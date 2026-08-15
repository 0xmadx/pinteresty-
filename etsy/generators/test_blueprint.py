"""The SEO blueprint, and the three things the naive version gets wrong.

Fixtures are the real values measured on `first day of school sign`, 2026-08-15:
172,705 searches, 64,555 listings, a $10.10-$13.20 median band, and page-one tags of
which eight exceed Etsy's 20-character limit.

    .venv/Scripts/python.exe -m etsy.generators.test_blueprint
"""
from etsy.analytics import profit
from etsy.generators.blueprint import (MAX_TAGS, build, build_tags, build_title,
                                       recommend_price, validate_tag)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


# The real page-one tag set. Eight of these are unusable on Etsy.
LIVE_TAGS = [
    "school sign", "back to school", "back to school board", "first day of school",
    "first day sign", "school board", "school signs",
    "first day of school sign",          # 24
    "first day of school board",         # 25
    "1st day of school sign",            # 22
    "school sign personalized",          # 24
    "personalized first day of school",  # 32
    "first day of kindergarten",         # 25
]


# --- 1. an invalid tag is rejected, not truncated -----------------------------------
ok, reason = validate_tag("personalized first day of school")
check("a 32-char tag is rejected", ok is False)
check("and the reason states the length", "32 chars" in reason, reason)
check("a 20-char tag is accepted", validate_tag("back to school board")[0] is True)
check("a comma is rejected", validate_tag("school, sign")[0] is False)
# Etsy's editor splits on commas, so one tag would silently become two.

built = build_tags("first day of school sign", LIVE_TAGS)
check("over-long tags are dropped, not silently cut",
      all(len(t) <= 20 for t in built["tags"]), built["tags"])
check("all six over-long tags are reported", len(built["rejected"]) == 6, built["rejected"])
check("each rejection says why",
      all("chars" in r["reason"] for r in built["rejected"]), built["rejected"])
check("a tag that is both primary and consensus is judged once",
      len([r for r in built["rejected"] if r["tag"] == "first day of school sign"]) == 1,
      built["rejected"])
# Counting it twice would inflate the "N tags exceed the limit" warning the operator
# uses to judge how much of page one is unusable.

# --- 2. no invented filler ----------------------------------------------------------
check("only measured, valid tags are used", built["filled"] == 7, built["filled"])
check("under-filling is reported, not padded", built["is_complete"] is False, built)
# 13 slots is the limit, never a quota to fill.

many = build_tags("term", [f"tag number {i}" for i in range(30)])
check("never exceeds Etsy's 13", len(many["tags"]) == MAX_TAGS, len(many["tags"]))

dupes = build_tags("school sign", ["school sign", "School Sign", "  school sign  "])
check("duplicates and casing collapse to one", len(dupes["tags"]) == 1, dupes["tags"])

sourced = build_tags("primary term", ["consensus a"], ["gap a"], ["tail a"])
check("the primary term leads", sourced["tags"][0] == "primary term", sourced["tags"])
check("every tag records its source",
      sourced["sources"] == {"primary": 1, "consensus": 1, "gap": 1, "long_tail": 1},
      sourced["sources"])
# The mix is the strategy; without provenance the operator cannot shift it.

# --- 3. a price that loses money is refused ----------------------------------------
# Measured: even at the top of the band the margin is 13.9% against a 35% floor.
def verdict_for(price):
    return profit.verdict(price=price, product_type="physical", demand_units_per_week=0,
                          cogs=8.0, shipping_cost=3.0, labor_minutes=0)


priced = recommend_price(10.10, 13.20, verdict_for)
check("a band that cannot clear the floor returns no price", priced["price"] is None, priced)
check("named band_below_floor", priced["basis"] == "band_below_floor", priced)
check("and reports the margin at the top of the band",
      priced["margin_at_band_top"] < 0.35, priced)
check("the reason says the niche does not pay",
      "does not pay at market prices" in priced["reason"], priced["reason"])
# Returning the midpoint anyway is exactly how a plausible wrong number reaches the
# operator — and it is the number they would list at.


def healthy(price):
    return profit.verdict(price=price, product_type="physical", demand_units_per_week=0,
                          cogs=2.0, shipping_cost=1.0, labor_minutes=0)


priced = recommend_price(20.0, 40.0, healthy)
check("a workable band returns a price", priced["price"] is not None, priced)
check("inside the band", 20.0 <= priced["price"] <= 40.0, priced)
check("and it clears the floor", priced["margin"] >= 0.35, priced)

check("no band is a refusal, not a rejection",
      recommend_price(None, None, healthy)["basis"] == "no_price_band")

# --- title --------------------------------------------------------------------------
title = build_title("first day of school sign",
                    ["school sign", "back to school", "first day of school sign"],
                    product_type="personalized")
check("the title leads with the exact term",
      title["title"].lower().startswith("first day of school sign"), title["title"])
check("within Etsy's length limit", title["length"] <= 140, title["length"])
check("a supporting phrase already inside the lead is skipped",
      "first day of school sign" not in title["supporting"], title["supporting"])
# Repeating the lead's words in different orders is what reads as spam to a human and
# is what Etsy penalises — it is not a ranking trick.
check("personalized is surfaced", "Personalized" in title["title"], title["title"])

# --- assembled blueprint, and its warnings -------------------------------------------
data = {"volume": 172705, "supply": 64555, "cvr": 0.00244, "wow_change": -3.3,
        "price_low": 10.10, "price_high": 13.20}

bp = build("first day of school sign", data,
           {"consensus_tags": LIVE_TAGS, "all_confounded": True}, verdict_for,
           product_type="personalized")
warnings = " ".join(bp["warnings"])
check("under-filled tags warn", "13 tags had measured support" in warnings, warnings)
check("dropped over-long tags warn", "exceed Etsy's 20-char limit" in warnings, warnings)
check("confounded sources raise B-01", "B-01" in warnings, warnings)
check("the failing price reaches the blueprint", bp["price"]["price"] is None, bp["price"])
# The most winnable term on the board still fails the gate — offense finds it,
# defense stops it.

allcons = build("term", data,
                {"consensus_tags": [f"tag {i}" for i in range(20)]}, healthy)
check("an all-consensus tag set is called out",
      any("nothing they lack" in w for w in allcons["warnings"]), allcons["warnings"])
# Filling all 13 with what page one already ranks for is B-01 as a strategy: it lists
# you where the incumbents are strongest, with no differentiator.

check("the CTR checklist is always present", len(bp["ctr_checklist"]) >= 4)
# Tags win the impression; the photo and price win the click.

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
