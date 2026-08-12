"""
request_cache.py

Layer: core/ (I/O — a SQLite-backed key/value cache with TTL)
Purpose: one place that answers "did I already fetch THIS, recently enough to
         trust it?" — replacing five hand-rolled file caches that each had their
         own key scheme and NO expiry.

Key decision — the cache and the store are different concerns and must not share a
table. This cache exists to FORGET: a stale entry is replaced, because its only job
is to avoid paying for the same request twice within a window you decided is safe.
The observation tables (market_intelligence.db, graph.db) exist to REMEMBER: they
keep every reading with its collected_at, forever. Putting cache rows in the store
would corrupt history; putting history in the cache would lose it. So this gets its
own file.

Why SQLite and not Redis: this is a single-operator, single-machine, weekly-batch
system. Redis solves cache coordination across many concurrent processes — a
problem that does not exist here. A SQLite table is the right tier; see
06_stack_and_deps.md on scale discipline. Revisit only at multi-tenant scale
(blueprint 07_saas_evolution).

TTL is a BET, not knowledge. The cache cannot know whether the listing changed on
Etsy — the only way to find out is to fetch it, which is the thing being avoided.
So each data type gets a TTL matched to how fast it really moves, and anything that
must be live is given TTL_LIVE (0) so it is never served from cache. The more a
value moves, the shorter its TTL.

Two refusals carried over from the rest of this codebase:
  - a FAILED fetch (fetch_fn returns None) is never stored, so a transient error is
    not frozen into the cache — the same not-found-vs-not-checked distinction the
    rank tracker and the review parser had to make;
  - TTL=0 is not the same as TTL=None: 0 means "never cache" (live), None means
    "never expires" (immutable). Collapsing them is how live data gets stuck.
"""
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from core import runlog

DEFAULT_DB = os.path.join("etsy", "data", "cache", "request_cache.db")

# The bets. Named so a caller states intent ("this is trend data") rather than a bare
# number, and so every TTL in the system is tuned in one place.
DAY = 86400
TTL_LIVE = 0                 # stock, "N in cart", today's badge — never cache
TTL_SERP = 1 * DAY           # rankings shift, but not hour to hour
TTL_TREND_SERIES = 7 * DAY   # a WEEKLY number; re-fetching daily buys nothing (fixes T-3)
TTL_LISTING_TAGS = 30 * DAY  # sellers rarely re-tag
TTL_METERED = 30 * DAY       # private-API data: expensive, moves slowly
TTL_TAXONOMY = 30 * DAY      # category trees, demographics splits — structural, slow
TTL_FOREVER = None           # genuinely immutable (a taxonomy id map, say)


@dataclass(frozen=True)
class CacheEntry:
    key: str
    payload: object
    fetched_at: str          # ISO UTC — the age this value carries (B-10)
    age_seconds: int
    source: str = None


class RequestCache:
    def __init__(self, db_path=DEFAULT_DB, clock=None):
        # clock is injectable so TTL expiry is testable without sleeping.
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS request_cache (
                    key        TEXT PRIMARY KEY,
                    payload    TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    source     TEXT
                )
            """)
            conn.commit()

    def _now(self):
        t = self._clock()
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)

    def get_or_fetch(self, key, ttl_seconds, fetch_fn, source=None):
        """Return the cached payload if fresh, else call fetch_fn and cache the result.

        This is the whole point of the module: same key + within TTL = no network.
        Increments the runlog cache_hits/cache_misses counters (a no-op outside a
        stage), so the health report's budget numbers finally reflect reality.
        """
        entry = self._live_entry(key, ttl_seconds)
        if entry is not None:
            runlog.count(cache_hits=1)
            return entry.payload

        runlog.count(cache_misses=1)
        data = fetch_fn()
        # A failed fetch is not cached — freezing a transient error would serve it as
        # truth until the TTL expired. TTL_LIVE (0) is never stored either.
        if data is not None and ttl_seconds != 0:
            self._store(key, data, source)
        return data

    def get(self, key, ttl_seconds):
        """TTL-respecting read: the payload if fresh, else None. For callers that keep
        the fetch separate (get-then-maybe-store), like the Pinterest client's split
        `_cached`/`_store` pattern. Counts hits/misses the same as get_or_fetch."""
        entry = self._live_entry(key, ttl_seconds)
        if entry is not None:
            runlog.count(cache_hits=1)
            return entry.payload
        runlog.count(cache_misses=1)
        return None

    def put(self, key, data, source=None):
        """Store a fetched value. None is not stored (a failed fetch is not cached).
        Returns data unchanged so callers can `return cache.put(key, fetch())`."""
        if data is not None:
            self._store(key, data, source)
        return data

    def _live_entry(self, key, ttl_seconds):
        """The entry for key IF it exists and is within ttl_seconds, else None."""
        if ttl_seconds == 0:
            return None   # live data is never a hit
        entry = self.get_entry(key)
        if entry is None:
            return None
        if ttl_seconds is not None and entry.age_seconds > ttl_seconds:
            return None   # stale: the bet expired
        return entry

    def get_entry(self, key):
        """The raw entry for key regardless of TTL, or None. Carries fetched_at + age,
        so a caller can feed the age into freshness_floor (B-10)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT payload, fetched_at, source FROM request_cache WHERE key = ?",
                (key,)).fetchone()
        if not row:
            return None
        try:
            payload = json.loads(row[0])
        except (ValueError, TypeError):
            # A corrupt row is a miss, not a crash — treat it as absent so the caller
            # re-fetches and overwrites it.
            return None
        fetched = datetime.fromisoformat(row[1])
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        age = int((self._now() - fetched).total_seconds())
        return CacheEntry(key=key, payload=payload, fetched_at=row[1],
                          age_seconds=age, source=row[2])

    def _store(self, key, data, source):
        # INSERT OR REPLACE is correct HERE (unlike the observation tables): a cache
        # keeps only the latest copy on purpose. History lives in the store.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO request_cache (key, payload, fetched_at, source) "
                "VALUES (?, ?, ?, ?)",
                (key, json.dumps(data), self._now().isoformat(), source))
            conn.commit()

    def invalidate(self, key):
        """Drop one key. Returns how many rows were removed."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM request_cache WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount

    def invalidate_prefix(self, prefix):
        """Drop every key starting with `prefix` — the manual flush T-3 needs when a
        key scheme changes. Returns how many rows were removed.

        Real keys contain '_' and '%' is possible too, and both are LIKE metacharacters
        ('_' matches any single char). They are escaped and the escape char declared, or
        `invalidate_prefix("public_search_")` would also match "publicXsearchX...".
        """
        pattern = prefix.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM request_cache WHERE key LIKE ? ESCAPE '\\'", (pattern,))
            conn.commit()
            return cur.rowcount

    def stats(self):
        with sqlite3.connect(self.db_path) as conn:
            entries = conn.execute("SELECT COUNT(*) FROM request_cache").fetchone()[0]
            by_source = dict(conn.execute(
                "SELECT COALESCE(source,'unknown'), COUNT(*) FROM request_cache GROUP BY 1"))
        return {"entries": entries, "by_source": by_source}
