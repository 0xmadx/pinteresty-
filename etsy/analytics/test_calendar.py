"""The calendar (D-20), and the distinction it exists to make.

A deadline that has passed is not the same as an opportunity that has gone. Halloween's
listing deadline was seven weeks ago while its peak is still two months out — measured
live 2026-08-15. A calendar that treats "past list_by" as "missed" silently discards
that; one that treats it as "on time" pretends the best window is still open. Both are
confident and wrong, which is the failure this system exists to prevent.

Offline: synthetic plans shaped like real `launch_plan` output.

    .venv/Scripts/python.exe -m etsy.analytics.test_calendar
"""
from datetime import datetime, timedelta, timezone

from etsy.analytics.calendar import (LIST_BY, LIST_NOW, PASSED, WATCHING, build,
                                     classify, match_terms_to_moment)

passed = failed = 0
NOW = datetime(2026, 8, 15, tzinfo=timezone.utc)


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def plan(moment, weeks_left, peak_in_days, phase="approaching"):
    peak = (NOW + timedelta(days=peak_in_days)).date().isoformat()
    list_by = (NOW + timedelta(weeks=weeks_left)).date().isoformat()
    return {"moment": moment, "phase": phase, "weeks_left": weeks_left,
            "list_by": list_by, "takeoff": list_by, "peak": peak}


# --- the three states -------------------------------------------------------------
r = classify(plan("thanksgiving", 1.5, 100), NOW)
check("a deadline inside 2 weeks is LIST NOW", r["state"] == LIST_NOW, r)
check("and it is not flagged late", r["is_late"] is False, r)

r = classify(plan("christmas", 4.5, 120), NOW)
check("a deadline in 4.5 weeks is LIST BY", r["state"] == LIST_BY, r)

r = classify(plan("new years eve", 10.5, 150), NOW)
check("beyond the horizon is WATCHING", r["state"] == WATCHING, r)
# Showing far-off moments as actionable trains the operator to ignore the calendar.

# --- THE distinction --------------------------------------------------------------
r = classify(plan("halloween", -7.6, 65, phase="rising"), NOW)
check("past the deadline with the peak ahead is still LIST NOW",
      r["state"] == LIST_NOW, r)
check("and it IS flagged late", r["is_late"] is True, r)
check("the reason names both facts", "late, not missed" in r["reason"], r["reason"])
check("and how far the peak still is", "65 days" in r["reason"], r["reason"])
# Measured live: this is halloween on 2026-08-15. Dropping it loses a real chance;
# treating it as on time hides that the ranking runway is gone.

r = classify(plan("mothers day", -23.6, -30, phase="ended"), NOW)
check("past the deadline AND past the peak is PASSED", r["state"] == PASSED, r)
check("the reason says wait for next year", "next year" in r["reason"], r["reason"])
# The difference between this and halloween is entirely the peak, not the deadline.

# --- refusals ----------------------------------------------------------------------
r = classify({"moment": "mystery", "weeks_left": None}, NOW)
check("a moment with no takeoff has no state", r["state"] is None, r)
check("and says why", "cannot be timed" in r["reason"], r["reason"])
# An undated moment cannot be scheduled, and inventing a date is the whole failure.

r = classify({"moment": "x", "weeks_left": 3.0, "peak": "not-a-date"}, NOW)
check("an unparseable peak does not crash the row", r["state"] == LIST_BY, r)
check("days_to_peak is None rather than guessed", r["days_to_peak"] is None, r)

# --- terms belong to moments by containment ----------------------------------------
terms = ["christmas ornament", "ornament", "christmas tree skirt", "mom necklace"]
matched = match_terms_to_moment("christmas", terms)
check("a term containing the moment matches",
      set(matched) == {"christmas ornament", "christmas tree skirt"}, matched)
check("a broader term does NOT match", "ornament" not in matched, matched)
# "ornament" is not a christmas niche; attaching it would put a year-round term on a
# seasonal deadline and make it look urgent every autumn.
check("an unrelated term does not match", "mom necklace" not in matched, matched)
check("an empty moment name matches nothing", match_terms_to_moment("", terms) == [])

# --- ordering and filtering ---------------------------------------------------------
moments = [
    {"moment": "far", "takeoff_ms": str(int((NOW + timedelta(weeks=20)).timestamp() * 1000)),
     "peak_ms": str(int((NOW + timedelta(weeks=26)).timestamp() * 1000)), "phase": "approaching"},
    {"moment": "soon", "takeoff_ms": str(int((NOW + timedelta(weeks=7)).timestamp() * 1000)),
     "peak_ms": str(int((NOW + timedelta(weeks=14)).timestamp() * 1000)), "phase": "approaching"},
]
rows = build(moments, terms=[], lead_weeks=6, now=NOW)
check("urgent moments sort before distant ones",
      [r["moment"] for r in rows] == ["soon", "far"], [r["moment"] for r in rows])
check("epoch strings are handled", all(r["list_by"] for r in rows), rows)
# Pinterest returns takeoff_ms as a STRING ("1791331200000"), not an int — the same
# shape trap as review counts arriving as "1459".

gone = [{"moment": "gone",
         "takeoff_ms": str(int((NOW - timedelta(weeks=30)).timestamp() * 1000)),
         "peak_ms": str(int((NOW - timedelta(weeks=20)).timestamp() * 1000)),
         "phase": "ended"}]
check("passed moments are hidden by default", build(gone, now=NOW) == [])
check("but available on request",
      build(gone, now=NOW, include_passed=True)[0]["state"] == PASSED)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
