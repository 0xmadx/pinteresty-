"""The vault must fail, not hang, when there is no usable session (S-2).

The original loop was `while not profile_id: sleep(5)` with no exit. An empty pool
did not raise — the process simply never returned. A scheduled job would wedge
overnight and report nothing, which is the worst available outcome: no data AND no
error to notice.

Offline: a fake Redis and a patched sleep, so the timeout is exercised in
milliseconds.

    .venv/Scripts/python.exe -m core.test_cookie_vault
"""
import contextlib
import io
import json
import time

from core.cookie_vault import RedisCookieVault, VaultEmpty

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


class FakeRedis:
    """Set + hash operations, enough for get_valid_account."""

    def __init__(self, sets=None, hashes=None):
        self.sets = {k: list(v) for k, v in (sets or {}).items()}
        self.hashes = hashes or {}
        self.srem_calls = []

    def srandmember(self, key):
        members = self.sets.get(key) or []
        return members[0] if members else None

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def srem(self, key, member):
        self.srem_calls.append((key, member))
        if key in self.sets and member in self.sets[key]:
            self.sets[key].remove(member)


def build(sets=None, hashes=None):
    vault = RedisCookieVault.__new__(RedisCookieVault)  # skip __init__'s live connect
    vault.redis_client = FakeRedis(sets, hashes)
    return vault


@contextlib.contextmanager
def quiet():
    """The vault narrates every wait and rejection; a hundred lines of it per run
    would bury the one line that matters."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# Keep the suite fast: the logic under test is the bound, not the wall clock.
_real_sleep = time.sleep
time.sleep = lambda _s: None

COOKIES = json.dumps({"session-key-www": "x"})

# --- the bug: an empty pool must raise, not spin forever ------------------------
vault = build(sets={"valid_profiles:etsy": []})
started = _real_sleep and True
try:
    vault.get_valid_account("etsy")
    check("empty pool raises", False, "returned instead of raising")
except VaultEmpty as exc:
    check("empty pool raises VaultEmpty", True)
    check("message names the platform", "etsy" in str(exc), str(exc))
    check("message points at the diagnostic", "vault_status" in str(exc), str(exc))
except RecursionError:
    check("empty pool raises VaultEmpty", False, "got RecursionError")

# VaultEmpty must be distinguishable from a genuine Etsy refusal — the two have
# different fixes (open Chrome vs back off).
check("VaultEmpty is not a generic Exception subclass only",
      issubclass(VaultEmpty, RuntimeError))

# --- a healthy profile still comes back unchanged -------------------------------
vault = build(
    sets={"valid_profiles:etsy": ["p1"]},
    hashes={"cookie:etsy:p1": {"cookies_json": COOKIES, "is_valid": "1"}},
)
account = vault.get_valid_account("etsy")
check("returns the profile", account["profile_id"] == "p1", account.get("profile_id"))
check("parses cookies_json to a dict", isinstance(account["cookies_json"], dict),
      type(account["cookies_json"]))

# --- a pool of unusable profiles terminates with the real reason ----------------
# Every private profile here has a csrf_token but no shop_id — the exact S-1 shape
# sitting in the live vault. Each is rejected and SREM'd, recursing once per profile.
many = {f"p{i}": {"cookies_json": COOKIES, "csrf_token": "t"} for i in range(40)}
vault = build(
    sets={"valid_profiles:etsy_private": list(many)},
    hashes={f"cookie:etsy_private:{k}": v for k, v in many.items()},
)
try:
    vault.get_valid_account("etsy_private")
    check("all-unusable pool raises", False, "returned an unusable profile")
except VaultEmpty as exc:
    check("all-unusable pool raises VaultEmpty", True)
    check("does not exhaust the stack first", "Rejected" in str(exc) or "No valid" in str(exc),
          str(exc))
except RecursionError:
    check("all-unusable pool raises VaultEmpty", False,
          "RecursionError — the depth bound is not working")

# --- a private profile missing seller fields is rejected, never returned --------
vault = build(
    sets={"valid_profiles:etsy_private": ["bad", "good"]},
    hashes={
        "cookie:etsy_private:bad": {"cookies_json": COOKIES, "csrf_token": "t"},
        "cookie:etsy_private:good": {"cookies_json": COOKIES, "csrf_token": "t",
                                     "shop_id": "56057851"},
    },
)
account = vault.get_valid_account("etsy_private")
check("skips the incomplete seller profile", account["profile_id"] == "good",
      account.get("profile_id"))
check("and removes it from the pool",
      ("valid_profiles:etsy_private", "bad") in vault.redis_client.srem_calls,
      vault.redis_client.srem_calls)

# --- a stale heartbeat is purged rather than used -------------------------------
stale = str(time.time() - 9999)
vault = build(
    sets={"valid_profiles:etsy": ["old"]},
    hashes={"cookie:etsy:old": {"cookies_json": COOKIES, "last_updated": stale}},
)
try:
    vault.get_valid_account("etsy")
    check("stale profile is not returned", False, "returned a dead profile")
except VaultEmpty:
    check("stale profile is purged, then pool is empty", True)

time.sleep = _real_sleep

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
