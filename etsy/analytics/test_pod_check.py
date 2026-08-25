"""POD viability: the ceiling comes off page one, and a ceiling is never a verdict.

The bug this suite exists to prevent is anchoring the margin floor to the wrong
price. `results-data` reports a market-wide median band; the listings that actually
rank charge roughly double it. Applying the floor to the band rejects terms POD
could serve, and the numbers below are the real ones that exposed it.

    .venv/Scripts/python.exe -m etsy.analytics.test_pod_check
"""
from etsy.analytics import profit
from etsy.analytics.pod_check import (check, ceilings, lead_time_verdict,
                                      page_one_prices, price_reality, render)
from etsy.analytics.pod_costing import PodOption

passed = failed = 0


def check_(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


# --- the real page-one prices, measured live 2026-08-25 ----------------------------
# "personalized baby blanket": 20 ranking listings, every one Bestseller-badged.
PRICES = [11.65, 15.00, 15.73, 17.97, 20.00, 20.99, 21.75, 23.25, 24.50, 24.95,
          25.43, 26.97, 29.32, 30.00, 34.00, 39.95, 39.97, 50.34, 53.20, 70.21]
CARDS = [{"price": p, "title": f"listing {i}"} for i, p in enumerate(PRICES)]
DATA = {"volume": 74580, "supply": 104368, "cvr": 0.001484, "wow_change": -6.6,
        "price_low": 11.7, "price_high": 14.3, "listings": CARDS}

page = page_one_prices(CARDS)
check_("page-one prices are measured from the free competitor cards",
       page["basis"] == "measured" and page["n"] == 20, page)
check_("the median is what page one charges, not the API band",
       page["median"] == 25.19, page["median"])
check_("and the spread is carried, not flattened to one number",
       page["min"] == 11.65 and page["max"] == 70.21, page)

# --- the gap between the two price populations ------------------------------------
r = price_reality(DATA)
check_("both populations are reported, never merged",
       r["band_low"] == 11.7 and r["page_one"]["basis"] == "measured", r)
check_("the ratio exposes that winners charge a premium",
       r["ratio"] > 1.3, r["ratio"])
check_("and the note says to price off page one",
       "not the band" in r["note"], r["note"])
# API band midpoint $13.00 vs page-one median $25.19 -> 1.94x. Anchoring the margin
# floor to $13 is what makes a servable term look impossible.

# --- the ceiling changes with the anchor, which is the whole point ----------------
caps = {c["label"]: c["max_cogs"] for c in ceilings(r, profit.PHYSICAL)}
check_("a ceiling is computed at the market band", caps["market band low"] is not None)
check_("and at the page-one median", caps["page-one MEDIAN"] is not None)
check_("the page-one ceiling is materially higher than the band's",
       caps["page-one MEDIAN"] > caps["market band low"] * 1.5, caps)
# Measured: $5.21 at the band vs $12.82 at page one. A blank a supplier can hit at
# $12 is a business; at $5 it is not. Same term, same margin floor, one anchor.

# --- a price too low to carry fees says so, and blames the price ------------------
tiny = price_reality({"price_low": 1.0, "price_high": 1.2,
                      "listings": [{"price": 1.1}]})
tiny_caps = ceilings(tiny, profit.PHYSICAL)
check_("a price that cannot carry Etsy's fees yields None, not a negative ceiling",
       any(c["max_cogs"] is None for c in tiny_caps), tiny_caps)
# None here means the problem is the price, not the supplier — a real answer.

# --- absent is not zero (N-02) ----------------------------------------------------
none_priced = page_one_prices([{"title": "no price"}, {"price": None}])
check_("cards with no readable price are unmeasured, not $0",
       none_priced["basis"] == "unmeasured" and none_priced["n"] == 0, none_priced)
check_("and no median is invented", "median" not in none_priced, none_priced)
check_("empty input does not crash", page_one_prices([])["basis"] == "unmeasured")
check_("None input does not crash", page_one_prices(None)["basis"] == "unmeasured")

half = price_reality({"price_low": None, "price_high": None, "listings": CARDS})
check_("one measured population cannot produce a ratio",
       half["ratio"] is None, half)
check_("and it says which comparison is missing",
       "cannot compare" in half["note"], half["note"])

# --- lead time: the number Printify DOES give -------------------------------------
slow = [PodOption(575, "Soft Fleece Baby Blanket", 70, "Printed Mint", 1,
                  ship_first_item=7.09, ship_additional=3.99, handling_days=10)]
lt = lead_time_verdict(slow)
check_("handling time is read from the option", lt["fastest_handling_days"] == 10, lt)
check_("a 10-day handling floor cannot reach Etsy's 7-day bracket",
       lt["can_reach_fast_bracket"] is False, lt)
check_("and the consequence is spelled out",
       "except speed" in lt["detail"], lt["detail"])
# This is the structural POD constraint: handling alone exceeds the fast bracket.

fast = [PodOption(1, "Poster", 2, "Fast Co", 1, handling_days=1)]
check_("a genuinely fast option is recognised",
       lead_time_verdict(fast)["can_reach_fast_bracket"] is True)

unknown = [PodOption(1, "X", 2, "Y", 1, handling_days=None)]
check_("unknown handling is unmeasured, NOT 'cannot ship fast'",
       lead_time_verdict(unknown)["basis"] == "unmeasured", lead_time_verdict(unknown))
check_("no options at all is also unmeasured",
       lead_time_verdict(None)["basis"] == "unmeasured")
# can_ship_fast returns None for unknown handling, and None must not read as False.

# --- the whole check never claims profitability -----------------------------------
result = check("personalized baby blanket", DATA, options=slow)
check_("COGS is declared unavailable, not guessed",
       result["cogs_basis"] == "unavailable_from_printify_catalog", result["cogs_basis"])
check_("and the next step hands sourcing back to the operator",
       "Printify UI" in result["next_step"], result["next_step"])
check_("no key anywhere claims the term is profitable",
       "profitable" not in str(result).lower())
# Printify's catalog has no variant price, so a ceiling is the strongest honest
# output. Returning "profitable" would require inventing the one missing number.

check_("demand rides along so the ceiling is not read in isolation",
       result["demand"]["volume"] == 74580, result["demand"])

# --- render -----------------------------------------------------------------------
out = render(result)
check_("the render marks where to price", "<-- price here" in out, out[:200])
check_("shows both price populations", "market band" in out and "page one" in out)
check_("names the lead-time consequence", "except speed" in out)
check_("and states the COGS gap rather than hiding it",
       "unavailable_from_printify_catalog" in out)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
