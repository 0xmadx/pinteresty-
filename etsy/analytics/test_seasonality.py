"""JOIN 1 — the partial month never becomes a crash, and one source never confirms itself.

Both guards here exist because of something measured. Etsy sends the current month
half-counted, and a naive peak/trough scan reads that as a collapse — `felt garland`'s
apparent trough WAS the partial bucket. And a flat curve has a maximum in it like any
other, so without a ratio floor every evergreen term acquires a fake deadline.

    .venv/Scripts/python.exe -m etsy.analytics.test_seasonality
"""
from etsy.analytics.seasonality import (MIN_POINTS, SEASONAL_RATIO, compare,
                                        peak_month, profile, render)
from etsy.api.private.api import parse_chart_series

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def curve(values, labels=None, partial=False):
    labels = labels or ["Sep 2025", "Oct 2025", "Nov 2025", "Dec 2025", "Jan 2026",
                        "Feb 2026", "Mar 2026", "Apr 2026", "May 2026", "Jun 2026",
                        "Jul 2026", "Aug 2026"][:len(values)]
    return {"points": [{"label": l, "value": v, "timestamp": 0}
                       for l, v in zip(labels, values)],
            "last_is_partial": partial, "granularity": "month"}


# --- the real curves, measured live 2026-08-20 -------------------------------------
XMAS = [41088, 71000, 163930, 85000, 7000, 1758, 1000, 3000, 5000, 11000, 23000, 21245]
MOM = [7000, 7000, 15000, 16683, 7000, 6000, 7000, 12000, 10000, 5698, 13000, 9000]

xmas = profile(curve(XMAS, partial=True))
check("a strongly seasonal term is called seasonal",
      xmas["verdict"] == "seasonal", xmas)
check("with the peak month Etsy actually measured",
      xmas["peak_label"] == "Nov 2025", xmas)
check("and a swing that quotes both ends", "93" in str(xmas["ratio"]), xmas["ratio"])
check("the peak month resolves to a number for joining", peak_month(xmas) == 11,
      peak_month(xmas))

mom = profile(curve(MOM, partial=True))
check("a 2.9x swing still counts as seasonal", mom["verdict"] == "seasonal", mom)
check("and its peak is DECEMBER, not Mother's Day",
      mom["peak_label"] == "Dec 2025", mom)
# By search volume "mom necklace" is a Christmas gift before it is a May one. Only a
# measured curve says so; the name implies the opposite.

# --- the partial bucket must never become the trough -------------------------------
# The real trap: a curve whose LAST month is the lowest only because it is half over.
sneaky = [5000, 5000, 5200, 5100, 4900, 5000, 5100, 5000, 4950, 5050, 5000, 900]
with_flag = profile(curve(sneaky, partial=True))
without_flag = profile(curve(sneaky, partial=False))

check("with the partial flag, the half-counted month is NOT the trough",
      with_flag["trough_label"] != "Aug 2026", with_flag)
check("and the term reads evergreen, which is the truth",
      with_flag["verdict"] == "evergreen", with_flag)
check("without the flag the same data looks like a 5.6x seasonal collapse",
      without_flag["verdict"] == "seasonal", without_flag)
# That contrast IS the bug. The flag is the only thing separating them, and every
# caller in this repo would have hit it.

check("the partial month is still reported, just not judged on",
      with_flag["partial_month"]["label"] == "Aug 2026", with_flag)
check("and the months actually used are counted",
      with_flag["months_used"] == 11, with_flag)

# --- a flat curve is evergreen, not a season ---------------------------------------
flat = profile(curve([1000, 1050, 980, 1020, 1010, 990, 1030, 1000, 1005, 995, 1015, 1000]))
check("a drifting curve is evergreen", flat["verdict"] == "evergreen", flat)
check("and says there is no season worth timing",
      "no season worth timing" in flat["detail"], flat)
check("the threshold is stated, not implicit", SEASONAL_RATIO == 2.0)
check("no peak month is offered for an evergreen term to join on",
      peak_month(flat) is None, peak_month(flat))
# Without this floor every flat term gets a maximum, a "peak month", and a deadline.

# --- refusals name themselves -------------------------------------------------------
check("no curve at all is unmeasured", profile(None)["verdict"] == "unmeasured")
check("and names why", profile(None)["basis"] == "no_curve")
check("an empty point list is unmeasured too",
      profile({"points": []})["verdict"] == "unmeasured")

short = profile(curve([100, 200, 300]))
check("too few months refuses rather than guessing a peak",
      short["verdict"] == "unmeasured", short)
check("and names the curve length as the reason",
      short["basis"] == "curve_too_short", short)
check(f"the minimum is stated", MIN_POINTS == 6)

# A zero trough must not produce an infinite ratio.
zeroed = profile(curve([0, 0, 5000, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
check("a zero trough yields a finite ratio, not inf",
      zeroed["ratio"] == 5000.0, zeroed.get("ratio"))

# --- JOIN 1: two sources, and disagreement is the output ---------------------------
agree = compare(xmas, 11)
check("two sources naming the same month agree", agree["agree"] is True, agree)
check("and it is called out as two INDEPENDENT sources",
      "independent" in agree["detail"], agree)

near = compare(xmas, 12)
check("one month apart still counts as agreement", near["agree"] is True, near)

disagree = compare(xmas, 5)
check("a five-month gap is a disagreement", disagree["agree"] is False, disagree)
check("and it is reported, never averaged into one date",
      "disagree" in disagree["detail"], disagree)
check("carrying both months so the operator can check",
      disagree["etsy_peak_month"] == 11 and disagree["pinterest_peak_month"] == 5,
      disagree)

# December and January are one month apart, not eleven.
wrap = compare(profile(curve(MOM, partial=True)), 1)
check("the month gap wraps around the year end",
      wrap["months_apart"] == 1 and wrap["agree"] is True, wrap)

# --- one source cannot confirm itself ----------------------------------------------
alone = compare(xmas, None)
check("with no Pinterest peak, agreement is None — not True",
      alone["agree"] is None, alone)
check("and it says one source cannot confirm itself",
      "cannot be confirmed by itself" in alone["detail"], alone)
check("an evergreen Etsy curve also cannot be compared",
      compare(flat, 11)["agree"] is None)
# `None` here is a third state, deliberately: False would read as "they disagree".

# --- the parser is what feeds all of this ------------------------------------------
raw = {"granularity": "month", "is_last_bucket_partial": True, "series": [
    {"search_term": "christmas ornament", "series_type": "search_volume",
     "points": [{"label": "Nov 2025", "value": 163930, "timestamp": 1}]},
    {"search_term": "christmas ornament", "series_type": "avg_total_listings",
     "points": [{"label": "Nov 2025", "value": 99, "timestamp": 1}]},
]}
parsed = parse_chart_series(raw)
check("the parser keys curves by term", "christmas ornament" in parsed, parsed)
check("and keeps ONLY the volume series, not the supply one",
      parsed["christmas ornament"]["points"][0]["value"] == 163930, parsed)
check("the partial flag rides on every curve",
      parsed["christmas ornament"]["last_is_partial"] is True, parsed)
check("an absent term simply has no entry — it is not an empty curve",
      "linen apron" not in parsed, parsed)
# Asked Etsy for 4 terms and got 3; the missing one is unmeasured, not flat (N-02).
check("an empty response parses to nothing rather than raising",
      parse_chart_series(None) == {} and parse_chart_series({}) == {})
check("a point with no value is skipped, not read as 0",
      parse_chart_series({"series": [{"search_term": "t",
                                      "series_type": "search_volume",
                                      "points": [{"label": "x", "value": None}]}]}) == {})

# --- render -------------------------------------------------------------------------
out = render("christmas ornament", xmas, agree)
check("the render leads with the verdict", "SEASONAL" in out, out)
check("shows the partial month as in progress", "still in progress" in out, out)
check("and marks agreement", "✓" in out, out)
check("a refusal renders its reason rather than a blank",
      "no seasonal reading" in render("x", profile(None)))

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
