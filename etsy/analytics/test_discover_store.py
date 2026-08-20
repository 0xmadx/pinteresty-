"""The discovered-candidate pool: append-only, and deduped to a ranked list on read.

A term can be discovered from two different seeds in one run, and across runs. The
store keeps every row (append-only, like every observation table here), but
`latest_discovered` must return the pool of ONE run, deduped so the strongest
sighting of each term wins — otherwise the Discover screen shows a cross-join
instead of a ranked list.

    .venv/Scripts/python.exe -m etsy.analytics.test_discover_store
"""
import os
import tempfile

from core.database import MarketDatabase

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    tmp = tempfile.mkdtemp()
    db = MarketDatabase(db_path=os.path.join(tmp, "d.db"))

    # --- empty pool -------------------------------------------------------------------
    print()
    check("nothing discovered yet returns an empty list, not an error",
          db.latest_discovered() == [])

    # --- one run, ranked by winnability ------------------------------------------------
    print()
    run1 = "2026-08-20T00:00:00+00:00"
    db.record_discovered("wall a", seed="s1", demand_per_listing=0.01,
                         verdict="wall", collected_at=run1)
    db.record_discovered("winner", seed="s1", demand_per_listing=1.74,
                         verdict="winnable", collected_at=run1)
    db.record_discovered("contested x", seed="s2", demand_per_listing=0.4,
                         verdict="contested", collected_at=run1)
    pool = db.latest_discovered()
    check("the pool is ranked by demand per listing, best first",
          [r["term"] for r in pool] == ["winner", "contested x", "wall a"],
          [r["term"] for r in pool])

    # --- a term found under two seeds keeps the STRONGER sighting -----------------------
    print()
    db.record_discovered("both", seed="s1", demand_per_listing=0.3,
                         verdict="contested", collected_at=run1)
    db.record_discovered("both", seed="s2", demand_per_listing=0.9,
                         verdict="contested", collected_at=run1)
    pool = db.latest_discovered()
    both = [r for r in pool if r["term"] == "both"]
    check("a term discovered from two seeds appears ONCE, not twice",
          len(both) == 1, both)
    check("and it keeps the higher demand-per-listing sighting",
          both[0]["demand_per_listing"] == 0.9, both[0])
    check("with the seed that produced it", both[0]["seed"] == "s2", both[0])

    # --- a later run replaces the pool, without deleting the old rows -------------------
    print()
    run2 = "2026-08-27T00:00:00+00:00"
    db.record_discovered("fresh", seed="s1", demand_per_listing=2.0,
                         verdict="winnable", collected_at=run2)
    pool = db.latest_discovered()
    check("the latest pool is only the newest run",
          [r["term"] for r in pool] == ["fresh"], [r["term"] for r in pool])
    # The old rows still exist — append-only, time is first-class.
    with db.get_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM discovered_candidates").fetchone()[0]
    check("but the earlier run's rows are NOT deleted (append-only)",
          total == 6, total)   # run1: wall a, winner, contested x, both/s1, both/s2 + run2: fresh

    # --- absent is not zero -------------------------------------------------------------
    print()
    db2 = MarketDatabase(db_path=os.path.join(tmp, "e.db"))
    db2.record_discovered("unsized", seed="s", demand_per_listing=None,
                         verdict="unmeasured", collected_at=run1)
    db2.record_discovered("sized", seed="s", demand_per_listing=0.5,
                         verdict="contested", collected_at=run1)
    pool = db2.latest_discovered()
    check("an unsized term sorts LAST, not first as a zero would",
          pool[-1]["term"] == "unsized", [r["term"] for r in pool])
    check("and it survives in the pool rather than being dropped",
          len(pool) == 2, pool)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
