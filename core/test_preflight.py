"""Preflight refuses to start a run that cannot finish, and tidies while it looks.

Two failures this prevents, both observed:

  * a crawl reaches its first etsy_private call forty keywords in, discovers there is
    no seller session, and dies on a half-populated run
  * the vault accumulates a new profile id per re-sync until one browser wears ten
    names, at which point "rotation" redraws the identity that was just blocked

Offline: a fake Redis, no container.

    .venv/Scripts/python.exe -m core.test_preflight
"""
import json

import core.preflight as preflight
import core.vault_status as vault_status
from core.preflight import PreflightFailed

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def cookies(uaid, session="S"):
    return json.dumps({"uaid": uaid, "session-key-www": session, "extra": "x"})


class FakeRedis:
    def __init__(self, hashes=None, sets=None):
        self.hashes = hashes or {}
        self.sets = {k: set(v) for k, v in (sets or {}).items()}

    def ping(self):
        return True

    def smembers(self, key):
        return set(self.sets.get(key, set()))

    def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in list(self.hashes) if k.startswith(prefix)]

    def srem(self, key, member):
        self.sets.get(key, set()).discard(member)

    def delete(self, key):
        self.hashes.pop(key, None)

    def keys(self, _pattern):
        return list(self.hashes)


def install(fake):
    """Both modules build their own client; point them at the same fake."""
    preflight.redis.Redis.from_url = staticmethod(lambda *a, **k: fake)
    vault_status.redis.Redis.from_url = staticmethod(lambda *a, **k: fake)


# --- a complete vault passes, and reports what it will run as --------------------
fake = FakeRedis(
    hashes={
        "cookie:etsy:buyer": {"cookies_json": cookies("U1"), "is_valid": "1"},
        "cookie:etsy_private:seller": {"cookies_json": cookies("U2"), "is_valid": "1",
                                       "csrf_token": "t", "shop_id": "56057851"},
        "cookie:pinterest:pin_a": {"cookies_json": cookies("U3"), "is_valid": "1"},
    },
    sets={"valid_profiles:etsy": ["buyer"],
          "valid_profiles:etsy_private": ["seller"],
          "valid_profiles:pinterest": ["pin_a"]},
)
install(fake)
report = preflight.require("etsy", "etsy_private", "pinterest")
check("complete vault passes", set(report) == {"etsy", "etsy_private", "pinterest"})
check("reports the identity a run will use",
      report["etsy_private"]["profiles"] == ["seller"], report["etsy_private"])

# --- the whole point: refuse UP FRONT, not mid-run -------------------------------
fake = FakeRedis(
    hashes={"cookie:etsy:buyer": {"cookies_json": cookies("U1"), "is_valid": "1"}},
    sets={"valid_profiles:etsy": ["buyer"]},
)
install(fake)
try:
    preflight.require("etsy", "etsy_private")
    check("missing platform refuses", False, "returned instead of raising")
except PreflightFailed as exc:
    check("missing platform raises PreflightFailed", True)
    check("names the missing platform", "etsy_private" in str(exc), str(exc))
    check("says why refusing beats failing late", "partial" in str(exc).lower(), str(exc))
    check("tells the operator to open Shop Manager",
          "SHOP MANAGER" in str(exc).upper(), str(exc))

# A platform that IS present must not be dragged down by a missing sibling.
install(fake)
check("still passes for the platform that is fine",
      set(preflight.require("etsy")) == {"etsy"})

# --- hygiene: the rules that are safe to apply unasked ---------------------------
fake = FakeRedis(
    hashes={
        # one real session under three names — the accumulation the operator reported
        "cookie:etsy:name_a": {"cookies_json": cookies("SAME"), "is_valid": "1",
                               "last_updated": "100"},
        "cookie:etsy:name_b": {"cookies_json": cookies("SAME"), "is_valid": "1",
                               "last_updated": "200"},
        "cookie:etsy:name_c": {"cookies_json": cookies("SAME"), "is_valid": "1",
                               "last_updated": "300"},
        # spent by a 403 failover
        "cookie:etsy:blocked": {"cookies_json": cookies("OTHER"), "is_valid": "0"},
        # cannot authenticate as anyone
        "cookie:etsy:hollow": {"is_valid": "1"},
        # a genuinely different, working account must survive
        "cookie:etsy:second": {"cookies_json": cookies("SECOND"), "is_valid": "1",
                               "last_updated": "400"},
    },
    sets={"valid_profiles:etsy": ["name_a", "name_b", "name_c", "blocked", "hollow",
                                  "second"]},
)
install(fake)
removed = preflight.hygiene(fake)
reasons = {e["profile_id"]: e["reason"] for e in removed}
check("retires the 403-blocked profile", "retired" in reasons.get("blocked", ""),
      reasons)
check("retires the cookie-less profile", "no usable cookies" in reasons.get("hollow", ""),
      reasons)
check("collapses three names to one session", len(
    [p for p in ("name_a", "name_b", "name_c") if p in reasons]) == 2, reasons)
check("keeps the freshest of the duplicates", "name_c" not in reasons, reasons)
check("never removes a distinct working account", "second" not in reasons, reasons)
check("survivors remain in the pool",
      fake.sets["valid_profiles:etsy"] == {"name_c", "second"},
      fake.sets["valid_profiles:etsy"])

# --- hygiene must not empty a platform down to nothing usable --------------------
# Adding accounts later means more identities, not more names; the rule scales because
# it keys on session, not on how many profiles happen to exist.
fake = FakeRedis(
    hashes={f"cookie:pinterest:acct{i}": {"cookies_json": cookies(f"U{i}"),
                                          "is_valid": "1", "last_updated": "1"}
            for i in range(5)},
    sets={"valid_profiles:pinterest": [f"acct{i}" for i in range(5)]},
)
install(fake)
preflight.hygiene(fake)
check("five distinct accounts all survive hygiene",
      len(fake.sets["valid_profiles:pinterest"]) == 5,
      fake.sets["valid_profiles:pinterest"])

# --- dry run changes nothing ------------------------------------------------------
fake = FakeRedis(
    hashes={"cookie:etsy:hollow": {"is_valid": "1"}},
    sets={"valid_profiles:etsy": ["hollow"]},
)
install(fake)
would = preflight.hygiene(fake, dry_run=True)
check("dry run reports the removal", len(would) == 1, would)
check("dry run deletes nothing", "cookie:etsy:hollow" in fake.hashes)

# --- every live entry point must refresh the mirror before it runs -----------------
# This project reads a MIRROR of the shared vault (D-33) and nothing refreshes it on
# its own. `Scheduler.run_job` gets the refresh for free because it calls preflight,
# but a CLI entry point does not — and a stale mirror does not fail cleanly. The
# fresh profile ages past the eviction threshold, the pool falls back to the
# heartbeat-less seller profile (never evicted by design, D-35), and that returns a
# 401 partway through a pipeline. Measured 2026-08-21: db0 fresh at 125s while db1
# held a copy 7,473s old, and every direct run 401'd while `vault_status` — which
# syncs — reported the vault green minutes earlier.
import pathlib  # noqa: E402
import re  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
LIVE_CLIENTS = re.compile(r"EtsyPrivateAPI\(\)|EtsyPublicAPI\(\)|PinterestTrendsAPI\(")

# ⚠️ This list was ONCE three CLI files, and that hand-maintained list is exactly
# why the MCP server shipped without a sync (found 2026-08-25 when the agent
# reported "0 usable sessions" to the operator while Chrome was beaming fine —
# the mirror lagged 131s, sessions expire at 300s, so our copy aged out first).
# A list you have to remember to extend is not a guard. `test_every_live_entry_point`
# below walks the tree instead; these three stay as named regressions.
for module in ["etsy/analytics/discover.py",
               "etsy/analytics/filter_trust.py",
               "etsy/engines/master_arbitrage.py",
               "mcp_server/server.py"]:
    source = (ROOT / module).read_text(encoding="utf-8")
    name = module.rsplit("/", 1)[-1]
    check(f"{name} builds a live client (so it needs a session)",
          bool(LIVE_CLIENTS.search(source)), name)
    check(f"{name} preflights first, refreshing the mirror",
          "from core.preflight import require" in source
          or "vault_mirror import sync" in source,
          f"{name} instantiates a live API client without refreshing the mirror — a "
          f"stale copy will surface as a 401 mid-run, or as a false 'no sessions'")

# --- the guard that does NOT depend on remembering to update a list ---------------
# Walk every module that builds a live client and demand it refreshes the mirror
# first, by whatever route. Anything genuinely session-free is listed as exempt
# with a reason, so an addition here is a deliberate act rather than an omission.
#
# The rule is narrower than "constructs a client", and deliberately so. A library
# reached THROUGH the scheduler inherits `run_job`'s preflight; it is only a
# module you can run DIRECTLY that can start a live call against an unsynced
# mirror. So the guard is: builds a live client AND has its own __main__.
EXEMPT = {
    # The access layer and the sync itself — refreshing here would recurse.
    "core/session_manager.py": "IS the access layer",
    "core/cookie_vault.py": "IS the access layer",
    "core/vault_mirror.py": "IS the mirror",
    "core/vault_status.py": "syncs internally; see separation_check",
    "core/preflight.py": "IS the sync",
}
CONSTRUCTS_LIVE = re.compile(r"EtsyPrivateAPI\(\)|EtsyPublicAPI\(\)|PinterestTrendsAPI\(")
HAS_MAIN = re.compile(r"^if __name__ == [\"']__main__[\"']", re.M)
REFRESHES = re.compile(r"from core\.preflight import require|vault_mirror import sync"
                       r"|preflight\.require|_sync_mirror|require\(")

runnable, missing = [], []
for path in ROOT.rglob("*.py"):
    rel = path.relative_to(ROOT).as_posix()
    if any(part in rel for part in (".venv", "__pycache__", "/test_", "tests/")):
        continue
    if rel in EXEMPT:
        continue
    src = path.read_text(encoding="utf-8", errors="replace")
    if CONSTRUCTS_LIVE.search(src) and HAS_MAIN.search(src):
        runnable.append(rel)
        if not REFRESHES.search(src):
            missing.append(rel)

check("the sweep actually found runnable live entry points to check",
      len(runnable) >= 3, runnable)

# 26 of these had no sync, and editing 26 files would have left the 27th broken.
# The fix went into the three API CLIENT constructors instead — the one place every
# entry point passes through — so this now asserts the property holds, by whatever
# route, rather than that each file remembered to do it.
CLIENTS = ["etsy/api/private/api.py", "etsy/api/public/api.py",
           "pinterest/endpoints/api.py"]
for client in CLIENTS:
    src = (ROOT / client).read_text(encoding="utf-8", errors="replace")
    check(f"{client.split('/')[-2]}/{client.split('/')[-1]} syncs the mirror on construction",
          "sync_if_stale" in src,
          f"{client} builds sessions without refreshing the mirror — every entry "
          f"point that uses it inherits a possibly-stale pool")

check("so a runnable entry point without its own sync is still covered",
      not missing or all((ROOT / c).read_text(encoding="utf-8",
                                              errors="replace").count("sync_if_stale")
                         for c in CLIENTS),
      f"uncovered: {missing}")

# The throttle matters: a client built in a loop must not re-sync every time.
from core import vault_mirror as _vm  # noqa: E402
check("the sync is throttled, not per-construction",
      _vm.MAX_MIRROR_AGE >= 60, _vm.MAX_MIRROR_AGE)
check("and the throttle window is shorter than the 300s eviction line",
      _vm.MAX_MIRROR_AGE < 300, _vm.MAX_MIRROR_AGE)
# If the window met or exceeded 300s the mirror could still age past eviction
# between syncs, which is the whole failure this is meant to close.

# And the guard that makes the above meaningful: require() must actually sync.
src = (ROOT / "core" / "preflight.py").read_text(encoding="utf-8")
check("preflight.require refreshes from the shared vault before judging",
      "from core.vault_mirror import sync" in src and "sync()" in src)
check("and treats a mirror failure as non-fatal, not as an empty pool",
      "Continuing with the copy we already hold" in src)
# A mirror that cannot be reached is not the same as having no session — we may
# already hold a good copy, so the real check decides.

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
