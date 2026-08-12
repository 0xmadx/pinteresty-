"""Offline tests for the keyed request cache. No network; a temp SQLite file.

The cache answers one question — "did I already fetch THIS, recently enough to trust it?"
— and must answer it three ways that the old hand-rolled file caches got wrong:

  1. same key within TTL -> return the saved copy, never call the network (dedup);
  2. same key past TTL   -> the bet expired, fetch once, re-stamp (this is what the
                            dateless Pinterest keys, T-3, never did — they were forever);
  3. a FAILED fetch is not cached, so a transient error does not get frozen in.

Run:  python -m core.test_request_cache
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

from core.request_cache import RequestCache

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


class Clock:
    """A hand-cranked clock so TTL expiry is tested deterministically, not with sleeps."""
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t = self.t + timedelta(**kw)


class Counter:
    """Counts how many times the real fetch actually ran."""
    def __init__(self, value):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.value


def main():
    tmp = tempfile.mkdtemp()
    clock = Clock(datetime(2026, 8, 11, tzinfo=timezone.utc))
    cache = RequestCache(db_path=os.path.join(tmp, "cache.db"), clock=clock)

    # --- 1. miss then hit within TTL -------------------------------------------------------
    fetch = Counter({"tags": ["gift", "necklace"]})
    a = cache.get_or_fetch("listing:123", ttl_seconds=3600, fetch_fn=fetch)
    b = cache.get_or_fetch("listing:123", ttl_seconds=3600, fetch_fn=fetch)
    check("first call fetches", a == {"tags": ["gift", "necklace"]} and fetch.calls == 1)
    check("second call within TTL returns the SAME data without fetching",
          b == a and fetch.calls == 1, f"calls={fetch.calls}")

    # --- 2. past TTL, the bet expires and it re-fetches ------------------------------------
    print()
    clock.advance(hours=2)   # now older than the 3600s TTL
    fetch2 = Counter({"tags": ["gift", "necklace", "silver"]})
    c = cache.get_or_fetch("listing:123", ttl_seconds=3600, fetch_fn=fetch2)
    check("a stale entry re-fetches", fetch2.calls == 1 and "silver" in c["tags"])
    check("and the refreshed copy replaces the old one",
          cache.get_or_fetch("listing:123", 3600, Counter({"x": 1}))["tags"][-1] == "silver")

    # --- 3. a failed fetch is not cached ---------------------------------------------------
    print()
    fail = Counter(None)              # None = the fetch failed
    r = cache.get_or_fetch("listing:999", ttl_seconds=3600, fetch_fn=fail)
    check("a failed fetch returns None", r is None)
    retry = Counter({"tags": ["ok"]})
    r2 = cache.get_or_fetch("listing:999", ttl_seconds=3600, fetch_fn=retry)
    check("and is NOT cached — the next call retries instead of serving the failure",
          retry.calls == 1 and r2 == {"tags": ["ok"]})

    # --- TTL=0 means live: never cache, always fetch ---------------------------------------
    print()
    live = Counter({"in_stock": 17})
    cache.get_or_fetch("stock:1", ttl_seconds=0, fetch_fn=live)
    cache.get_or_fetch("stock:1", ttl_seconds=0, fetch_fn=live)
    check("TTL=0 fetches every time — live data is never served from cache",
          live.calls == 2, f"calls={live.calls}")
    check("and nothing is stored for it", cache.get_entry("stock:1") is None)

    # --- TTL=None means forever ------------------------------------------------------------
    print()
    forever = Counter({"immutable": True})
    cache.get_or_fetch("const:1", ttl_seconds=None, fetch_fn=forever)
    clock.advance(days=400)
    cache.get_or_fetch("const:1", ttl_seconds=None, fetch_fn=forever)
    check("TTL=None never expires, even 400 days later", forever.calls == 1)

    # --- keys are independent --------------------------------------------------------------
    print()
    f1, f2 = Counter({"a": 1}), Counter({"b": 2})
    check("different keys do not collide",
          cache.get_or_fetch("k1", 3600, f1) != cache.get_or_fetch("k2", 3600, f2))

    # --- get_entry exposes the age, for freshness_floor -----------------------------------
    print()
    clock.t = datetime(2026, 8, 11, tzinfo=timezone.utc)
    cache.get_or_fetch("aged:1", ttl_seconds=None, fetch_fn=Counter({"v": 1}))
    clock.advance(days=3)
    entry = cache.get_entry("aged:1")
    check("get_entry returns payload, fetched_at and age regardless of TTL",
          entry.payload == {"v": 1} and entry.age_seconds == 3 * 86400,
          f"got {entry}")
    check("get_entry on a missing key is None", cache.get_entry("nope") is None)

    # --- invalidation (the manual flush T-3 needs) ----------------------------------------
    print()
    cache.get_or_fetch("related:us:nails", None, Counter({"s": 1}))
    cache.get_or_fetch("related:us:bows", None, Counter({"s": 2}))
    cache.get_or_fetch("metrics:us:nails", None, Counter({"s": 3}))
    removed = cache.invalidate_prefix("related:")
    check("invalidate_prefix clears a whole family of keys", removed == 2, f"got {removed}")
    check("and leaves other families intact", cache.get_entry("metrics:us:nails") is not None)

    # Underscores are LIKE wildcards — a prefix flush must treat them literally, or
    # invalidate_prefix("public_search_") would also nuke "publicXsearchX..." keys.
    cache.get_or_fetch("public_search_mom", None, Counter({"s": 1}))
    cache.get_or_fetch("publicXsearchXmom", None, Counter({"s": 2}))
    removed = cache.invalidate_prefix("public_search_")
    check("invalidate_prefix treats '_' literally, not as a wildcard",
          removed == 1 and cache.get_entry("publicXsearchXmom") is not None,
          f"removed {removed}")
    check("invalidate removes one key", cache.invalidate("metrics:us:nails") == 1
          and cache.get_entry("metrics:us:nails") is None)

    # --- a corrupt stored row is a miss, not a crash --------------------------------------
    print()
    import sqlite3
    with sqlite3.connect(cache.db_path) as conn:
        conn.execute("INSERT OR REPLACE INTO request_cache (key, payload, fetched_at, source)"
                     " VALUES ('bad', '{not json', ?, NULL)", (clock().isoformat(),))
        conn.commit()
    refetch = Counter({"clean": 1})
    check("an unparseable cached payload is treated as a miss and re-fetched",
          cache.get_or_fetch("bad", 3600, refetch) == {"clean": 1} and refetch.calls == 1)

    # --- split get/put (the Pinterest _cached/_store pattern) ---------------------------------
    print()
    clock.t = datetime(2026, 8, 11, tzinfo=timezone.utc)
    check("get on a missing key is None", cache.get("split:1", 3600) is None)
    cache.put("split:1", {"v": 1}, source="pin")
    check("after put, get within TTL returns it", cache.get("split:1", 3600) == {"v": 1})
    clock.advance(hours=2)
    check("get past TTL is None even though the row exists",
          cache.get("split:1", 3600) is None
          and cache.get_entry("split:1") is not None)
    check("put returns its data for return-chaining", cache.put("split:2", {"w": 2}) == {"w": 2})
    check("put(None) stores nothing", cache.put("split:3", None) is None
          and cache.get_entry("split:3") is None)

    # --- stats --------------------------------------------------------------------------------
    print()
    s = cache.stats()
    check("stats reports how many entries are cached", s["entries"] >= 3, f"got {s}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
