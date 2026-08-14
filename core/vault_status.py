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
        "problems": problems,
        "warnings": warnings,
    }


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
    import sys
    raise SystemExit(main(verbose="-v" in sys.argv))
