"""Blocking vs warning classification in the vault diagnostic.

Exists because the first version got this wrong in the direction that matters: it
treated a missing user_agent and a missing heartbeat as blocking, and reported a vault
holding 20 working profiles as "0 usable". A diagnostic that cries wolf is worse than
none — the operator learns to ignore it, and then misses the real outage.

Offline: a fake Redis client, no network, no container.

    .venv/Scripts/python.exe -m core.test_vault_status
"""
import json
import time

from core.vault_status import _profile_report

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


class FakeRedis:
    """Only hgetall is used by _profile_report."""

    def __init__(self, fields):
        self._fields = fields

    def hgetall(self, key):
        return dict(self._fields)


def report(platform="etsy", in_pool=True, **fields):
    base = {"is_valid": "1", "last_updated": str(time.time())}
    base.update(fields)
    return _profile_report(FakeRedis(base), platform, "p1", in_pool)


COOKIES = json.dumps({"session-key-www": "x", "uaid": "y"})


# --- a healthy profile is usable, with nothing to say about it -------------------
r = report(cookies_json=COOKIES, user_agent="Mozilla/5.0 ...")
check("healthy: no problems", r["problems"] == [], r["problems"])
check("healthy: no warnings", r["warnings"] == [], r["warnings"])
check("healthy: counts cookies", r["n_cookies"] == 2, r["n_cookies"])

# --- the two that must NOT block ------------------------------------------------
r = report(cookies_json=COOKIES)  # no user_agent
check("no UA does not block", r["problems"] == [], r["problems"])
check("no UA warns", any("user_agent" in w for w in r["warnings"]), r["warnings"])

r = report(cookies_json=COOKIES, user_agent="UA", last_updated=None)
del_fields = {k: v for k, v in {"cookies_json": COOKIES, "user_agent": "UA"}.items()}
r = _profile_report(FakeRedis({"is_valid": "1", **del_fields}), "etsy", "p1", True)
check("no heartbeat does not block", r["problems"] == [], r["problems"])
check("no heartbeat warns", any("heartbeat" in w for w in r["warnings"]), r["warnings"])
# cookie_vault only purges when last_updated is PRESENT, so absent == never purged.
# Blocking on it would condemn every profile written by the older server.

# --- the ones that must block ---------------------------------------------------
r = report(cookies_json=COOKIES, in_pool=False)
check("out of pool blocks", any("valid pool" in p for p in r["problems"]), r["problems"])

r = report(cookies_json=COOKIES, is_valid="0")
check("is_valid=0 blocks", any("invalid" in p for p in r["problems"]), r["problems"])

r = report()
check("no cookies blocks", any("NO COOKIES" in p for p in r["problems"]), r["problems"])

stale = str(time.time() - 999)
r = report(cookies_json=COOKIES, last_updated=stale)
check("stale heartbeat blocks", any("purged" in p for p in r["problems"]), r["problems"])
# It is *about* to be SREM'd by get_valid_account, so it is not dependable capacity.

# --- S-3: the popup's double-encoded payload ------------------------------------
r = report(cookies_json=json.dumps(COOKIES))  # a JSON string, not an object
check("double-encoded blocks", any("double-encoded" in p for p in r["problems"]),
      r["problems"])
check("double-encoded reads 0 cookies", r["n_cookies"] == 0, r["n_cookies"])

r = report(cookies_json="{not json")
check("unparseable blocks", any("unparseable" in p for p in r["problems"]), r["problems"])

# --- private tier needs all three seller fields ---------------------------------
r = report(platform="etsy_private", cookies_json=COOKIES, csrf_token="t", shop_id="123")
check("complete private profile is usable", r["problems"] == [], r["problems"])

r = report(platform="etsy_private", cookies_json=COOKIES, csrf_token="t")
check("private without shop_id blocks",
      any("shop_id" in p for p in r["problems"]), r["problems"])

r = report(platform="etsy_private", cookies_json=COOKIES, shop_id="123")
check("private without csrf blocks",
      any("csrf_token" in p for p in r["problems"]), r["problems"])

# The observed S-1 signature: seller tokens arrived, cookies went to the other
# platform. Must block — it is the exact shape that cannot authenticate.
r = report(platform="etsy_private", csrf_token="t", shop_id="123")
check("S-1 signature (tokens, no cookies) blocks",
      any("NO COOKIES" in p for p in r["problems"]), r["problems"])

# --- the same fields are only a warning on the public tier ----------------------
r = report(platform="etsy", cookies_json=COOKIES)
check("public tier needs no shop_id", r["problems"] == [], r["problems"])

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
