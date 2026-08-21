"""JOIN 1 — Etsy's OWN seasonal curve, as a second opinion on Pinterest's calendar.

The calendar's timing comes entirely from Pinterest moments: one source, unchecked.
`docs/market_map/analysis/combinations.md` §JOIN 1 asks for two independent seasonal
sources so they can **confirm or contradict** each other — when both say a term peaks
in November that is strong, and when they disagree that is a flag to investigate
rather than a number to average.

The second source turned out to be already paid for. `chart-series-data` returns a
12-month volume curve per term in its `series` block, and every caller in this repo
has read `term_summaries` and thrown `series` away for the project's whole life
(D-45). No new endpoint, no new call — a parser and this module.

WHAT THE CURVE ACTUALLY LOOKS LIKE (measured 2026-08-20)
--------------------------------------------------------
    christmas ornament   peak Nov 163,930 · trough Feb  1,758  ->  93.2x   seasonal
    felt garland         peak Nov   6,784 · trough Aug  2,012  ->   3.4x   seasonal
    mom necklace         peak Dec  16,683 · trough Jun  5,698  ->   2.9x   seasonal

`mom necklace` peaking in **December** rather than May is the kind of thing only a
measured curve tells you: by search volume it is a Christmas gift before it is a
Mother's Day one.

TWO TRAPS, BOTH REAL
--------------------
**The last bucket is partial.** Etsy sends `is_last_bucket_partial: true` and the
final point is the current month counted so far. Included in a peak/trough scan it
manufactures a collapse — this module drops it from every judgement and reports it
separately, labelled.

**A flat curve is not a season.** Peak-over-trough below `SEASONAL_RATIO` is noise
with a maximum in it, and calling that a peak would put a deadline on an evergreen
term. `evergreen` is a real answer here, not a missing one.
"""
# Peak-over-trough below this is not a season. Coarse and named: measured terms run
# 2.9x (mom necklace) to 93x (christmas ornament), and a genuinely evergreen term
# drifts well under 2x across a year.
SEASONAL_RATIO = 2.0

# A curve shorter than this cannot show a year's shape, so no peak is claimed from it.
MIN_POINTS = 6


def profile(curve):
    """One term's curve -> peak, trough, and whether it is seasonal at all.

    `curve` is one value from `parse_chart_series`. Returns a `basis` of `measured`
    only when a real judgement was possible; every refusal names itself.
    """
    if not curve or not curve.get("points"):
        return {"verdict": "unmeasured", "basis": "no_curve",
                "detail": "Etsy returned no volume series for this term"}

    points = list(curve["points"])
    partial = None
    # The current month is incomplete. Judging on it invents a crash (N-02).
    if curve.get("last_is_partial") and len(points) > 1:
        partial = points[-1]
        points = points[:-1]

    if len(points) < MIN_POINTS:
        return {"verdict": "unmeasured", "basis": "curve_too_short",
                "detail": f"{len(points)} complete month(s) — fewer than "
                          f"{MIN_POINTS}, so a year's shape cannot be read",
                "partial_month": partial}

    peak = max(points, key=lambda p: p["value"])
    trough = min(points, key=lambda p: p["value"])
    # A zero trough would make the ratio infinite; clamp to 1 so the number stays
    # finite and the caller still sees an enormous, honest ratio.
    ratio = peak["value"] / max(trough["value"], 1)

    if ratio >= SEASONAL_RATIO:
        verdict = "seasonal"
        detail = (f"peaks {peak['label']} at {peak['value']:,}, bottoms "
                  f"{trough['label']} at {trough['value']:,} — {ratio:.1f}x swing")
    else:
        verdict = "evergreen"
        detail = (f"{ratio:.1f}x between best and worst month — no season worth "
                  f"timing a launch around")

    return {"verdict": verdict, "basis": "measured",
            "peak_label": peak["label"], "peak_value": peak["value"],
            "trough_label": trough["label"], "trough_value": trough["value"],
            "ratio": round(ratio, 2), "detail": detail,
            "months_used": len(points),
            # Reported, never judged on — so a reader can see the current month
            # without it having moved the verdict.
            "partial_month": partial}


def peak_month(prof):
    """The month number (1-12) of the measured peak, or None.

    **Only a SEASONAL term has one.** An evergreen curve still has a maximum, and
    returning it would hand a flat term a peak month, a deadline, and a place on the
    calendar — undoing the exact thing `SEASONAL_RATIO` exists to prevent. A measured
    verdict of `evergreen` is a real answer, and its peak month is None.

    Parses Etsy's own label ("Nov 2025"), because that is what it sends — no date
    maths on a timestamp that may be bucketed differently than it appears.
    """
    prof = prof or {}
    label = prof.get("peak_label")
    if not label or prof.get("verdict") != "seasonal":
        return None
    months = ["jan", "feb", "mar", "apr", "may", "jun",
              "jul", "aug", "sep", "oct", "nov", "dec"]
    head = str(label).strip().lower()[:3]
    return months.index(head) + 1 if head in months else None


def compare(prof, pinterest_peak_month):
    """JOIN 1: do Etsy and Pinterest agree on when this peaks?

    `pinterest_peak_month` is the month number from the Pinterest moment, or None.
    Disagreement is the OUTPUT — it is reported, never averaged into a single date
    (B-05, D-38). Two sources agreeing is the strongest timing signal this system
    can produce; two disagreeing is a flag to look before committing stock.
    """
    etsy_month = peak_month(prof)
    if etsy_month is None or pinterest_peak_month is None:
        missing = "Etsy" if etsy_month is None else "Pinterest"
        return {"agree": None, "basis": "one_source_only",
                "detail": f"{missing} has no measured peak for this term — one "
                          f"source cannot be confirmed by itself"}

    gap = abs(etsy_month - pinterest_peak_month)
    gap = min(gap, 12 - gap)          # December and January are one month apart
    if gap <= 1:
        return {"agree": True, "basis": "measured", "months_apart": gap,
                "detail": f"Etsy and Pinterest both put the peak within {gap} "
                          f"month(s) of each other — two independent sources agree"}
    return {"agree": False, "basis": "measured", "months_apart": gap,
            "etsy_peak_month": etsy_month, "pinterest_peak_month": pinterest_peak_month,
            "detail": f"Etsy measures the peak {gap} months from Pinterest's. They "
                      f"disagree — check which one describes the BUYING season "
                      f"before committing to a date"}


def render(term, prof, comparison=None):
    """Plain-language seasonality, with the refusals visible."""
    out = [f"{term}"]
    if prof.get("basis") != "measured":
        out.append(f"    no seasonal reading — {prof.get('detail')}")
        return "\n".join(out)

    out.append(f"    {prof['verdict'].upper()}: {prof['detail']}")
    partial = prof.get("partial_month")
    if partial:
        out.append(f"    ({partial['label']} is still in progress at "
                   f"{partial['value']:,} — excluded from the peak)")
    if comparison:
        mark = {True: "✓", False: "⚠", None: "·"}[comparison.get("agree")]
        out.append(f"    {mark} {comparison['detail']}")
    return "\n".join(out)
