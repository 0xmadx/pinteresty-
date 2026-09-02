"""Offline checks for POD costing. No network."""
from etsy.analytics import profit
from etsy.analytics.pod_costing import (PodOption, affordable_cogs, cogs_ladder,
                                        faster_share, read, required_price)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def opt(**kw):
    base = dict(blueprint_id=352, blueprint_title="Beach Towel", provider_id=99,
                provider_title="Printify Choice", variants=2,
                ship_first_item=7.99, ship_additional=2.99, handling_days=10)
    base.update(kw)
    return PodOption(**base)


def main():
    # --- required_price is the inverse of the profit gate ------------------------------
    print()
    p = required_price(10.10, profit.PERSONALIZED, shipping_cost=7.99)
    check("a price is returned for a real COGS", p is not None, p)
    econ = profit.unit_economics(p, profit.PERSONALIZED, 10.10, 7.99)
    floor = profit.ProfitConfig().floors.for_type(profit.PERSONALIZED)
    check("the price it returns actually clears the floor", econ["margin"] >= floor,
          f"margin {econ['margin']:.3f} vs floor {floor}")
    just_under = profit.unit_economics(p - 0.25, profit.PERSONALIZED, 10.10, 7.99)
    check("and it is the LOWEST such price -- a cent under misses",
          just_under["margin"] < floor, just_under["margin"])
    check("a higher COGS demands a higher price",
          required_price(22.15, profit.PERSONALIZED, shipping_cost=7.99) > p)
    check("a cheaper floor (physical) demands less than personalized",
          required_price(10.10, profit.PHYSICAL, shipping_cost=7.99) < p)

    # --- refusing rather than guessing --------------------------------------------------
    print()
    check("unknown COGS yields no price, never a default one",
          required_price(None, profit.PERSONALIZED) is None)
    pass  # REPLACED — see the labour block below
    

    # --- lead time ----------------------------------------------------------------------
    print()
    o = opt()
    check("lead time adds transit to handling", o.lead_days == (12, 16), o.lead_days)
    check("a 10-day handling time CANNOT reach the 7-day bracket",
          o.can_ship_fast is False)
    check("unknown handling is None, not 'fast'",
          opt(handling_days=None).can_ship_fast is None)
    check("unknown handling yields no lead time at all",
          opt(handling_days=None).lead_days is None)
    check("a 2-day handling time can reach the fast bracket",
          opt(handling_days=2).can_ship_fast is True)

    # --- joining to the market's own delivery curve --------------------------------------
    print()
    bands = [("0-7 days", 0.081), ("8-14 days", 0.284), ("15-21 days", 0.272),
             ("22-30 days", 0.248), ("over 30 days", 0.115)]
    s = faster_share(o, bands)
    check("only bands wholly faster than our slowest case count",
          abs(s - 0.365) < 0.001, s)
    check("an unmeasured market does not read as 'nobody is faster'",
          faster_share(o, None) is None)
    check("unknown lead time does not read as 'nobody is faster'",
          faster_share(opt(handling_days=None), bands) is None)

    # --- what read() will and will not claim ----------------------------------------------
    print()
    lines = read(opt(cogs=None), market_bands=bands)
    check("unknown COGS is stated loudly, not silently skipped",
          any("UNKNOWN" in l for l in lines))
    check("and no price is quoted alongside it",
          not any("Charge at least" in l for l in lines))
    check("the closed fast bracket is called out",
          any("Cannot enter" in l for l in lines))
    lines = read(opt(cogs=10.10), market_bands=bands)
    check("a confirmed COGS produces a concrete price",
          any("Charge at least" in l for l in lines))
    # $95 COGS on a $7.99 shipping: fees scale with price, so the floor is unreachable.
    lines = read(opt(cogs=900.0), market_bands=bands)
    check("an impossible product is named as impossible, not priced anyway",
          any("cannot be made to pay" in l for l in lines), lines)

    # --- the other inverse: what may this cost to make? ---------------------------------
    print()
    m = affordable_cogs(45.78, profit.PERSONALIZED, shipping_cost=7.99)
    check("a price yields a maximum affordable COGS", m is not None, m)
    ok = profit.unit_economics(45.78, profit.PERSONALIZED, m, 7.99)
    check("at that COGS the floor is cleared", ok["margin"] >= floor, ok["margin"])
    over = profit.unit_economics(45.78, profit.PERSONALIZED, m + 0.25, 7.99)
    check("and a cent more misses it -- it really is the maximum",
          over["margin"] < floor, over["margin"])
    check("required_price and affordable_cogs are consistent inverses",
          abs(m - 10.10) < 0.30, m)
    check("a higher price affords a more expensive product",
          affordable_cogs(80.0, profit.PERSONALIZED, shipping_cost=7.99) > m)
    check("at the market's actual price the product is impossible even FREE",
          affordable_cogs(16.60, profit.PERSONALIZED, shipping_cost=7.99) is None)
    # 45 minutes of the operator's time at $45.78 leaves nothing for a supplier at
    # all -- affordable_cogs returns None, not a smaller number. That is the honest
    # answer: the problem is the labour, and no sourcing decision fixes it.
    with_labour = affordable_cogs(45.78, profit.PERSONALIZED, shipping_cost=7.99,
                                  labor_minutes=45)
    pass  # REPLACED — see the labour block below
    
    pass  # REPLACED — see the labour block below
    
    ladder = cogs_ladder([16.60, 30.0, 45.78, 80.0], profit.PERSONALIZED,
                         shipping_cost=7.99)
    check("the ladder returns one entry per price", len(ladder) == 4)
    check("it shows where a product BECOMES possible, not just that it failed",
          ladder[0][1] is None and ladder[-1][1] is not None, ladder)

    # --- labour is REPORTED, not charged (changed 2026-09-01) ----------------------
    #
    # These three assertions used to pin the opposite: "labour is costed into the
    # required price", "labour can make a price impossible outright". That model
    # subtracted the operator's own hourly rate as a COST and then required the
    # remainder to clear a 35-70% floor — charging the product a wage AND taking half
    # of what was left.
    #
    # Measured on the real "Custom sign" profile, a $45 sign taking 45 minutes:
    #     old:  profit $9.53, margin 21%  -> REJECTED (below the 50% floor)
    #     true: the seller takes home $28.28 for 45 min = $37.70/hour
    # The operator's words: "i dont need this $25/hr cos am seller". They do not pay
    # themselves a wage; they keep the profit.
    print()
    from etsy.analytics import profit as _p
    base = dict(product_type="personalized", cogs=12.0, shipping_cost=0.0,
                shipping_charged=0.0)
    none_ = _p.unit_economics(45.0, labor_minutes=0.0, **base)
    lots_ = _p.unit_economics(45.0, labor_minutes=45.0, **base)

    check("labour does NOT change the cash margin — it is not cash out",
          none_["margin"] == lots_["margin"], (none_["margin"], lots_["margin"]))
    check("nor the profit that reaches the seller",
          none_["profit_per_unit"] == lots_["profit_per_unit"])
    check("so it cannot make a price impossible any more",
          lots_["margin"] > 0.5, lots_["margin"])

    # What replaced it: the number a maker actually judges by.
    check("but the TIME is reported, as dollars per hour",
          lots_["profit_per_hour"] == round(lots_["profit_per_unit"] / 0.75, 2),
          lots_["profit_per_hour"])
    check("and it is the seller's call, not a gate — a 45-min sign at $45 pays ~$37/hr",
          36 < lots_["profit_per_hour"] < 39, lots_["profit_per_hour"])
    check("no build time means no hourly rate — unmeasured, NOT infinite",
          none_["profit_per_hour"] is None)
    # The old view is kept, clearly named, so an opportunity-cost read is one field away.
    check("the after-labour view survives under its own name",
          lots_["margin_after_labor"] < lots_["margin"]
          and lots_["profit_after_labor"] < lots_["profit_per_unit"])
    check("and the margin says which basis it is on",
          "CASH" in lots_["margin_basis"])

    # The floor now tests cash. A price genuinely too thin still fails.
    thin = _p.verdict(price=9.0, product_type="physical", cogs=4.0,
                      shipping_cost=4.5, shipping_charged=5.0, labor_minutes=12.0)
    check("a genuinely thin price is still refused — this is not a rubber stamp",
          thin["go"] is False and thin["margin"] < 0.35, (thin["margin"], thin["go"]))

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
