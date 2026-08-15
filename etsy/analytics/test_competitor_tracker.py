"""Competitor outcomes: what they launched, and whether it worked (D-25).

Every refusal here is a case where a plausible number could be produced and would be
wrong. One sighting is a level, not a rate. Two readings an hour apart make rounding
the signal. A listing already present on the first sweep has no knowable age. Getting
any of these wrong produces a confident "validated winner" out of noise, which is
worse than showing nothing.

Offline — a fake db, no network.

    .venv/Scripts/python.exe -m etsy.analytics.test_competitor_tracker
"""
from etsy.analytics.competitor_tracker import (match_title_to_term, new_listings,
                                               observed_age_days, rank_by_outcome,
                                               review_velocity)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def obs(day, reviews, hour=0, basis="repeat_sighting", first_seen=None):
    ts = f"2026-08-{day:02d}T{hour:02d}:00:00+00:00"
    return {"listing_id": "L1", "collected_at": ts, "total_reviews": reviews,
            "sighting_basis": basis, "first_seen_at": first_seen or ts,
            "title": "Linen apron", "shop_name": "S"}


# --- the headline number ---------------------------------------------------------
v = review_velocity([obs(1, 4, basis="first_sighting"), obs(11, 16)])
check("measures reviews per day", v["velocity"] == 1.2, v)
check("basis is measured", v["basis"] == "measured", v)
check("reports the window", v["window_days"] == 10.0, v)
# Most buyers never review, so this is "at least this many sold" — never a sales count.
check("declares itself a lower bound", v["is_lower_bound"] is True, v)

# --- the refusals ----------------------------------------------------------------
v = review_velocity([obs(1, 4)])
check("one sighting is a level, not a rate", v["velocity"] is None, v)
check("and says so", v["basis"] == "insufficient_history", v)

v = review_velocity([obs(1, 4, hour=0), obs(1, 5, hour=6)])
check("a 6-hour window is refused", v["velocity"] is None, v)
check("window_too_short is named", v["basis"] == "window_too_short", v)
# 1 review over 6h would extrapolate to 4/day — a fabricated hit from rounding.

v = review_velocity([obs(1, None), obs(11, None)])
check("unparsed review counts are not zero", v["velocity"] is None, v)
check("treated as absent, not measured", v["basis"] == "insufficient_history", v)

v = review_velocity([obs(1, 10), obs(11, 8)])
check("a falling review count is refused", v["velocity"] is None, v)
check("counter_decreased is named", v["basis"] == "counter_decreased", v)
# Etsy removed a review, so the window is not a clean difference.

# A listing that gained nothing is a real, measured zero — not a refusal.
v = review_velocity([obs(1, 5), obs(11, 5)])
check("no growth is a measured zero", v["velocity"] == 0.0 and v["basis"] == "measured", v)

# --- age is observed, not known --------------------------------------------------
a = observed_age_days([obs(1, 2, basis="first_sighting"), obs(15, 9)])
check("age counts from first sighting", a["days"] == 14.0, a)
check("a watched-from-birth listing has a bounded age", a["age_is_bounded"] is True, a)

a = observed_age_days([obs(1, 200, basis="repeat_sighting"), obs(15, 210)])
check("a listing already present has NO knowable age", a["age_is_bounded"] is False, a)
# "Listed 3 weeks ago" is honest only when age_is_bounded is True; otherwise the
# listing is older than we can see, and calling it new invents the whole finding.

# --- title -> watched niche ------------------------------------------------------
watch = ["linen apron", "mom necklace", "necklace"]
check("a real title matches its niche",
      match_title_to_term("Reversible Linen Apron: No-Tie Organic European Flax", watch)
      == "linen apron")
# term_join.best_match demands exact word-set equality, so it could never fire here.

check("the most specific niche wins",
      match_title_to_term("Mom Necklace Gift for Her", watch) == "mom necklace")
# Not "necklace" — collapsing a narrow niche into a wide one is what D-17 guards.

check("a title matching nothing stays None",
      match_title_to_term("Ceramic Planter Pot", watch) is None)
check("an empty title is not forced into a niche",
      match_title_to_term("", watch) is None)
check("equally specific competing niches are refused",
      match_title_to_term("Gold Silver Ring", ["gold ring", "silver ring"]) is None)


# --- ranking, against a fake store -------------------------------------------------
class FakeDB:
    def __init__(self, rows, histories):
        self._rows, self._histories = rows, histories

    def tracked_listings(self, shop_name=None):
        return [r for r in self._rows
                if shop_name is None or r["shop_name"] == shop_name]

    def get_listing_history(self, listing_id):
        return self._histories.get(listing_id, [])


def row(lid, title, first_seen):
    return {"listing_id": lid, "title": title, "shop_name": "S",
            "first_seen_at": first_seen, "total_reviews": 0}


def hist(lid, a, b, basis="first_sighting"):
    return [{"listing_id": lid, "collected_at": "2026-08-01T00:00:00+00:00",
             "total_reviews": a, "sighting_basis": basis,
             "first_seen_at": "2026-08-01T00:00:00+00:00"},
            {"listing_id": lid, "collected_at": "2026-08-11T00:00:00+00:00",
             "total_reviews": b, "sighting_basis": "repeat_sighting",
             "first_seen_at": "2026-08-01T00:00:00+00:00"}]


db = FakeDB(
    rows=[row("fast", "Linen apron", "2026-08-01T00:00:00+00:00"),
          row("slow", "Mom necklace", "2026-08-01T00:00:00+00:00"),
          row("new", "Ceramic pot", "2026-08-12T00:00:00+00:00")],
    histories={"fast": hist("fast", 2, 42), "slow": hist("slow", 5, 6),
               "new": [{"listing_id": "new", "collected_at": "2026-08-12T00:00:00+00:00",
                        "total_reviews": 0, "sighting_basis": "first_sighting",
                        "first_seen_at": "2026-08-12T00:00:00+00:00"}]},
)
ranked = rank_by_outcome(db)
check("fastest-growing listing ranks first", ranked[0]["listing_id"] == "fast",
      [r["listing_id"] for r in ranked])
check("the unjudgeable listing is kept, not dropped",
      "new" in [r["listing_id"] for r in ranked], [r["listing_id"] for r in ranked])
check("and it sorts last with its reason",
      ranked[-1]["listing_id"] == "new"
      and ranked[-1]["velocity"]["basis"] == "insufficient_history", ranked[-1])
# Dropping it would hide the newest launches — exactly the ones worth seeing early.

fresh = new_listings(db, "S", since="2026-08-05T00:00:00+00:00")
check("new_listings finds only what appeared after the cutoff",
      [r["listing_id"] for r in fresh] == ["new"], [r["listing_id"] for r in fresh])

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
