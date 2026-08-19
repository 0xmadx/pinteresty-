"""Offline tests for sourcing analysis. No network.

The guard that matters most: a filter Etsy IGNORED returns the unfiltered total,
which would otherwise read as "100% of listings match" — the exact opposite of the
truth, and invisible. That is how a wrong parameter name poisons an analysis.

Run:  python -m etsy.analytics.test_sourcing
"""
import sys
from etsy.analytics.sourcing import IGNORED, build_profile, read, to_share

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

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
