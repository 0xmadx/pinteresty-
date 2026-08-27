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

# --- no live client or entry point references the retired mirror -----------------
# core/vault_mirror.py (D-33) was removed once pinterest-apify moved to its own
# Redis and there was nothing left to mirror from (D-49). This is the one guard
# worth keeping from that era: a stray `sync_if_stale()`/`vault_mirror import`
# reappearing anywhere would be dead code pointing at a module that no longer
# exists, and would raise ModuleNotFoundError the first time that path executed.
import re  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# Matches real import/call syntax only — not a prose mention like "core/vault_mirror.py
# (D-33)" in a historical comment, which several files keep on purpose.
STALE_REF = re.compile(r"vault_mirror\s+import|import\s+vault_mirror"
                       r"|sync_if_stale\s*\(|_sync_mirror\s*\(")
offenders = []
for path in ROOT.rglob("*.py"):
    rel = path.relative_to(ROOT).as_posix()
    if any(part in rel for part in (".venv", "__pycache__")) or rel == "core/test_preflight.py":
        continue
    src = path.read_text(encoding="utf-8", errors="replace")
    if STALE_REF.search(src):
        offenders.append(rel)

check("no module still imports or calls the retired vault_mirror", not offenders, offenders)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
