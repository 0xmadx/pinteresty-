"""Offline tests for the profit gate wired into the engines. No network, no database.

Two things are asserted here that the pure profit tests cannot cover:

  1. `parse_price` never fabricates a number — the old code coerced "Unknown" to 0.0,
     which reads as a catastrophic loss rather than as missing data.
  2. The gate's *decision* is right at the boundary: a high-demand keyword whose price
     cannot cover the fees is rejected, and a keyword with no price is carried through
     as unjudged rather than silently dropped.

Run:  python -m etsy.analytics.test_profit_gate
"""
import sys

from etsy.analytics.derivations import parse_price
from etsy.analytics.profit import DIGITAL, PERSONALIZED, PHYSICAL, verdict

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
    # --- parse_price: measured or None, never 0.0 ----------------------------------------
    check("parse_price reads a plain currency string", parse_price("$12.34") == 12.34)
    check("parse_price reads thousands separators", parse_price("$1,234.56") == 1234.56)
    check("parse_price passes numbers through", parse_price(19.99) == 19.99)
    check("parse_price accepts an int", parse_price(20) == 20.0)

    for bad in ["Unknown", "", None, "n/a", "-", "  ", "abc"]:
        check(f"parse_price({bad!r}) is None, NOT 0.0", parse_price(bad) is None,
              f"got {parse_price(bad)!r}")
    check("parse_price rejects a malformed decimal rather than guessing",
          parse_price("12.34.56") is None, f"got {parse_price('12.34.56')!r}")
    check("parse_price rejects a bool (bool is an int subclass)",
          parse_price(True) is None)
    check("parse_price treats zero as a real measured price, not as missing",
          parse_price("$0.00") == 0.0)

    # --- the gate's decision --------------------------------------------------------------
    print()
    # Where the digital floor actually bites. Fees are 0.20 listing + 6.5% + 3% + $0.25,
    # so margin = 0.905 - 0.45/price, and it crosses the 70% floor at about $2.20.
    # Worth pinning: the fixed $0.45 is what kills cheap downloads, not the percentages,
    # and the intuition "a $3 download is mostly profit" is wrong below roughly $2.
    cheap = verdict(price=1.50, product_type=DIGITAL)
    check("a $1.50 digital download cannot clear the 70% digital floor",
          not cheap["go"], f"margin {cheap['margin']:.1%}")
    check("and the rejection names the floor it missed",
          any("floor" in r for r in cheap["reasons"]))
    check("just above the break-even it passes — the gate is a threshold, not a mood",
          verdict(price=2.50, product_type=DIGITAL)["go"]
          and not verdict(price=2.00, product_type=DIGITAL)["go"],
          f"$2.50 -> {verdict(price=2.50, product_type=DIGITAL)['margin']:.1%}, "
          f"$2.00 -> {verdict(price=2.00, product_type=DIGITAL)['margin']:.1%}")

    healthy = verdict(price=18.0, product_type=DIGITAL)
    check("an $18 digital download clears it comfortably",
          healthy["go"], f"margin {healthy['margin']:.1%}, reasons {healthy['reasons']}")
    check("profit per unit is positive and below the sticker price",
          0 < healthy["profit_per_unit"] < 18.0)

    # The $25/hr operator rate is what sinks this one: 45 minutes of work is $18.75 of
    # labour cost against a $32 sale that also pays COGS, shipping and fees.
    handmade = verdict(price=32.0, product_type=PERSONALIZED, cogs=8.0,
                       shipping_cost=6.0, shipping_charged=0.0, labor_minutes=45)
    check("a made-to-order item priced below its labour cost is rejected",
          not handmade["go"], f"margin {handmade['margin']:.1%}")
    check("the $25/hr rate is actually charged against it",
          handmade["labor_cost"] == 18.75, f"got {handmade['labor_cost']}")

    # --- the capacity ceiling is surfaced, not silently applied ---------------------------
    print()
    busy = verdict(price=120.0, product_type=PERSONALIZED, cogs=15.0, shipping_cost=9.0,
                   shipping_charged=9.0, labor_minutes=60, demand_units_per_week=40)
    check("15 h/wk at 60 min/unit is a 15-unit ceiling",
          busy["weekly_capacity"] == 15, f"got {busy['weekly_capacity']}")
    check("weekly profit uses the ceiling, not the 40/wk demand",
          busy["capped_units_per_week"] == 15 and busy["capacity_bound"])
    check("being capacity-bound does not by itself fail the verdict",
          busy["go"], f"reasons {busy['reasons']}")
    check("but it is stated in the reasons",
          any("capacity-bound" in r for r in busy["reasons"]))

    # --- the engine's own branch: price is None -------------------------------------------
    print()
    # Mirrors master_niche_finder STEP 5: no price -> unjudged, never rejected.
    niches = [
        {"keyword": "has price", "median_price_low": parse_price("$24.00")},
        {"keyword": "no price", "median_price_low": parse_price("Unknown")},
    ]
    passed, rejected, unjudged = [], [], []
    for n in niches:
        if n["median_price_low"] is None:
            unjudged.append(n)
            continue
        (passed if verdict(price=n["median_price_low"], product_type=DIGITAL)["go"]
         else rejected).append(n)

    check("a priced niche is judged", len(passed) == 1 and passed[0]["keyword"] == "has price")
    check("an unpriced niche is unjudged, NOT rejected",
          len(unjudged) == 1 and len(rejected) == 0,
          f"unjudged={len(unjudged)} rejected={len(rejected)}")

    # --- the fee schedule is dated, so a stale one is visible ------------------------------
    print()
    check("every verdict carries the fee-schedule verification date",
          healthy["fee_schedule_verified"] and isinstance(healthy["fee_schedule_verified"], str))
    check("and its basis, so a stored verdict is never mistaken for a measurement",
          healthy["basis"] == "derived_from_config")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
