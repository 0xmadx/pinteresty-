"""Offline tests for sourcing analysis. No network.

The guard that matters most: a filter Etsy IGNORED returns the unfiltered total,
which would otherwise read as "100% of listings match" — the exact opposite of the
truth, and invisible. That is how a wrong parameter name poisons an analysis.

Run:  python -m etsy.analytics.test_sourcing
"""
import sys
from datetime import date
from etsy.analytics.sourcing import (IGNORED, build_profile, delivery_distribution,
                                     median_band, parse_get_by, read, to_share)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    # --- the ignored-filter guard ---------------------------------------------------
    s = to_share("China", 1000, 1000)
    check("a count equal to the total is flagged as IGNORED, not 100%",
          s.status == IGNORED, f"got {s.status}")
    check("a normal count is measured", to_share("China", 250, 1000).status == "measured")
    check("a None count is unmeasured, not zero",
          to_share("China", None, 1000).status == "unmeasured")
    check("share is computed against total", to_share("US", 250, 1000).share == 0.25)
    check("zero total does not divide by zero", to_share("US", 5, 0).share == 0.0)

    # --- the real towel numbers -------------------------------------------------------
    print()
    p = build_profile("personalized towel", 217213,
                      {"United States": 180214, "United Kingdom": 14620,
                       "Canada": 8476, "China": 6682, "India": 3313},
                      {"7": 17640, "14": 79312})
    check("domestic share is found", abs(p.domestic.share - 0.83) < 0.01,
          f"got {p.domestic.share}")
    check("fast delivery share is found", abs(p.fast_delivery.share - 0.081) < 0.005,
          f"got {p.fast_delivery.share}")
    check("unmeasured remainder is computed (Turkey lives here)",
          abs(p.unmeasured_share - 0.0176) < 0.005, f"got {p.unmeasured_share}")

    lines = " ".join(read(p))
    check("a domestic niche says speed is table stakes", "table stakes" in lines, lines)
    check("thin fast-delivery is flagged as worth testing", "7 days" in lines)
    check("and D-10 is restated rather than assumed away", "D-10" in lines, lines)

    # --- an import-led niche reads differently -------------------------------------------
    print()
    imp = build_profile("cheap phone case", 100000,
                        {"United States": 12000, "China": 74000},
                        {"7": 500, "14": 3000})
    lines = " ".join(read(imp))
    check("import-led is named", "Import-led" in lines, lines)
    check("direct manufacturing is called out at >=50% single origin",
          "direct manufacturing" in lines, lines)

    # --- a large unattributed remainder is surfaced ----------------------------------------
    print()
    gap = build_profile("turkish towel", 50000, {"United States": 5000}, {"7": 100})
    lines = " ".join(read(gap))
    check("a big unmeasured share is reported, not folded into domestic",
          "does not list" in lines and "Turkey" in lines, lines)
    check("unmeasured share is 90%", abs(gap.unmeasured_share - 0.90) < 0.01,
          f"got {gap.unmeasured_share}")

    # --- an ignored filter surfaces in the read --------------------------------------------
    print()
    bad = build_profile("x", 1000, {"Nowhere": 1000}, {"7": 50})
    check("an ignored filter is reported to the reader",
          any("ignored" in l.lower() for l in read(bad)), read(bad))

    # --- lead time: cumulative brackets must become bands ----------------------------
    print()
    lead = build_profile("personalized towel", 217213, {"United States": 180214},
                         {"7": 17640, "14": 79312, "21": 138482, "30": 192308})
    dist = dict(delivery_distribution(lead))
    check("0-7 band matches the raw bracket", abs(dist["0-7 days"] - 0.081) < 0.005,
          f"got {dist['0-7 days']}")
    check("8-14 SUBTRACTS the faster listings (brackets are cumulative)",
          abs(dist["8-14 days"] - 0.284) < 0.005, f"got {dist['8-14 days']}")
    check("the over-30 tail is surfaced - no bracket reports it directly",
          abs(dist["over 30 days"] - 0.115) < 0.005, f"got {dist['over 30 days']}")
    check("bands sum to 1", abs(sum(dist.values()) - 1.0) < 0.001, sum(dist.values()))
    check("median band is the honest 'how long, typically'",
          median_band(lead) == "15-21 days", median_band(lead))
    ign = build_profile("x", 1000, {}, {"7": 1000, "14": 300})
    check("an ignored bracket never becomes a band",
          "0-7 days" not in dict(delivery_distribution(ign)))

    # --- per-listing delivery estimate (the delai) -------------------------------------
    print()
    t = date(2026, 8, 15)
    r = parse_get_by("Aug 24-28", today=t)
    check("same-month range parses", r["days_min"] == 9 and r["days_max"] == 13, r)
    r = parse_get_by("Aug 27-Sep 4", today=t)
    check("CROSS-MONTH range parses - the slow tail a naive parser breaks on",
          r["earliest"] == "2026-08-27" and r["latest"] == "2026-09-04", r)
    r = parse_get_by("Dec 28-Jan 5", today=t)
    check("a range rolling into next year does not go negative",
          r["latest"].startswith("2027") and r["days_max"] > r["days_min"], r)
    check("unparseable text yields None, never a guessed date",
          parse_get_by("garbage") is None and parse_get_by(None) is None)
    check("an impossible date is refused, not clamped",
          parse_get_by("Feb 30-31", today=t) is None)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
