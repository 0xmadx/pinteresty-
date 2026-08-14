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
import hashlib
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

    # Blocking = this profile cannot serve a request, or will be gone before it does.
    # Warning  = it works, but degrades a defence. Conflating the two makes the tool
    # cry wolf, which is how a green vault gets reported as red.
    problems, warnings = [], []

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
        # SessionManager falls back to a hardcoded Chrome 124 UA, so the request still
        # goes out — but the UA no longer matches the browser that made the cookies,
        # which is exactly the mismatch DataDome looks for.
        warnings.append("no user_agent — falls back to hardcoded UA (ban risk)")

    age = None
    last_updated = data.get("last_updated")
    if last_updated:
        try:
            age = time.time() - float(last_updated)
            if age > HEARTBEAT_MAX_AGE:
                problems.append(f"heartbeat stale ({int(age)}s) — purged on next draw")
        except (ValueError, TypeError):
            warnings.append("last_updated unreadable")
    else:
        # cookie_vault only purges when last_updated is present, so no heartbeat means
        # this profile is never aged out. Old, but usable.
        warnings.append("no heartbeat — written by an older server; never auto-purged")

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
        "identity": session_identity(cookies),
        "problems": problems,
        "warnings": warnings,
    }


def session_identity(cookies):
    """A fingerprint of *which browser session* these cookies are, not which profile
    name they were filed under.

    `uaid` is Etsy's visitor id and `session-key-www` the login; together they identify
    one browser. Two profile ids sharing a fingerprint are the SAME session stored
    twice — which matters because the vault's whole defence is drawing a random
    profile per request. If the pool is one session under ten names, rotation buys
    nothing, and a 403 failover retires a name and then retries the identity that was
    just blocked (S-11).
    """
    if not cookies:
        return None
    parts = (cookies.get("uaid", ""), cookies.get("session-key-www", ""),
             cookies.get("_pinterest_sess", ""))
    if not any(parts):
        return None
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]


def find_shadow_vaults(configured_url, timeout=2):
    """Is another Redis answering on the same port, holding a fuller vault?

    Two Redis servers can share port 6379 on Windows: a native one bound to
    127.0.0.1 and Docker's proxy bound to 0.0.0.0. `localhost` resolves to loopback
    first, so the native one wins and Python silently reads a *different database*
    than the Go server writes to. That produces the worst possible symptom — an
    empty vault that looks like an auth problem (D-30).

    Returns candidates that hold more profiles than the configured URL does.
    """
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(configured_url)
    port = parsed.port or 6379

    def profile_count(url):
        try:
            client = redis.Redis.from_url(url, decode_responses=True,
                                          socket_connect_timeout=timeout)
            return sum(len(client.smembers(f"valid_profiles:{p}"))
                       for p in ("etsy", "etsy_private", "pinterest"))
        except Exception:
            return None

    here = profile_count(configured_url) or 0
    candidates = []
    for host in {"127.0.0.1", "host.docker.internal", socket.gethostbyname(socket.gethostname())}:
        url = f"redis://{host}:{port}/0"
        if url == configured_url:
            continue
        found = profile_count(url)
        if found is not None and found > here:
            candidates.append((url, found))
    return sorted(candidates, key=lambda c: -c[1])


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


def plan_prune(client, config):
    """Which profiles should go, and why. Computes only — never writes.

    Four rules, in order of how badly the entry misleads:

      1. no cookies              — authenticates as nobody (S-13)
      2. seller session in `etsy`— D-29: the irreplaceable account doing risky work
      3. non-seller in etsy_private — a buyer session mis-filed by the old "auto" role
      4. duplicate of a session already kept — a name, not capacity (S-11)

    Rule 4 keeps the BEST profile per session, not the newest: completeness and pool
    membership beat recency, because the one verified-working seller profile predates
    the heartbeat field and would lose a pure freshness contest to a broken sibling.
    """
    seller_identity = None
    private_key = "cookie:etsy_private:"
    for key in client.scan_iter(f"{private_key}*"):
        data = client.hgetall(key)
        if data.get("shop_id") and data.get("csrf_token") and data.get("cookies_json"):
            try:
                cookies = json.loads(data["cookies_json"])
            except (ValueError, TypeError):
                continue
            if isinstance(cookies, dict):
                seller_identity = session_identity(cookies)
                break

    expected = config.expected_sessions
    doomed, kept = [], []

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
                cookies = {}
            try:
                updated = float(data.get("last_updated") or 0)
            except (ValueError, TypeError):
                updated = 0
            entries.append({
                "key": key, "platform": platform, "profile_id": profile_id,
                "identity": session_identity(cookies), "n_cookies": len(cookies),
                "in_pool": profile_id in pool, "updated": updated,
                "complete": bool(cookies) and (
                    platform != "etsy_private"
                    or (data.get("csrf_token") and data.get("shop_id"))),
            })

        survivors = []
        for e in entries:
            if not e["n_cookies"]:
                e["reason"] = "no cookies — authenticates as nobody (S-13)"
                doomed.append(e)
            elif platform == "etsy" and seller_identity and e["identity"] == seller_identity:
                e["reason"] = "SELLER session in the public pool (D-29)"
                doomed.append(e)
            elif platform == "etsy_private" and seller_identity and e["identity"] != seller_identity:
                e["reason"] = "not the seller session — mis-filed by the old 'auto' role"
                doomed.append(e)
            else:
                survivors.append(e)

        # Best first, then everything after the first of each identity is a duplicate.
        survivors.sort(key=lambda e: (e["complete"], e["in_pool"], e["updated"]),
                       reverse=True)
        seen = {}
        for e in survivors:
            ident = e["identity"]
            if ident in seen:
                e["reason"] = f"duplicate of {seen[ident]} — same session, another name"
                doomed.append(e)
            else:
                seen[ident] = e["profile_id"]
                kept.append(e)

        want = expected.get(platform)
        if want is not None and len(seen) > want:
            # More distinct sessions than accounts. The extras are old logins of the
            # same account; keep the best `want` and retire the rest.
            ranked = [e for e in kept if e["platform"] == platform]
            for e in ranked[want:]:
                e["reason"] = (f"{len(seen)} sessions but {want} account(s) run — "
                               f"retiring the least complete")
                doomed.append(e)
                kept.remove(e)

    return doomed, kept, seller_identity


def apply_prune(client, doomed, backup_path):
    """Delete, after writing every field of every doomed profile to disk.

    The backup is what makes this reversible in the moment. The real recovery is
    re-syncing from Chrome — one page load per account — but that requires the
    operator to be there, and a mistake here should not need them.
    """
    import pathlib

    dump = []
    for e in doomed:
        dump.append({"key": e["key"], "platform": e["platform"],
                     "profile_id": e["profile_id"], "reason": e["reason"],
                     "fields": client.hgetall(e["key"])})

    path = pathlib.Path(backup_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dump, indent=2), encoding="utf-8")

    for e in doomed:
        client.srem(f"valid_profiles:{e['platform']}", e["profile_id"])
        client.delete(e["key"])
    return path


def main(verbose=False):
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
        # Only the broken ones in full; usable profiles are summarised, since a healthy
        # vault holds dozens and the point of this tool is to surface what is wrong.
        for p in state["profiles"]:
            if not p["problems"] and not verbose:
                continue
            age = f"{int(p['age'])}s ago" if p["age"] is not None else "no heartbeat"
            print(f"      {p['profile_id']}  cookies={p['n_cookies']}"
                  f"  shop_id={p['shop_id'] or '-'}  csrf={'y' if p['has_csrf'] else 'n'}"
                  f"  {age}")
            for problem in p["problems"]:
                print(f"        ✗ {problem}")
            for warning in p["warnings"]:
                print(f"        · {warning}")
        if usable:
            names = ", ".join(p["profile_id"] for p in state["usable"][:6])
            more = f" +{usable - 6} more" if usable > 6 else ""
            print(f"      usable: {names}{more}")
            degraded = sum(1 for p in state["usable"] if p["warnings"])
            if degraded:
                print(f"      ⚠️  {degraded} of them have no user_agent (S-9 — ban risk)")
        print()

    # How many DISTINCT browser sessions back the usable pool, and is the seller
    # session sitting in the public pool?
    identities = {}
    for platform, state in report.items():
        for p in state["usable"]:
            if p["identity"]:
                identities.setdefault(p["identity"], {}).setdefault(platform, []).append(
                    p["profile_id"])

    expected = config.expected_sessions
    for platform, state in report.items():
        usable = state["usable"]
        distinct = {p["identity"] for p in usable if p["identity"]}
        want = expected.get(platform)

        if usable and len(distinct) < len(usable):
            print(f"⚠️  {platform}: {len(usable)} usable profile names, but only "
                  f"{len(distinct)} distinct session(s) (S-11).")
            print(f"    Rotation gives no identity diversity — a 403 failover retires a "
                  f"name and redraws the same session.")

        if want is None:
            continue
        if len(distinct) > want:
            print(f"    ({platform}: {len(distinct)} sessions vs {want} account(s) you "
                  f"run — {len(distinct) - want} stale or duplicated.)")
        elif len(distinct) < want:
            print(f"🚨 {platform}: only {len(distinct)} of your {want} account(s) are "
                  f"syncing. One is signed out, or its browser has no role set.")

    leaked = {ident: places for ident, places in identities.items()
              if "etsy_private" in places and "etsy" in places}
    if leaked:
        print()
        print("🚨 D-29 VIOLATION — the SELLER session is also in the PUBLIC pool:")
        for ident, places in leaked.items():
            print(f"    session {ident}")
            print(f"      as seller : {', '.join(places['etsy_private'])}")
            print(f"      as public : {', '.join(places['etsy'])}")
        print("    Competitor scraping will draw the seller account. Remove the public")
        print("    copies, or the one account you cannot replace is doing the risky work.")
    print()

    if blocked:
        # Before blaming the extension, check we are even reading the right database.
        shadows = find_shadow_vaults(config.REDIS_URL)
        if shadows:
            url, count = shadows[0]
            print("🔎 A DIFFERENT Redis on this port holds a fuller vault:")
            print(f"      {url}  → {count} valid profiles")
            print(f"      (configured: {config.REDIS_URL})")
            print("   Two servers share the port; `localhost` resolves to the wrong one.")
            print(f"   Point REDIS_URL at the address above, or stop the stray server.")
            print("   See docs/architecture/10_session_layer.md §3a (D-30)")
            return 1

        print(f"No usable profile for: {', '.join(blocked)}")
        print("Pipelines raise VaultEmpty rather than run on nothing. To fix:")
        if "etsy" in blocked or "etsy_private" in blocked:
            print("  · Etsy: open the extension popup and say whether that browser is")
            print("    signed in as a buyer or as your seller account. Undeclared means")
            print("    Etsy is skipped on purpose — we will not guess which it is.")
            print("    Then load any Etsy page to sync.")
        if "etsy_private" in blocked:
            print("  · Seller specifically: open SHOP MANAGER. shop_id is only captured")
            print("    from a URL matching /shop/<digits>/ — cookies and csrf alone are")
            print("    not enough and the profile will be rejected.")
        if "pinterest" in blocked:
            print("  · Pinterest: just load a Pinterest page. No declaration needed.")
        print("  Then re-run this check.  See docs/architecture/10_session_layer.md")
        return 1

    print("Vault is green — live calls will work.")
    return 0


def prune_main(apply=False):
    config = ScraperConfig()
    client = redis.Redis.from_url(config.REDIS_URL, decode_responses=True)
    client.ping()

    doomed, kept, seller = plan_prune(client, config)
    print(f"Vault: {config.REDIS_URL}")
    print(f"Seller session: {seller or '(none identified)'}\n")

    if not doomed:
        print("Nothing to prune.")
        return 0

    by_reason = {}
    for e in doomed:
        by_reason.setdefault(e["reason"], []).append(e)
    for reason, entries in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"DELETE ({len(entries)}) — {reason}")
        for e in sorted(entries, key=lambda x: (x["platform"], x["profile_id"])):
            pool = "in pool" if e["in_pool"] else "       "
            print(f"    {e['platform']:<14} {e['profile_id']:<26} "
                  f"{e['n_cookies']:>3} cookies  {pool}")
        print()

    print("KEEP")
    for e in sorted(kept, key=lambda x: (x["platform"], x["profile_id"])):
        print(f"    {e['platform']:<14} {e['profile_id']:<26} "
              f"{e['n_cookies']:>3} cookies  session {e['identity']}")
    print(f"\n{len(doomed)} to delete, {len(kept)} to keep.")

    if not apply:
        print("\nDry run. Re-run with --apply to perform it.")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = apply_prune(client, doomed, f"data/vault_backup_{stamp}.json")
    print(f"\nDeleted {len(doomed)} profiles. Backup: {path}")
    print("Re-sync from Chrome to repopulate: one page load per account.")
    return 0


if __name__ == "__main__":
    import sys
    if "--prune" in sys.argv:
        raise SystemExit(prune_main(apply="--apply" in sys.argv))
    raise SystemExit(main(verbose="-v" in sys.argv))
