"""Per-term series store — the thing that turns requests into local lookups.

The reason this exists: `/related_terms/` and `/prefix_match/` already hand back a full
weekly series for every term they suggest, and the crawler was throwing it away and then
paying a `/metrics/` call to fetch the same numbers back. Measured on the existing cache:
114 terms had a free series sitting in related/prefix responses, and 22 of the 32 terms we
had spent `/metrics/` calls on were among them.

Provenance, measured against `/metrics/?days=365` on the same terms:

    related_terms   53 points, byte-identical to /metrics/       -> exact
    metrics         53 points, the reference                     -> exact
    prefix_match    52 points, == metrics[1:] renormalized to
                    its own 52-week peak; off by <=2 on a
                    0-100 scale when the dropped week was the
                    peak                                         -> approx

Slicing a long window down to a short one is renormalization, not truncation: the API
scales each window to its own peak. Verified on 14 terms x {30,90,180} days — 13 of 14
reproduce exactly. The one that misses is a term whose recent weeks round to 0 inside the
365-day series, so the precision was destroyed by the *source* rounding before we ever
sliced. `get()` refuses to serve those rather than return quietly-wrong numbers.
"""
import json
import math
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "series.db"

# related is verified byte-identical to metrics, so it ranks equal.
RANK = {"metrics": 3, "related": 3, "prefix": 1}

# A sliced window whose raw peak is below this lost too much to source rounding to be
# trustworthy. Below it we make the caller fetch instead of guessing.
MIN_SLICE_PEAK = 25


def window_points(days):
    """Weekly buckets the API returns for a `days` window. Verified: 30->5, 90->13,
    180->26, 365->53, 730->105."""
    return math.ceil(days / 7)


def slice_window(counts, days):
    """Take the last N weeks and renormalize to that window's own peak.

    Truncating alone is wrong — the API scales every window to 100 at its own maximum, so
    a naive tail of a 365-day series is off by the ratio between the two peaks.
    """
    need = window_points(days)
    if need >= len(counts):
        return list(counts)
    tail = counts[-need:]
    peak = max(tail)
    if not peak:
        return tail
    return [round(x * 100 / peak) for x in tail]


class SeriesStore:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS series (
                    term TEXT, country TEXT, end_date TEXT,
                    source TEXT, points TEXT, n INTEGER, growth_json TEXT,
                    PRIMARY KEY (term, country, end_date)
                )
            """)
            conn.commit()

    # -- writes ------------------------------------------------------------------------
    def put(self, term, counts, source, country="US", end_date=None, growth=None):
        """Insert, but never downgrade: an approximate prefix series must not overwrite an
        exact one, and a shorter series must not overwrite a longer one."""
        if not term or not counts:
            return False
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "SELECT source, n FROM series WHERE term=? AND country=? AND end_date=?",
                (term, country, end_date))
            row = cur.fetchone()
            if row:
                old_source, old_n = row
                if (RANK.get(old_source, 0), old_n) >= (RANK.get(source, 0), len(counts)):
                    return False
            conn.execute("""
                INSERT OR REPLACE INTO series (term, country, end_date, source, points, n, growth_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (term, country, end_date, source, json.dumps(counts), len(counts),
                  json.dumps(growth) if growth else None))
            conn.commit()
        return True

    def harvest(self, rows, source, country="US", end_date=None):
        """Absorb a /related_terms/ or /prefix_match/ response. These carry `counts[]` per
        suggested term — a free series for terms nothing has asked about yet."""
        n = 0
        for r in rows or []:
            if isinstance(r, dict) and r.get("term") and r.get("counts"):
                n += self.put(r["term"], r["counts"], source, country, end_date)
        return n

    def harvest_metrics(self, series, country="US", end_date=None):
        """Absorb a /metrics/ response, keeping growth_rates — those are not reliably
        recomputable from the rounded counts, so they are worth storing rather than
        re-deriving."""
        n = 0
        for s in series or []:
            counts = [p.get("count") for p in s.get("counts", [])]
            if s.get("term") and counts:
                n += self.put(s["term"], counts, "metrics", country, end_date,
                              growth=s.get("growth_rates"))
        return n

    # -- reads -------------------------------------------------------------------------
    def get(self, term, days=None, country="US", end_date=None, exact_only=False):
        """Return `{counts, source, precision, growth}` or None if the store cannot serve
        this faithfully. None means "go fetch it", never "no data".
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT source, points, n, growth_json FROM series "
                "WHERE term=? AND country=? AND end_date=?",
                (term, country, end_date)).fetchone()
        if not row:
            return None
        source, points, n, growth_json = row
        counts = json.loads(points)
        growth = json.loads(growth_json) if growth_json else None
        precision = "exact" if RANK.get(source, 0) == 3 else "approx"

        if days is not None:
            need = window_points(days)
            if need > n:
                return None                      # stored window too short
            if need < n:
                tail = counts[-need:]
                if max(tail) < MIN_SLICE_PEAK:
                    return None                  # source rounding already destroyed it
                counts = slice_window(counts, days)
                precision = "approx"
        if exact_only and precision != "exact":
            return None
        return {"counts": counts, "source": source, "precision": precision, "growth": growth}

    def split(self, terms, days=None, country="US", end_date=None, exact_only=False):
        """(served_locally, must_fetch) for a batch — the call the crawler actually makes."""
        hits, misses = {}, []
        for t in terms:
            got = self.get(t, days, country, end_date, exact_only)
            (hits.__setitem__(t, got) if got else misses.append(t))
        return hits, misses

    def stats(self):
        with sqlite3.connect(self.db_path) as conn:
            return {
                "terms": conn.execute("SELECT COUNT(*) FROM series").fetchone()[0],
                "by_source": dict(conn.execute(
                    "SELECT source, COUNT(*) FROM series GROUP BY 1")),
            }
