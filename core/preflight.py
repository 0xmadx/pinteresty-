"""Check every session a run needs BEFORE it starts, and tidy the vault while looking.

The failure this prevents: a crawl gets forty keywords in, reaches the first call that
needs a different platform, and only then discovers there is no session for it. With
the old unbounded wait that hung forever; now it raises — but it still raises *after*
partial work, on a half-populated run, at whatever hour the scheduler fired.

So the contract is: state every platform a run will touch, up front.

    from core.preflight import require
    require("etsy", "etsy_private")      # raises PreflightFailed, or returns a report

Hygiene runs in the same pass because the checks are the same reads. Only the
unambiguous rules are automatic — an entry that cannot work, or is a second name for
a session already kept. Deciding that an operator has *too many* real accounts is a
judgement call and stays manual (`vault_status --prune`).
"""
import json

import redis

from core.settings import ScraperConfig
from core.vault_status import scan, session_identity


class PreflightFailed(RuntimeError):
    """A required platform has no usable session. Carries the operator-facing report."""

    def __init__(self, message, report=None):
        super().__init__(message)
        self.report = report or {}


# Rules safe to apply without asking. Each removes an entry that is either unusable or
# indistinguishable from one being kept — never the last good session for a platform.
def hygiene(client, dry_run=False):
    """Retire entries that cannot serve a request. Returns what was (or would be) cut.

    Deliberately NOT included: trimming to the expected account count. That rule
    decides which of several *working* sessions to discard, which is the operator's
    call — see `vault_status --prune`.
    """
    removed = []
    for platform in ("etsy", "etsy_private", "pinterest"):
        pool = set(client.smembers(f"valid_profiles:{platform}"))
        entries = []
        for key in client.scan_iter(f"cookie:{platform}:*"):
            profile_id = key.split(":", 2)[2]
            data = client.hgetall(key)
            try:
                cookies = json.loads(data.get("cookies_json") or "{}")
            except (ValueError, TypeError):
                cookies = {}
            if not isinstance(cookies, dict):
                cookies = {}          # S-3 double-encoded: unusable either way
            try:
                updated = float(data.get("last_updated") or 0)
            except (ValueError, TypeError):
                updated = 0
            complete = bool(cookies) and (
                platform != "etsy_private"
                or (data.get("csrf_token") and data.get("shop_id")))
            entries.append({
                "key": key, "platform": platform, "profile_id": profile_id,
                "identity": session_identity(cookies), "in_pool": profile_id in pool,
                "updated": updated, "complete": complete,
                "is_valid": data.get("is_valid") != "0",
            })

        keepers = []
        for e in entries:
            if not e["identity"]:
                e["reason"] = "no usable cookies"
            elif not e["is_valid"]:
                # Set by mark_invalid() after a 403/DataDome block. The session is
                # spent; keeping it means redrawing a blocked identity (S-11).
                e["reason"] = "retired by a 403 failover"
            elif platform == "etsy_private" and not e["complete"]:
                e["reason"] = "private profile without csrf/shop_id — cannot authenticate"
            else:
                keepers.append(e)
                continue
            removed.append(e)

        # Same session under several names: keep the best, drop the rest.
        keepers.sort(key=lambda e: (e["complete"], e["in_pool"], e["updated"]),
                     reverse=True)
        seen = {}
        for e in keepers:
            if e["identity"] in seen:
                e["reason"] = f"duplicate of {seen[e['identity']]}"
                removed.append(e)
            else:
                seen[e["identity"]] = e["profile_id"]

    if not dry_run:
        for e in removed:
            client.srem(f"valid_profiles:{e['platform']}", e["profile_id"])
            client.delete(e["key"])
    return removed


def require(*platforms, clean=True, config=None):
    """Assert a usable session exists for each platform. Raises PreflightFailed.

    Returns {platform: {"sessions": n, "profiles": [...]}} so a caller can log what it
    is about to run as — useful when a run is later found to have used one identity
    for everything.
    """
    config = config or ScraperConfig()

    # Pull the latest sessions from the SHARED vault into this project's private
    # one before judging whether we have any. Without this the separation would
    # trade one problem for a worse one: our pool would silently go stale while
    # the extension kept beaming fresh cookies into a database we no longer read,
    # and preflight would refuse a run that should have gone ahead.
    #
    # Deliberately non-fatal. The mirror being unavailable is not the same as
    # having no session — we may hold a perfectly good copy already — so a failure
    # here is reported and the real check below decides.
    # The report stays keyed by platform and nothing else — a caller iterating it
    # must never trip over a bookkeeping key. The mirror's own result is available
    # from core.vault_mirror.sync() for anyone who wants it.
    try:
        from core.vault_mirror import sync
        sync()
    except Exception as exc:
        print(f"[preflight] could not refresh from the shared vault: {exc}")
        print("    Continuing with the copy we already hold.")

    client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.exceptions.ConnectionError as exc:
        raise PreflightFailed(
            f"Vault unreachable at {config.REDIS_URL}: {exc}\n"
            f"  Start it:  docker compose up -d redis go-api") from exc

    cleaned = hygiene(client) if clean else []

    report, missing = {}, []
    state = scan(platforms)
    for platform in platforms:
        usable = state[platform]["usable"]
        identities = {p["identity"] for p in usable if p["identity"]}
        report[platform] = {
            "sessions": len(identities),
            "profiles": [p["profile_id"] for p in usable],
        }
        if not usable:
            missing.append(platform)

    if missing:
        lines = [f"No usable session for: {', '.join(missing)}.",
                 f"Refusing to start — a run that discovers this halfway through "
                 f"leaves partial data and a misleading run log."]
        if cleaned:
            lines.append(f"({len(cleaned)} dead profiles retired during this check.)")
        for platform in missing:
            if platform == "etsy_private":
                lines.append("  · etsy_private: open Etsy SHOP MANAGER in the browser "
                             "marked as your seller. shop_id is only captured from a "
                             "/shop/<digits>/ URL.")
            elif platform == "etsy":
                lines.append("  · etsy: set that browser's Etsy account type to Buyer "
                             "in the extension popup, then load any Etsy page.")
            else:
                lines.append(f"  · {platform}: load a {platform} page. No declaration "
                             f"needed.")
        lines.append("  Check with:  python -m core.vault_status")
        raise PreflightFailed("\n".join(lines), report)

    return report


if __name__ == "__main__":
    import sys

    wanted = [a for a in sys.argv[1:] if not a.startswith("-")] or \
             ["etsy", "etsy_private", "pinterest"]
    try:
        result = require(*wanted, clean="--no-clean" not in sys.argv)
    except PreflightFailed as exc:
        print(exc)
        raise SystemExit(1)
    for platform, info in result.items():
        print(f"✅ {platform:<14} {info['sessions']} session(s): "
              f"{', '.join(info['profiles'])}")
    print("\nPreflight passed — safe to start a run.")
