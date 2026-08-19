"""Offline checks for the LEARN loop. Fixtures only — no DB, no network."""
from etsy.analytics.learn import (MIN_LAUNCHES_TO_CALIBRATE, PICK_SCORE, calibration,
                                  read, report)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def row(lid, score, sales=None, readings=None, control=False, rank=None, obs=0):
    return {"listing_id": lid, "term_id": "t", "launched_at": "2026-01-01",
            "predicted_score": score, "predicted_profit": None, "product_type": None,
            "is_control": int(control), "observations": obs, "latest_rank": rank,
            "latest_observed_at": None,
            "outcome_readings": readings if readings is not None
            else (1 if sales is not None else 0),
            "latest_sales": sales, "latest_revenue": None}


def main():
    # --- the D-12 floor ------------------------------------------------------------------
    print()
    few = [row(str(i), 0.9, sales=5) for i in range(3)]
    c = calibration(few)
    check("three launches cannot calibrate anything", not c["ready"], c)
    check("and it says which gate blocked it", c["blocked_by"] == "launches", c)
    check("the note names the D-12 threshold",
          str(MIN_LAUNCHES_TO_CALIBRATE) in c["note"], c["note"])

    # --- controls: without them the loop only confirms itself (B-04) ----------------------
    print()
    all_picks = [row(str(i), 0.9, sales=5) for i in range(12)]
    c = calibration(all_picks)
    check("ten launches that were ALL picks still cannot calibrate",
          not c["ready"], c)
    check("because there is no control to compare against",
          c["blocked_by"] == "controls", c)

    mixed = ([row(f"p{i}", 0.9, sales=8) for i in range(8)]
             + [row(f"c{i}", 0.2, sales=2, control=True) for i in range(4)])
    c = calibration(mixed)
    check("picks plus controls can finally calibrate", c["ready"], c)
    check("picks and controls are counted separately",
          c["picks"] == 8 and c["controls"] == 4, c)
    check("separation is the difference in mean sales",
          abs(c["separation"] - 6.0) < 0.001, c["separation"])

    # --- a losing model must be able to say so --------------------------------------------
    print()
    losing = ([row(f"p{i}", 0.9, sales=1) for i in range(8)]
              + [row(f"c{i}", 0.2, sales=6, control=True) for i in range(4)])
    c = calibration(losing)
    check("the loop can report NEGATIVE separation", c["separation"] < 0, c["separation"])
    lines = read({"launches": 12, "measured": 12, "unmeasured": 0, "rows": losing,
                  "calibration": c})
    check("and says plainly that the scorer is not picking winners",
          any("not picking winners" in l for l in lines), lines[:3])

    # --- unmeasured launches are excluded, never counted as failures ----------------------
    print()
    partial = ([row(f"p{i}", 0.9, sales=8) for i in range(6)]
               + [row(f"u{i}", 0.9) for i in range(6)]          # never measured
               + [row(f"c{i}", 0.2, sales=2, control=True) for i in range(2)])
    c = calibration(partial)
    check("unmeasured launches do not enter the scored set",
          c["launches_scored"] == 8, c)
    check("mean sales for picks ignores the unmeasured ones, not counts them as 0",
          abs(c["mean_sales_picks"] - 8.0) < 0.001, c["mean_sales_picks"])
    lines = read({"launches": 14, "measured": 8, "unmeasured": 6, "rows": partial,
                  "calibration": c})
    check("the exclusion is stated, not silent",
          any("EXCLUDED" in l for l in lines), lines[:3])

    # --- outcomes recorded but no prediction -----------------------------------------------
    print()
    unscored = [row(str(i), None, sales=5) for i in range(12)]
    c = calibration(unscored)
    check("launches with no predicted score cannot be scored",
          not c["ready"] and c["blocked_by"] == "outcomes", c)

    # --- rank and sales are reported side by side, never substituted ----------------------
    print()
    lines = read({"launches": 1, "measured": 0, "unmeasured": 1,
                  "rows": [row("x", 0.9, rank=3, obs=4)],
                  "calibration": calibration([row("x", 0.9, rank=3, obs=4)])})
    joined = " ".join(lines)
    check("a well-ranked listing with no sales data says sales are UNMEASURED",
          "rank 3" in joined and "sales unmeasured" in joined, joined)
    lines = read({"launches": 1, "measured": 0, "unmeasured": 1,
                  "rows": [row("x", 0.9, rank=None, obs=0)],
                  "calibration": calibration([])})
    check("never-checked rank is distinguished from checked-and-absent",
          "rank unchecked" in " ".join(lines), lines)
    lines = read({"launches": 1, "measured": 0, "unmeasured": 1,
                  "rows": [row("x", 0.9, rank=None, obs=3)],
                  "calibration": calibration([])})
    check("checked-and-absent reads as 'unranked'",
          "unranked" in " ".join(lines), lines)

    # --- the empty state -------------------------------------------------------------------
    print()
    lines = read({"launches": 0, "measured": 0, "unmeasured": 0, "rows": [],
                  "calibration": calibration([])})
    check("with nothing launched it says how to start",
          any("launch --seed" in l for l in lines), lines)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
