"""Offline tests for the gap finder. No network, no database.

The assertion that matters most is D-10's worked example: shipping-speed arbitrage on a
digital product must never be reported as an opportunity, however empty the bracket is.
That is the exact case `master_arbitrage.py` gets wrong today.

Run:  python -m etsy.analytics.test_gaps
"""
import sys

from etsy.analytics.gaps import (DIGITAL, PERSONALIZED, PHYSICAL, analyse_bracket,
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
    results = find_gaps(brackets, DIGITAL, total_listings=50000, demand_by_bracket=demand)

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
    phys = find_gaps(brackets, PHYSICAL, total_listings=50000, demand_by_bracket=demand)
    check("sweep: for a physical product those dimensions become answerable",
          summarise(phys).get("not_applicable") is None, f"got {summarise(phys)}")
    check("sweep: but they are still 'empty', not gaps, without demand",
          all(not r.is_gap for r in phys if r.listings == 0))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
