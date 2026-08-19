"""Offline tests for the gap finder. No network, no database.

The assertion that matters most is D-10's worked example: shipping-speed arbitrage on a
digital product must never be reported as an opportunity, however empty the bracket is.
That is the exact case `master_arbitrage.py` gets wrong today.

Run:  python -m etsy.analytics.test_gaps
"""
import sys

from etsy.analytics import filter_trust
from etsy.analytics.gaps import (ALL_DIMENSIONS, DIGITAL, PERSONALIZED, PHYSICAL,
                                 analyse_bracket,
                                 find_gaps, summarise)

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
    # --- D-10's worked example ---------------------------------------------------------
    b = analyse_bracket("shipping_speed", "7_days", listings=0, total_listings=50000,
                        product_type=DIGITAL)
    check("D-10: shipping speed on a digital product is not_applicable, not a gap",
          b.status == "not_applicable" and not b.is_gap, f"got {b.status}")
    check("D-10: the reason explains the 0% is structural",
          "structural" in b.note, f"got {b.note!r}")

    # Even with demand supplied, a non-applicable dimension stays non-applicable.
    b = analyse_bracket("gift_wrap", "true", listings=0, total_listings=50000,
                        product_type=DIGITAL, demand_in_bracket=500)
    check("D-10: demand cannot rescue a dimension that cannot apply",
          b.status == "not_applicable")

    # --- the empty-bracket trap itself ---------------------------------------------------
    print()
    b = analyse_bracket("color", "gold", listings=0, total_listings=50000,
                        product_type=PHYSICAL)
    check("trap: 0 listings with no measured demand is 'empty', never a gap",
          b.status == "empty" and not b.is_gap, f"got {b.status}")
    check("trap: the note says it is an empty cell",
          "empty cell" in b.note, f"got {b.note!r}")

    b = analyse_bracket("color", "gold", listings=0, total_listings=50000,
                        product_type=PHYSICAL, demand_in_bracket=320)
    check("trap: 0 listings WITH demonstrated demand is a genuine gap",
          b.is_gap, f"got {b.status}")

    # --- the demand gate -----------------------------------------------------------------
    print()
    thin_no_demand = analyse_bracket("occasion", "halloween", listings=200,
                                     total_listings=50000, product_type=PHYSICAL)
    check("gate: thin supply without measured demand is 'thin_but_unproven'",
          thin_no_demand.status == "thin_but_unproven" and not thin_no_demand.is_gap,
          f"got {thin_no_demand.status}")
    check("gate: it says demand was never measured inside the bracket",
          thin_no_demand.demand_evidence == "none")

    thin_demand = analyse_bracket("occasion", "halloween", listings=200,
                                  total_listings=50000, product_type=PHYSICAL,
                                  demand_in_bracket=45)
    check("gate: the same bracket WITH demand becomes a gap", thin_demand.is_gap)
    check("gate: a gap records that its demand was measured",
          thin_demand.demand_evidence == "measured")

    # --- crowded --------------------------------------------------------------------------
    print()
    crowded = analyse_bracket("format", "digital", listings=20000, total_listings=50000,
                              product_type=PHYSICAL, demand_in_bracket=900)
    check("crowded: 40% saturation is crowded even with strong demand",
          crowded.status == "crowded" and not crowded.is_gap, f"got {crowded.status}")

    mid = analyse_bracket("quality", "star_seller", listings=5000, total_listings=50000,
                          product_type=PHYSICAL, demand_in_bracket=100)
    check("mid-range saturation is not a gap", not mid.is_gap, f"got {mid.status}")

    # --- validation -------------------------------------------------------------------------
    print()
    for bad, kwargs in [("product type", dict(product_type="digtial")),
                        ("dimension", dict(dimension="vibes"))]:
        args = dict(dimension="color", value="gold", listings=1, total_listings=100,
                    product_type=PHYSICAL)
        args.update(kwargs)
        try:
            analyse_bracket(**args)
            check(f"validation: an unknown {bad} raises", False)
        except ValueError:
            check(f"validation: an unknown {bad} raises", True)

    # --- find_gaps over a full seven-dimension sweep -------------------------------------
    print()
    brackets = {
        ("shipping_speed", "7_days"): 0,      # not applicable to digital
        ("gift_wrap", "true"): 0,             # not applicable to digital
        ("free_shipping", "true"): 0,         # not applicable to digital
        ("color", "gold"): 0,                 # empty, no demand measured
        ("occasion", "halloween"): 150,       # thin + demand -> gap
        ("personalizable", "true"): 400,      # thin, no demand -> unproven
        ("format", "digital"): 30000,         # crowded
    }
    demand = {("occasion", "halloween"): 60}
    results = find_gaps(brackets, DIGITAL, total_listings=50000, demand_by_bracket=demand,
                      trust=True)

    check("sweep: every bracket is classified, none silently dropped",
          len(results) == len(brackets), f"got {len(results)}")
    check("sweep: exactly one genuine gap", sum(1 for r in results if r.is_gap) == 1,
          f"got {[r.value for r in results if r.is_gap]}")
    check("sweep: the gap is the one with demonstrated demand",
          results[0].is_gap and results[0].dimension == "occasion",
          f"got {results[0].dimension}/{results[0].status}")
    check("sweep: gaps sort above unproven and non-applicable",
          [r.status for r in results][:2] == ["gap", "thin_but_unproven"],
          f"got {[r.status for r in results]}")

    counts = summarise(results)
    check("sweep: three digital-inapplicable dimensions are reported as such",
          counts.get("not_applicable") == 3, f"got {counts}")
    check("sweep: the old code would have called 4 zero-listing brackets opportunities; "
          "this reports 0 of them as gaps",
          sum(1 for r in results if r.listings == 0 and r.is_gap) == 0)

    # Same sweep, physical: the shipping/gift/free dimensions now genuinely apply.
    phys = find_gaps(brackets, PHYSICAL, total_listings=50000, demand_by_bracket=demand,
                      trust=True)
    check("sweep: for a physical product those dimensions become answerable",
          summarise(phys).get("not_applicable") is None, f"got {summarise(phys)}")
    check("sweep: but they are still 'empty', not gaps, without demand",
          all(not r.is_gap for r in phys if r.listings == 0))

    # --- the trust gate: an untrusted filter may not produce a verdict ------------------
    print()
    b = analyse_bracket("geographic", "Germany", listings=2000, total_listings=50000,
                        product_type=PHYSICAL, trusted=False)
    check("an untrusted filter's bracket is refused, not classified",
          b.status == "untrusted_source", b.status)
    check("and it is explicitly NOT a gap", not b.is_gap)
    check("the note says how to fix it", "filter_trust" in b.note, b.note)
    b = analyse_bracket("geographic", "Germany", listings=2000, total_listings=50000,
                        product_type=PHYSICAL, trusted=True)
    check("the same bracket classifies normally when the filter is trusted",
          b.status != "untrusted_source", b.status)

    # A thin bracket WITH demand would be the strongest possible "gap" verdict.
    # It must still lose to an untrusted source: a launch recommendation built on
    # a count that is not a share is the worst outcome this system can produce.
    b = analyse_bracket("geographic", "Germany", listings=100, total_listings=50000,
                        product_type=PHYSICAL, trusted=False, demand_in_bracket=900)
    check("untrust beats even a thin bracket with proven demand",
          b.status == "untrusted_source", b.status)

    # --- find_gaps consults the registry, and can be injected for tests -----------------
    print()
    brackets = {("geographic", "Germany"): 100, ("shipping_speed", "7_days"): 100}
    none_trusted = find_gaps(brackets, PHYSICAL, 50000, trust=lambda d, v: False)
    check("find_gaps(trust=callable) refuses every bracket",
          all(b.status == "untrusted_source" for b in none_trusted))
    all_trusted = find_gaps(brackets, PHYSICAL, 50000, trust=True)
    check("find_gaps(trust=True) classifies normally for offline rule tests",
          not any(b.status == "untrusted_source" for b in all_trusted))
    check("untrusted brackets sort LAST, below even not_applicable",
          find_gaps({("geographic", "DE"): 100, ("gift_wrap", "true"): 100}, PHYSICAL,
                    50000, trust=lambda d, v: d != "geographic")[-1].dimension
          == "geographic")

    # --- the dimension -> filter map must cover what master_arbitrage sends -------------
    print()
    unmapped = [d for d in ALL_DIMENSIONS
                if d != "quality" and filter_trust.filter_for(d) is None]
    check("every gap dimension maps to a real SERP filter", not unmapped, unmapped)
    check("quality maps per value, since it asks three different filters",
          filter_trust.filter_for("quality", "star_seller") == "is_star_seller"
          and filter_trust.filter_for("quality", "5_star") == "min_rating")
    check("a dimension with no filter behind it is trusted by default",
          filter_trust.bracket_is_trusted("something_measured_elsewhere", registry={}))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
