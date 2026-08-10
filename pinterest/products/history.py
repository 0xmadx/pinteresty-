"""5. The historical archive Pinterest does not offer.

Pinterest Trends has no export, no bulk endpoint and no way to ask "what did the growing
table look like in March". But `endDate` back-dates cleanly: pass any past week and the
whole discovery table replays as it stood, ranks and all. Fifty-two calls per preset
reconstruct a year that the product itself cannot show you, and once written down it is
ours — the cache means it is fetched exactly once, ever.

What gets stored is the RANK-AND-ROW, not the curve. The series store already holds curves;
what has no other home is "this term was #7 on the growing table in the week ending
2026-03-02, at seasonality 0.91". That row is what makes `rank_history()` and the alerting
in `alerts.py` possible, and it is the one thing a re-fetch can never recover once the
week ages out.

    .venv/Scripts/python.exe pinterest/products/history.py --weeks 8
    .venv/Scripts/python.exe pinterest/products/history.py --term "cute august nails"
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import clamp_change

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "history.db"


def week_before(end_date, weeks):
    """Pinterest's weeks are Monday-anchored and endDate must land on one of them, so this
    steps in whole weeks from a known-good date rather than doing calendar arithmetic."""
    return (datetime.strptime(end_date, "%Y-%m-%d")
            - timedelta(weeks=weeks)).strftime("%Y-%m-%d")


class HistoryDB:
    def __init__(self, db_path=DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    week TEXT, country TEXT, preset TEXT, interest TEXT,
                    rank INTEGER, term TEXT,
                    search_count INTEGER, seasonality REAL,
                    mom REAL, yoy REAL, wow REAL, mom_rank INTEGER,
                    PRIMARY KEY (week, country, preset, interest, term)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS ix_term ON snapshots(term)")
            conn.commit()

    def write(self, week, country, preset, rows, interest=""):
        """One discovery table -> rows. INSERT OR REPLACE: re-running a week is idempotent,
        which matters because the cache makes re-running free and therefore likely."""
        payload = [
            (week, country, preset, interest, i, r["term"],
             r.get("searchCount"), r.get("seasonality_score"),
             clamp_change((r.get("mom_change") or {}).get("value")),
             clamp_change((r.get("yoy_change") or {}).get("value")),
             clamp_change((r.get("wow_change") or {}).get("value")),
             (r.get("mom_change") or {}).get("index"))
            for i, r in enumerate(rows)
        ]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                             payload)
            conn.commit()
        return len(payload)

    def weeks(self, country="US", preset=None):
        q = "SELECT DISTINCT week FROM snapshots WHERE country=?"
        args = [country]
        if preset:
            q, args = q + " AND preset=?", args + [preset]
        with sqlite3.connect(self.db_path) as conn:
            return sorted(w for (w,) in conn.execute(q + " ORDER BY week", args))

    def table(self, week, country="US", preset="growing", interest=""):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM snapshots WHERE week=? AND country=? AND preset=? "
                "AND interest=? ORDER BY rank", (week, country, preset, interest))]

    def rank_history(self, term, country="US", preset="growing"):
        """Where a term sat, week by week. This is the series Pinterest cannot give you —
        its own /metrics/ returns search volume, never rank."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT week, rank, search_count, seasonality, mom, yoy FROM snapshots "
                "WHERE term=? AND country=? AND preset=? ORDER BY week",
                (term, country, preset))]

    def longevity(self, country="US", preset="growing", min_weeks=2):
        """Terms by how many distinct weeks they held a place on the table.

        Separates a genuine trend from a one-week spike, which is exactly the distinction a
        single snapshot cannot make and the reason to keep an archive at all.
        """
        with sqlite3.connect(self.db_path) as conn:
            return [{"term": t, "weeks": n, "best_rank": best, "first": first, "last": last}
                    for t, n, best, first, last in conn.execute(
                        "SELECT term, COUNT(DISTINCT week), MIN(rank), MIN(week), MAX(week) "
                        "FROM snapshots WHERE country=? AND preset=? GROUP BY term "
                        "HAVING COUNT(DISTINCT week) >= ? ORDER BY 2 DESC, 3 ASC",
                        (country, preset, min_weeks))]

    def stats(self):
        with sqlite3.connect(self.db_path) as conn:
            return {
                "rows": conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
                "weeks": conn.execute("SELECT COUNT(DISTINCT week) FROM snapshots").fetchone()[0],
                "terms": conn.execute("SELECT COUNT(DISTINCT term) FROM snapshots").fetchone()[0],
            }


def backfill(api, weeks=8, country="US", presets=("growing", "seasonal"), db=None,
             limit=None):
    """Walk `endDate` backwards and archive each week. One request per week per preset.

    Ordered newest-first so an interrupted run still leaves the recent weeks — those are
    the ones alerting needs, and the deep past is a nice-to-have.

    `limit` defaults to None (the server's 50) rather than the 100 the server would allow.
    An archive is only useful if its weeks are comparable, and mixing 50-row and 100-row
    weeks would make `entered`/`exited` fire on the boundary rather than on real movement.
    Pass limit=100 to start a deeper archive — but then re-run every week at 100.
    """
    db = db or HistoryDB()
    latest = api.latest_available_date()
    written = {}
    for k in range(weeks):
        week = week_before(latest, k)
        for preset in presets:
            table = api.top_trends(preset, country=country, end_date=week, limit=limit)
            rows = (table or {}).get("values") or []
            if not rows:
                print(f"  {week} {preset}: empty (endDate may predate coverage)")
                continue
            # Trust the response's own endDate over the one we asked for: the server snaps
            # to its nearest complete week and will silently hand back a different one.
            actual = (table or {}).get("endDate") or week
            written[(actual, preset)] = db.write(actual, country, preset, rows)
            print(f"  {actual} {preset:9} {written[(actual, preset)]:>3} rows")
    return db, written


def report(weeks=8, country="US", term=None):
    db = HistoryDB()
    if term:
        hist = db.rank_history(term, country)
        if not hist:
            print(f"No archived rows for {term!r} — run --weeks first.")
            return
        print(f"=== {term} ===")
        for h in hist:
            print(f"  {h['week']}  rank {h['rank']:>2}  count {h['search_count']:>6}  "
                  f"seasonality {h['seasonality'] or 0:.3f}")
        return hist

    with PinterestTrendsAPI() as api:
        print(f"Archiving {weeks} weeks back from {api.latest_available_date()}\n")
        db, _ = backfill(api, weeks, country, db=db)
    print(f"\nArchive: {db.stats()}")
    print("\n=== terms that held the growing table longest ===")
    for row in db.longevity(country)[:12]:
        print(f"  {row['weeks']:>2} weeks  best rank {row['best_rank']:>2}  "
              f"{row['first']}..{row['last']}  {row['term']}")
    return db


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--term" in args:
        report(term=args[args.index("--term") + 1])
    else:
        n = int(args[args.index("--weeks") + 1]) if "--weeks" in args else 8
        report(weeks=n)
