"""Offline tests for the LEARN loop (M-3). No network; a temp database.

The two things that must not break:

  1. **Unranked is not unchecked.** A listing that is absent from the SERP is recorded
     with rank=None; a listing whose search failed is not recorded at all. Conflating
     them would make a model look right (or wrong) for reasons nobody measured.
  2. **Organic and absolute rank are different numbers.** A listing can slide in
     absolute rank while holding organic rank because a competitor started running ads.

Run:  python -m etsy.analytics.test_rank_tracker
"""
import os
import sys
import tempfile

from core.graph_db import GraphDB
from etsy.analytics.rank_tracker import find_rank, track_ranks

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def serp(card_ids, organic_ids, total=5000, ads=()):
    return {
        "total_results": total,
        "organic_listing_ids": organic_ids,
        "cards": [{"listing_id": str(i), "is_ad": str(i) in {str(a) for a in ads}}
                  for i in card_ids],
    }


class FakeAPI:
    """Stands in for EtsyPublicAPI. Returns canned SERPs; None means the search failed."""

    def __init__(self, by_query):
        self.by_query = by_query
        self.calls = []

    def get_public_search(self, query, filters=None):
        self.calls.append(query)
        return self.by_query.get(query)


def main():
    # --- find_rank: the position arithmetic -------------------------------------------
    r = find_rank(serp(["111", "222", "333"], ["111", "222", "333"]), "222")
    check("a listing is found at its 1-indexed position", r["absolute_rank"] == 2,
          f"got {r['absolute_rank']}")
    check("organic rank matches when there are no ads", r["organic_rank"] == 2)
    check("found is True", r["found"] is True)
    check("competitor count comes from total_results", r["competitor_count"] == 5000)

    # Two ads at the top: absolute 4, organic 2. This is the case that makes recording
    # only one number misleading.
    r = find_rank(serp(["ad1", "ad2", "111", "222"], ["111", "222"], ads=["ad1", "ad2"]),
                  "222")
    check("absolute rank counts ads", r["absolute_rank"] == 4, f"got {r['absolute_rank']}")
    check("organic rank excludes them", r["organic_rank"] == 2, f"got {r['organic_rank']}")
    check("the two are genuinely different here",
          r["absolute_rank"] != r["organic_rank"])

    r = find_rank(serp(["ad1", "222"], [], ads=["ad1"]), "ad1")
    check("a listing appearing as an ad is flagged", r["is_ad"] is True)

    # --- absence -----------------------------------------------------------------------
    print()
    r = find_rank(serp(["111", "222"], ["111", "222"]), "999")
    check("a listing not in the SERP has rank None", r["rank"] is None)
    check("and found is False", r["found"] is False)
    check("but the competitor count is still measured", r["competitor_count"] == 5000)

    check("an empty SERP does not crash", find_rank({}, "1")["rank"] is None)
    check("a None SERP does not crash", find_rank(None, "1")["rank"] is None)

    # --- ids compare as strings, not by type -------------------------------------------
    print()
    r = find_rank(serp([111, 222], [111, 222]), 222)
    check("integer ids match string ids", r["absolute_rank"] == 2, f"got {r}")

    # --- end to end against a real (temp) database ---------------------------------------
    print()
    tmp = tempfile.mkdtemp()
    db = GraphDB(db_path=os.path.join(tmp, "graph.db"))

    db.record_launch("111", "mom necklace", predicted_score=0.82,
                     predicted_profit=140.0, product_type="physical")
    db.record_launch("999", "dad mug", predicted_score=0.41)
    db.record_launch("777", "broken search", predicted_score=0.5)

    api = FakeAPI({
        "mom necklace": serp(["ad1", "111", "222"], ["111", "222"], ads=["ad1"]),
        "dad mug": serp(["555", "666"], ["555", "666"]),   # 999 is absent
        "broken search": None,                              # the search itself failed
    })

    results = track_ranks(db=db, public_api=api)
    check("every launch is attempted", len(api.calls) == 3, f"got {api.calls}")
    check("only the searches that succeeded produce results", len(results) == 2,
          f"got {len(results)}")

    ranked = db.get_rank_history("111")
    check("a found listing records its organic rank",
          len(ranked) == 1 and ranked[0]["rank"] == 1, f"got {ranked}")
    check("AND its absolute rank — both, per MIGRATION_AND_OPERATIONS.md:111",
          ranked[0]["absolute_rank"] == 2, f"got {ranked[0]['absolute_rank']}")
    check("the two are stored distinctly, so an ad above it is not read as a demotion",
          ranked[0]["rank"] != ranked[0]["absolute_rank"])
    check("the competitor count is stored alongside it",
          ranked[0]["competitor_count"] == 5000)

    absent = db.get_rank_history("999")
    check("a listing checked and NOT found records rank=None — a measurement",
          len(absent) == 1 and absent[0]["rank"] is None, f"got {absent}")
    check("its absolute rank is None too, not 0",
          absent[0]["absolute_rank"] is None, f"got {absent[0]['absolute_rank']}")
    check("but the row still records how many competitors were counted",
          absent[0]["competitor_count"] == 5000)

    unchecked = db.get_rank_history("777")
    check("a listing whose search FAILED records nothing — unchecked, not unranked",
          unchecked == [], f"got {unchecked}")

    # --- the distinction survives into the join ------------------------------------------
    print()
    rows = {r["listing_id"]: r for r in db.prediction_vs_outcome()}
    check("prediction_vs_outcome covers every launch", len(rows) == 3, f"got {len(rows)}")
    check("a ranked listing shows its rank and its prediction",
          rows["111"]["latest_rank"] == 1 and rows["111"]["predicted_score"] == 0.82)
    check("an unranked listing is distinguishable: observed but rank None",
          rows["999"]["observations"] == 1 and rows["999"]["latest_rank"] is None)
    check("an unchecked listing is distinguishable: zero observations",
          rows["777"]["observations"] == 0 and rows["777"]["latest_rank"] is None)

    # --- append-only over time -------------------------------------------------------------
    print()
    db.record_rank("111", "mom necklace", rank=4, observed_at="2026-08-12T00:00:00+00:00")
    db.record_rank("111", "mom necklace", rank=7, observed_at="2026-08-19T00:00:00+00:00")
    hist = db.get_rank_history("111")
    check("later observations append rather than overwrite", len(hist) == 3,
          f"got {len(hist)}")
    check("history is ordered oldest first",
          [h["rank"] for h in hist][-2:] == [4, 7], f"got {[h['rank'] for h in hist]}")

    # Re-running the tracker within the same timestamp must not duplicate.
    db.record_rank("111", "mom necklace", rank=7, observed_at="2026-08-19T00:00:00+00:00")
    check("re-recording the identical observation is idempotent",
          len(db.get_rank_history("111")) == 3,
          f"got {len(db.get_rank_history('111'))}")

    # --- D-12's gate has a number to read ----------------------------------------------------
    print()
    check("launch_count feeds the D-12 threshold", db.launch_count() == 3,
          f"got {db.launch_count()}")
    check("a duplicate launch does not inflate the count",
          (db.record_launch("111", "mom necklace"), db.launch_count())[1] == 3)

    # --- B-04: control launches ----------------------------------------------------------------
    # Without controls the LEARN loop only ever sees things the model scored highly, so it
    # measures precision and can never measure recall — it cannot discover that something
    # it rejected would have won. A control is a deliberate mid/low-scored launch.
    print()
    db2 = GraphDB(db_path=os.path.join(tempfile.mkdtemp(), "controls.db"))
    db2.record_launch("A", "term-a", predicted_score=0.91)
    db2.record_launch("B", "term-b", predicted_score=0.88)
    db2.record_launch("C", "term-c", predicted_score=0.22, is_control=True)

    check("a launch defaults to NOT a control", db2.get_launches(term_id="term-a")[0]["is_control"] == 0,
          f"got {db2.get_launches(term_id='term-a')[0]['is_control']}")
    check("a control launch is flagged", db2.get_launches(term_id="term-c")[0]["is_control"] == 1)
    check("controls are countable separately from the total",
          (db2.launch_count(), db2.launch_count(controls_only=True)) == (3, 2 - 1),
          f"got total={db2.launch_count()} controls={db2.launch_count(controls_only=True)}")
    check("control_ratio reports the share of launches that test the model",
          abs(db2.control_ratio() - 1 / 3) < 1e-9, f"got {db2.control_ratio()}")
    check("control_ratio on an empty table is None, not 0.0 — nothing was measured",
          GraphDB(db_path=os.path.join(tempfile.mkdtemp(), "e.db")).control_ratio() is None)
    check("prediction_vs_outcome carries the control flag so calibration can exclude them",
          {r["listing_id"]: r["is_control"] for r in db2.prediction_vs_outcome()}
          == {"A": 0, "B": 0, "C": 1})

    # --- no launches at all -------------------------------------------------------------------
    print()
    empty_db = GraphDB(db_path=os.path.join(tempfile.mkdtemp(), "empty.db"))
    check("tracking with no launches returns empty and does not crash",
          track_ranks(db=empty_db, public_api=FakeAPI({})) == [])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
