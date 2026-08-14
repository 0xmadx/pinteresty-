"""Is the session vault usable right now? — read-only diagnostic.

Answers the one question that blocks every live run, and answers it in one second
instead of by hanging. Run before any long pipeline:

    .venv/Scripts/python.exe -m core.vault_status

Deliberately does NOT call `RedisCookieVault.get_valid_account()`: that method blocks
forever on an empty pool (S-2 in `docs/architecture/10_session_layer.md`), which is
exactly the situation this tool exists to report. It reads the keys directly.

Observation only — it never writes to Redis, never mutates a profile, and adds no
session-handling capability. The access layer is read-only (see the skill, Rule 6).
"""
import json
import time

import redis

from core.settings import ScraperConfig

# A private profile needs all of these or it cannot authenticate as a seller.
PRIVATE_REQUIRED = ("cookies_json", "csrf_token", "shop_id")
HEARTBEAT_MAX_AGE = 300  # must match cookie_vault.py's purge threshold


def _profile_report(client, platform, profile_id, in_valid_set):
    """One profile's real state. Every problem is named, not summarised as a bool."""
    data = client.hgetall(f"cookie:{platform}:{profile_id}")
    cookies = {}
    raw = data.get("cookies_json")
    if raw:
        try:
            parsed = json.loads(raw)
            # S-3: force_sync double-encodes, so this can legitimately be a str.
            cookies = parsed if isinstance(parsed, dict) else {}
            if not isinstance(parsed, dict):
                data["_double_encoded"] = True
        except (ValueError, TypeError):
            data["_unparseable"] = True

    problems = []
    if not in_valid_set:
        problems.append("not in valid pool")
    if data.get("is_valid") == "0":
        problems.append("marked invalid (a 403/429 failover retired it)")
    if not cookies:
        problems.append("NO COOKIES")
    if data.get("_double_encoded"):
        problems.append("cookies_json double-encoded — S-3, popup Save button")
    if data.get("_unparseable"):
        problems.append("cookies_json unparseable")
    if not data.get("user_agent"):
        problems.append("no user_agent (written before UA sync, or by an old server)")

    age = None
    last_updated = data.get("last_updated")
    if last_updated:
        try:
            age = time.time() - float(last_updated)
            if age > HEARTBEAT_MAX_AGE:
                problems.append(f"heartbeat stale ({int(age)}s) — will be purged")
        except (ValueError, TypeError):
            problems.append("last_updated unreadable")
    else:
        problems.append("no heartbeat — never seen by the current Go server")

    if platform == "etsy_private":
        missing = [f for f in PRIVATE_REQUIRED if not data.get(f)]
        if missing:
            problems.append(f"seller fields missing: {', '.join(missing)}")

    return {
        "profile_id": profile_id,
        "n_cookies": len(cookies),
        "shop_id": data.get("shop_id"),
        "has_csrf": bool(data.get("csrf_token")),
        "age": age,
        "problems": problems,
    }


def scan(platforms=("etsy", "etsy_private", "pinterest")):
    """The vault's state per platform. Never blocks, never writes."""
    config = ScraperConfig()
    client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    client.ping()  # fail loudly here rather than deep inside a pipeline

    report = {}
    for platform in platforms:
        valid = set(client.smembers(f"valid_profiles:{platform}"))
        known = {k.split(":", 2)[2] for k in client.scan_iter(f"cookie:{platform}:*")}
        profiles = [_profile_report(client, platform, p, p in valid)
                    for p in sorted(known | valid)]
        report[platform] = {
            "valid_count": len(valid),
            "usable": [p for p in profiles if not p["problems"]],
            "profiles": profiles,
        }
    return report


def main():
    config = ScraperConfig()
    print(f"Vault: {config.REDIS_URL}\n")
    try:
        report = scan()
    except redis.exceptions.ConnectionError as exc:
        print(f"❌ Redis unreachable: {exc}")
        print("   Start it:  docker compose up -d redis go-api")
        return 1

    blocked = []
    for platform, state in report.items():
        usable = len(state["usable"])
        mark = "✅" if usable else ("⚠️ " if state["profiles"] else "❌")
        print(f"{mark} {platform:<14} {usable} usable / {len(state['profiles'])} known")
        if not usable:
            blocked.append(platform)
        for p in state["profiles"]:
            age = f"{int(p['age'])}s ago" if p["age"] is not None else "no heartbeat"
            print(f"      {p['profile_id']}  cookies={p['n_cookies']}"
                  f"  shop_id={p['shop_id'] or '-'}  csrf={'y' if p['has_csrf'] else 'n'}"
                  f"  {age}")
            for problem in p["problems"]:
                print(f"        · {problem}")
        print()

    if blocked:
        print(f"No usable profile for: {', '.join(blocked)}")
        print("Any pipeline touching these will HANG, not fail (S-2). Fix first:")
        print("  1. Open the extension popup and set the profile role explicitly")
        print("     ('auto' is the default and matches no branch — S-1).")
        print("  2. Reload an Etsy Shop Manager tab so cookies AND the csrf/shop_id")
        print("     hook both fire for that role.")
        print("  3. Re-run this check.")
        print("  See docs/architecture/10_session_layer.md §3")
        return 1

    print("Vault is green — live calls will work.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
