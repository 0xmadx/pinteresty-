"""Offline checks for POD costing. No network."""
from etsy.analytics import profit
from etsy.analytics.pod_costing import (PodOption, faster_share, read,
                                        required_price)

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
    check("labour is costed into the required price",
          required_price(10.10, profit.PERSONALIZED, shipping_cost=7.99,
                         labor_minutes=45) >
          required_price(10.10, profit.PERSONALIZED, shipping_cost=7.99))

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

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
