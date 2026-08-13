"""Offline tests for the profit model. No network, no database.

The headline case is the one GOAL.md:104-120 describes: the highest-revenue option losing
to a cheaper one on margin, and a high-margin personalized product failing on capacity
rather than economics. If those two assertions ever break, the system has quietly gone
back to ranking on revenue.

Run:  python -m etsy.analytics.test_profit
"""
import sys

from etsy.analytics.profit import (DIGITAL, PERSONALIZED, PHYSICAL, ProfitConfig,
                                   compare, etsy_fees, unit_economics, verdict,
                                   weekly_capacity)

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
    # --- fees --------------------------------------------------------------------------
    f = etsy_fees(price=20.0)
    # 0.20 listing + 6.5% of 20 (1.30) + (3% of 20 + 0.25) (0.85) = 2.35
    check("fees: $20 item costs $2.35 in Etsy fees", abs(f["total"] - 2.35) < 0.001,
          f"got {f['total']}")
    check("fees: no offsite ad fee unless asked", f["offsite_ads"] == 0.0)

    f_ship = etsy_fees(price=20.0, shipping_charged=5.0)
    check("fees: the transaction fee applies to buyer-paid shipping too",
          f_ship["transaction"] > f["transaction"], f"got {f_ship['transaction']}")

    f_ads = etsy_fees(price=20.0, offsite_ads=True)
    check("fees: offsite ads add 15% under the $10k threshold",
          abs(f_ads["offsite_ads"] - 3.0) < 0.001, f"got {f_ads['offsite_ads']}")

    check("fees: the schedule carries its verification date",
          f["schedule_verified"] == ProfitConfig().fees.verified)

    # --- unit economics ----------------------------------------------------------------
    d = unit_economics(price=6.0, product_type=DIGITAL)
    check("digital: $6 download clears a very high margin",
          d["margin"] > 0.80, f"got {d['margin']:.3f}")
    check("digital: no COGS, no shipping", d["cogs"] == 0 and d["shipping_cost"] == 0)

    try:
        unit_economics(price=6.0, product_type=DIGITAL, cogs=2.0)
        check("digital: passing COGS is rejected rather than silently ignored", False)
    except ValueError:
        check("digital: passing COGS is rejected rather than silently ignored", True)

    try:
        unit_economics(price=6.0, product_type="physcial")
        check("unknown product type raises", False)
    except ValueError:
        check("unknown product type raises", True)

    p = unit_economics(price=38.0, product_type=PHYSICAL, cogs=14.0,
                       shipping_cost=6.0, shipping_charged=0.0, labor_minutes=5)
    check("physical: free shipping is costed as a seller subsidy",
          p["shipping_subsidy"] == 6.0, f"got {p['shipping_subsidy']}")
    check("physical: the operator's own time is costed",
          p["labor_cost"] > 0, f"got {p['labor_cost']}")

    # --- THE GOAL.md CASE: revenue ranks the wrong thing --------------------------------
    print()
    digital = unit_economics(price=6.0, product_type=DIGITAL)
    physical = unit_economics(price=38.0, product_type=PHYSICAL, cogs=14.0,
                              shipping_cost=6.0, shipping_charged=0.0, labor_minutes=5)
    check("GOAL.md: the $38 physical earns more revenue than the $6 digital",
          physical["revenue"] > digital["revenue"])
    check("GOAL.md: yet the $6 digital wins on margin — revenue ranked the wrong one",
          digital["margin"] > physical["margin"],
          f"digital {digital['margin']:.2f} vs physical {physical['margin']:.2f}")

    # --- capacity: the constraint demand cannot fix -------------------------------------
    print()
    check("capacity: digital work is unconstrained", weekly_capacity(0) is None)
    # 15h/wk = 900 min; at 60 min each that is 15 units.
    check("capacity: 60 minutes per unit allows 15/week", weekly_capacity(60) == 15,
          f"got {weekly_capacity(60)}")

    v = verdict(price=45.0, product_type=PERSONALIZED, demand_units_per_week=40,
                cogs=12.0, shipping_cost=5.0, shipping_charged=5.0, labor_minutes=60)
    check("GOAL.md: 40/wk demand against a 15/wk hands limit is flagged capacity-bound",
          v["capacity_bound"] and v["weekly_capacity"] == 15,
          f"got bound={v['capacity_bound']} cap={v['weekly_capacity']}")
    check("capacity: projected profit uses the capped units, never raw demand",
          v["capped_units_per_week"] == 15
          and abs(v["weekly_profit"] - v["profit_per_unit"] * 15) < 0.001,
          f"got {v['capped_units_per_week']} units")
    check("capacity: the ceiling is explained in the reasons",
          any("capacity-bound" in r for r in v["reasons"]))

    # --- margin floors ------------------------------------------------------------------
    print()
    thin = verdict(price=38.0, product_type=PHYSICAL, demand_units_per_week=10,
                   cogs=22.0, shipping_cost=8.0, shipping_charged=0.0, labor_minutes=5)
    check("floors: a thin-margin physical is a no-go despite healthy revenue",
          not thin["go"], f"margin {thin['margin']:.3f}")
    check("floors: the no-go names the floor it missed",
          any("floor" in r for r in thin["reasons"]), f"got {thin['reasons']}")

    good = verdict(price=6.0, product_type=DIGITAL, demand_units_per_week=200)
    check("floors: a healthy digital is a go with no reasons against it",
          good["go"] and not good["reasons"], f"got {good['reasons']}")
    check("digital: unconstrained capacity means demand passes through untouched",
          good["capped_units_per_week"] == 200 and good["weekly_capacity"] is None)

    # --- compare: the three-way decision ------------------------------------------------
    print()
    ranked = compare([
        dict(price=6.0, product_type=DIGITAL, demand_units_per_week=50),
        dict(price=38.0, product_type=PHYSICAL, demand_units_per_week=50,
             cogs=22.0, shipping_cost=8.0, labor_minutes=5),
        dict(price=45.0, product_type=PERSONALIZED, demand_units_per_week=50,
             cogs=12.0, shipping_cost=5.0, shipping_charged=5.0, labor_minutes=60),
    ])
    check("compare: returns one verdict per option", len(ranked) == 3)
    check("compare: go options rank above no-go ones",
          ranked[0]["go"] and not ranked[-1]["go"],
          f"got {[(r['product_type'], r['go']) for r in ranked]}")
    check("compare: every option reports its own margin floor",
          all("margin_floor" in r for r in ranked))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
