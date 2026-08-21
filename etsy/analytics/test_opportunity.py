"""Calendar × demand × profit, and the unit trap it exists to avoid.

`profit.verdict()` takes `demand_units_per_week` meaning units THE OPERATOR sells.
Etsy's volume × CVR is the whole marketplace's demand, split across every competing
listing — 351,677 of them for "mom necklace". Feeding one into the other yields a
weekly profit that quietly assumes the operator wins the entire niche: large, specific,
and pure fantasy, on the screen decisions are made from.

Offline: no network, injected fetch, settings in a temp path.

    .venv/Scripts/python.exe -m etsy.analytics.test_opportunity
"""
import pathlib
import tempfile

from core.settings_store import Settings, _defaults
from etsy.analytics.opportunity import evaluate, for_calendar, market_demand

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def settings_with(profile="Mug", **profile_kwargs):
    s = Settings(_defaults(), pathlib.Path(tempfile.mkdtemp()) / "s.json")
    s.add_profile(profile, profile_kwargs.pop("product_type", "physical"),
                  **profile_kwargs)
    return s


def data(volume=12867, cvr=0.000256, low=17.10, high=20.90, supply=351677, wow=10.5):
    return {"volume": volume, "cvr": cvr, "price_low": low, "price_high": high,
            "supply": supply, "wow_change": wow}


# --- market demand is the MARKET's -------------------------------------------------
m = market_demand(data())
check("market demand is computed", m["units_per_week"] == 0.76, m)
check("labelled relative-only, NOT an order count", m["basis"] == "relative_only", m)
check("and says so in a field a caller cannot miss",
      m["not_an_order_count"] is True, m)
# Probed 2026-08-20: volume x query_cvr implies 39.8 orders/month market-wide for
# "personalized gift", whose #1 listing carries 14,733 reviews — ~30 years' worth.
# The figure is off by orders of magnitude, so it may be compared between terms
# (D-43's intent gate) but never thresholded as units.
check("and declared an upper bound for one shop",
      m["is_upper_bound_for_one_shop"] is True, m)
check("the detail names the split", "351677 listings" in m["detail"], m["detail"])

m = market_demand({"volume": None, "cvr": 0.02})
check("missing volume is unmeasured, not zero", m["units_per_week"] is None, m)
check("and says so", m["basis"] == "unmeasured", m)
# Zero would read as "nobody buys this" — the N-02 failure in the demand slot.

# --- THE trap ----------------------------------------------------------------------
s = settings_with(cogs=8.5, shipping_cost=4.2, labor_minutes=3)
r = evaluate("mom necklace", data(), s, "Mug")
check("without a capture share the weekly figure is zero, not market-wide",
      r["verdict"]["weekly_profit"] == 0.0, r["verdict"]["weekly_profit"])
check("and capped units stay zero", r["verdict"]["capped_units_per_week"] == 0, r)
check("while the per-unit verdict is still made",
      r["verdict"]["profit_per_unit"] is not None, r)
# The verdict needs no demand estimate, so it cannot be inflated by one.

check("market demand is still reported separately",
      r["market"]["units_per_week"] == 0.76, r["market"])
check("no share means no assumption recorded", r["capture_share"] is None, r)

# --- a share is allowed, but only when stated --------------------------------------
r = evaluate("mom necklace", data(volume=200000, cvr=0.01), s, "Mug", capture_share=0.05)
check("an explicit share produces weekly figures",
      r["verdict"]["capped_units_per_week"] > 0, r["verdict"])
check("and the assumption travels with the number",
      "5%" in r["capture_note"], r["capture_note"])

try:
    evaluate("x", data(), s, "Mug", capture_share=1.5)
    check("an impossible share is refused", False, "accepted 150%")
except ValueError:
    check("an impossible share is refused", True)
try:
    evaluate("x", data(), s, "Mug", capture_share=0)
    check("a zero share is refused", False)
except ValueError:
    check("a zero share is refused", True)

r = evaluate("x", data(volume=None), s, "Mug", capture_share=0.1)
check("a share against unmeasured demand yields no weekly figure",
      r["verdict"]["capped_units_per_week"] == 0, r["verdict"])
check("and the mismatch is stated", "unmeasured" in r["capture_note"], r["capture_note"])

# --- no price band is a refusal, not a rejection -----------------------------------
r = evaluate("obscure term", data(low=None, high=None), s, "Mug")
check("a missing price band refuses", r["verdict"] is None, r)
check("named as such", r["basis"] == "no_price_band", r)
check("and explicitly not a rejection", "not rejected" in r["reason"], r["reason"])
# Inventing a price sets the margin, which sets the verdict — the whole chain from
# one guess.
check("market demand is still reported", r["market"]["units_per_week"] is not None, r)

# --- provenance reaches the decision ------------------------------------------------
r = evaluate("mom necklace", data(), s, "Mug")
check("a verdict on default fees is provisional", r["provisional"] is True, r)
from core.settings_store import VERDICT_CRITICAL  # noqa: E402
for field in VERDICT_CRITICAL:
    s.set(field, s.get(field))
check("and stops being so once confirmed",
      evaluate("mom necklace", data(), s, "Mug")["provisional"] is False)

# --- only urgent rows spend private-tier calls --------------------------------------
calls = []


def fetch(term):
    calls.append(term)
    return data()


rows = [{"moment": "thanksgiving", "state": "list_now", "list_by": "2026-08-26",
         "terms": ["thanksgiving garland"], "is_late": False},
        {"moment": "new years eve", "state": "watching", "list_by": "2026-10-28",
         "terms": ["party decor"]}]
out = for_calendar(rows, fetch, s, "Mug")
check("only the urgent moment is fetched", calls == ["thanksgiving garland"], calls)
check("and the result carries its deadline", out[0]["list_by"] == "2026-08-26", out[0])
# Private-tier calls authenticate as the operator's own seller account (D-29); a
# moment ten weeks out would be stale before it mattered.

calls.clear()
out = for_calendar(rows, fetch, s, "Mug", states=("list_now", "watching"))
check("wider states can be requested explicitly", len(calls) == 2, calls)

calls.clear()
out = for_calendar(rows, lambda t: None, s, "Mug")
check("a failed fetch is recorded, not silently dropped",
      out and out[0]["basis"] == "fetch_failed", out)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
