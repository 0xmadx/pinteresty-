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
        self.leases = {}

    def srandmember(self, key):
        members = self.sets.get(key) or []
        return members[0] if members else None

    def smembers(self, key):
        return set(self.sets.get(key) or [])

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def hset(self, key, field=None, value=None, mapping=None):
        h = self.hashes.setdefault(key, {})
        if mapping:
            h.update(mapping)
        elif field is not None:
            h[field] = value

    def srem(self, key, member):
        self.srem_calls.append((key, member))
        if key in self.sets and member in self.sets[key]:
            self.sets[key].remove(member)

    # --- lease -----------------------------------------------------------------
    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.leases:
            return None
        self.leases[key] = value
        return True

    def delete(self, key):
        self.leases.pop(key, None)


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

# Per platform, because the signed-out check looks for the cookie that actually
# carries a LOGIN and those differ. A jar that authenticates on Etsy is a
# logged-out jar on Pinterest.
COOKIES = json.dumps({"session-key-www": "x"})
PIN_COOKIES = json.dumps({"_auth": "1", "_pinterest_sess": "s"})
JAR = {"etsy": COOKIES, "etsy_private": COOKIES, "pinterest": PIN_COOKIES}

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
    # Recursion is now structurally impossible: the selector iterates the pool
    # instead of calling itself once per rejected profile, so MAX_REJECTIONS is no
    # longer load-bearing. The message must still carry the real reason.
    check("terminates with a real reason, not a stack error",
          "No leasable" in str(exc) and "vault_status" in str(exc), str(exc))
except RecursionError:
    check("all-unusable pool raises VaultEmpty", False,
          "RecursionError — the iterative selector regressed to recursion")

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

# --- S-13: a cookie-less profile is never handed out ----------------------------
# Four of these were sitting in the live pinterest pool. The seller check below them
# only guards etsy_private, so these would have gone out unauthenticated.
for platform in ("etsy", "pinterest"):
    vault = build(
        sets={f"valid_profiles:{platform}": ["hollow", "real"]},
        hashes={
            f"cookie:{platform}:hollow": {"is_valid": "1"},
            f"cookie:{platform}:real": {"cookies_json": JAR[platform], "is_valid": "1"},
        },
    )
    with quiet():
        account = vault.get_valid_account(platform)
    check(f"{platform}: skips the cookie-less profile", account["profile_id"] == "real",
          account.get("profile_id"))
    check(f"{platform}: and drops it from the pool",
          (f"valid_profiles:{platform}", "hollow") in vault.redis_client.srem_calls,
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


# --- fresh profiles are PREFERRED over heartbeat-less ones ----------------------
# private_seller_1 in the live vault has no heartbeat and IS the operator's seller
# session. It must not be evicted (nothing beams it back) but it must also not be
# chosen while something provably fresh exists.
fresh_beat = str(time.time())
vault = build(
    sets={"valid_profiles:etsy": ["nobeat", "fresh"]},
    hashes={
        "cookie:etsy:nobeat": {"cookies_json": COOKIES},
        "cookie:etsy:fresh": {"cookies_json": COOKIES, "last_updated": fresh_beat},
    },
)
with quiet():
    account = vault.get_valid_account("etsy")
check("prefers the profile with a fresh heartbeat", account["profile_id"] == "fresh",
      account.get("profile_id"))
check("and does NOT evict the heartbeat-less one — it is irreplaceable",
      ("valid_profiles:etsy", "nobeat") not in vault.redis_client.srem_calls,
      vault.redis_client.srem_calls)

# With nothing fresher available it IS used, rather than the run failing.
vault = build(
    sets={"valid_profiles:etsy": ["nobeat"]},
    hashes={"cookie:etsy:nobeat": {"cookies_json": COOKIES}},
)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    account = vault.get_valid_account("etsy")
check("falls back to the heartbeat-less profile when nothing else exists",
      account["profile_id"] == "nobeat", account.get("profile_id"))
check("and says loudly that freshness is unverifiable",
      "NO HEARTBEAT" in buf.getvalue(), buf.getvalue()[:120])

# --- signed out: a full cookie jar with no session key --------------------------
# This is the failure this check exists for. A logged-OUT browser still carries 30+
# analytics and consent cookies, so the old "is the jar non-empty" test passes, the
# request goes out anonymous, and Etsy answers with plausible PUBLIC data. The run
# succeeds while collecting the wrong thing.
logged_out = json.dumps({"datadome": "x", "_ga": "y", "uaid": "z", "user_prefs": "p"})
vault = build(
    sets={"valid_profiles:etsy": ["out", "in"]},
    hashes={
        "cookie:etsy:out": {"cookies_json": logged_out, "last_updated": fresh_beat},
        "cookie:etsy:in": {"cookies_json": COOKIES, "last_updated": fresh_beat},
    },
)
with quiet():
    account = vault.get_valid_account("etsy")
check("a signed-out jar is never handed out", account["profile_id"] == "in",
      account.get("profile_id"))

# Eviction is asserted separately, with ONLY the bad profile in the pool. The
# selector stops at the first usable candidate and the order is shuffled, so a bad
# profile sitting behind a good one may simply never be inspected on a given run —
# which is correct (why pay to judge what we do not need?) and means "was it
# evicted" is not a question the mixed-pool case can answer.
vault = build(
    sets={"valid_profiles:etsy": ["out"]},
    hashes={"cookie:etsy:out": {"cookies_json": logged_out, "last_updated": fresh_beat}},
)
try:
    with quiet():
        vault.get_valid_account("etsy")
    check("a signed-out jar is evicted once inspected", False, "returned it")
except VaultEmpty:
    check("a signed-out jar is evicted once inspected — it authenticates as nobody",
          ("valid_profiles:etsy", "out") in vault.redis_client.srem_calls,
          vault.redis_client.srem_calls)

pin_out = json.dumps({"csrftoken": "c", "_b": "b"})
vault = build(
    sets={"valid_profiles:pinterest": ["out"]},
    hashes={"cookie:pinterest:out": {"cookies_json": pin_out, "last_updated": fresh_beat}},
)
try:
    with quiet():
        vault.get_valid_account("pinterest")
    check("pinterest signed-out is rejected too", False, "returned a logged-out jar")
except VaultEmpty:
    check("pinterest signed-out is rejected too", True)

# --- the lease: two callers cannot hold one session -----------------------------
# Two runs driving one Etsy session from two places is the pattern a fingerprinter
# looks for, and nothing prevented it before.
vault = build(
    sets={"valid_profiles:etsy": ["only"]},
    hashes={"cookie:etsy:only": {"cookies_json": COOKIES, "last_updated": fresh_beat}},
)
with quiet():
    first = vault.get_valid_account("etsy")
check("the first caller gets the profile", first["profile_id"] == "only")
try:
    with quiet():
        vault.get_valid_account("etsy")
    check("a second caller cannot take the same profile", False, "double-leased")
except VaultEmpty:
    check("a second caller cannot take the same profile", True)

with quiet():
    vault.release("etsy", "only")
    again = vault.get_valid_account("etsy")
check("releasing hands it back", again["profile_id"] == "only")
vault.release("etsy", "only")
vault.release("etsy", "only")
check("release is safe to call twice", True)

# --- S-3: a double-encoded jar is a string, not a jar ---------------------------
vault = build(
    sets={"valid_profiles:etsy": ["dbl"]},
    hashes={"cookie:etsy:dbl": {"cookies_json": json.dumps(COOKIES),
                                "last_updated": fresh_beat}},
)
try:
    with quiet():
        vault.get_valid_account("etsy")
    check("a double-encoded jar is refused", False, "returned a string as cookies")
except VaultEmpty:
    check("a double-encoded jar is refused", True)

time.sleep = _real_sleep

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
