"""Guard test for the append-only trends handoff. No network, no real database.

MIGRATION_AND_OPERATIONS.md:43 specifies exactly this test for the temporal fix:
"ingest twice, assert two rows, assert the original is intact."

That property is the whole reason the table exists in this shape. If it ever regresses to
an upsert, a backtest silently evaluates predictions against inputs that were never used
(DECISION_LOG.md D-04), and nothing else in the system would notice.

Run:  python -m pinterest.tests.test_trends_bridge
"""
import os
import sys
import tempfile

from core.database import MarketDatabase

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
    tmp = os.path.join(tempfile.mkdtemp(prefix="trends_guard_"), "test.db")
    db = MarketDatabase(db_path=tmp)
    print(f"temp db: {tmp}\n")

    # --- the guard: two observations of the same trend --------------------------------
    db.record_trend(
        trend_name="coquette room decor", source="pinterest_featured_topics",
        collected_at="2026-08-01T00:00:00+00:00",
        dominant_color="#e0a0c0", color_share=0.42, color_basis="measured",
        demographic={"dominant_age": "18-24", "mean_age": 24.5, "female_share": 0.81},
        demographic_basis="measured",
        takeoff_timestamp="2026-09-15", list_by="2026-08-04", takeoff_basis="measured",
        growth_mom=0.75, velocity=0.31, velocity_basis="derived",
    )
    db.record_trend(
        trend_name="coquette room decor", source="pinterest_featured_topics",
        collected_at="2026-08-08T00:00:00+00:00",
        dominant_color="#d090b8", color_share=0.51, color_basis="measured",
        demographic={"dominant_age": "25-34", "mean_age": 27.1, "female_share": 0.78},
        demographic_basis="measured",
        takeoff_timestamp="2026-09-15", list_by="2026-08-04", takeoff_basis="measured",
        growth_mom=0.92, velocity=0.44, velocity_basis="derived",
    )

    history = db.get_trend_history("coquette room decor")
    check("ingesting twice yields two rows", len(history) == 2, f"got {len(history)}")

    first = history[0] if history else {}
    check("the original observation is intact",
          first.get("collected_at") == "2026-08-01T00:00:00+00:00"
          and first.get("dominant_color") == "#e0a0c0"
          and first.get("growth_mom") == 0.75,
          f"got {first.get('collected_at')} / {first.get('dominant_color')} / {first.get('growth_mom')}")

    check("history is ordered oldest first",
          len(history) == 2 and history[0]["collected_at"] < history[1]["collected_at"])

    # --- current-state read -----------------------------------------------------------
    latest = db.get_trend("coquette room decor")
    check("get_trend returns the newest observation",
          latest and latest.get("collected_at") == "2026-08-08T00:00:00+00:00",
          f"got {latest and latest.get('collected_at')}")
    check("get_trend keeps the legacy field names master_arbitrage reads",
          latest and "dominant_color" in latest and "takeoff_timestamp" in latest)
    check("demographic round-trips as a dict, not a JSON string",
          isinstance(latest.get("demographic"), dict)
          and latest["demographic"].get("dominant_age") == "25-34",
          f"got {type(latest.get('demographic')).__name__}")

    # --- provenance -------------------------------------------------------------------
    check("measured/derived basis survives the round trip",
          latest.get("color_basis") == "measured"
          and latest.get("velocity_basis") == "derived",
          f"got {latest.get('color_basis')} / {latest.get('velocity_basis')}")

    # --- absent is distinguishable from zero ------------------------------------------
    db.record_trend(trend_name="bare trend", source="pinterest_featured_topics",
                    collected_at="2026-08-08T00:00:00+00:00",
                    color_basis="absent", demographic_basis="absent", takeoff_basis="absent")
    bare = db.get_trend("bare trend")
    check("a trend with no colour records 'absent', not a fake value",
          bare and bare.get("dominant_color") is None and bare.get("color_basis") == "absent",
          f"got {bare and bare.get('dominant_color')} / {bare and bare.get('color_basis')}")

    # --- isolation --------------------------------------------------------------------
    check("country is part of the key, so US and GB do not collide",
          db.record_trend(trend_name="coquette room decor", source="pinterest_featured_topics",
                          country="GB", collected_at="2026-08-08T00:00:00+00:00",
                          dominant_color="#112233") is not None
          and len(db.get_trend_history("coquette room decor", country="GB")) == 1
          and len(db.get_trend_history("coquette room decor", country="US")) == 2)

    check("unknown trend returns None rather than an empty row",
          db.get_trend("no such trend") is None)

    # --- keywords: same guard, and the cvr provenance flag ----------------------------
    print()
    db.record_keyword("mom necklace", collected_at="2026-08-01T00:00:00+00:00",
                      volume=12000, competition=48000, cvr=0.031, cvr_source="measured",
                      price_low=18.0, price_high=42.0)
    db.record_keyword("mom necklace", collected_at="2026-08-08T00:00:00+00:00",
                      volume=15500, competition=51000, cvr=0.02, cvr_source="default",
                      price_low=19.0, price_high=44.0)

    kh = db.get_keyword_history("mom necklace")
    check("keywords: two ingests, two rows", len(kh) == 2, f"got {len(kh)}")
    check("keywords: the first observation survives",
          kh and kh[0]["search_volume"] == 12000 and kh[0]["query_cvr"] == 0.031)
    check("keywords: a measured CVR and a defaulted one are distinguishable",
          kh[0]["cvr_source"] == "measured" and kh[1]["cvr_source"] == "default")
    check("keywords: get_keyword returns the latest with legacy field names",
          (lambda k: k and k["search_volume"] == 15500 and "query_cvr" in k
           and "median_price_low" in k)(db.get_keyword("mom necklace")))

    # The old signature must keep working — private_blueprint.py:93 still calls it.
    db.upsert_keyword("legacy kw", 100, 200, 0.02, 5.0, 9.0)
    lk = db.get_keyword("legacy kw")
    check("keywords: legacy upsert_keyword still works and now appends",
          lk and lk["search_volume"] == 100 and lk["cvr_source"] == "unspecified",
          f"got {lk and lk.get('cvr_source')}")

    # --- listings: the split that removes the ambiguous column -------------------------
    print()
    db.record_listing("4502693975", collected_at="2026-08-01T00:00:00+00:00",
                      shop_name="ExampleShop", price=34.0,
                      sales_lifetime_est=812, sales_basis="review_ratio",
                      estimated_views=40600, views_basis="derived_from_cvr_default",
                      velocity_score="STEADY", daily_sales=0, badge_present=False,
                      total_reviews=203)
    db.record_listing("4502693975", collected_at="2026-08-08T00:00:00+00:00",
                      shop_name="ExampleShop", price=31.5,
                      sales_30d_est=540, sales_basis="daily_badge_x30",
                      estimated_views=16200, views_basis="measured_daily_views",
                      velocity_score="HOT", daily_sales=18, badge_present=True,
                      total_reviews=209)

    lh = db.get_listing_history("4502693975")
    check("listings: two ingests, two rows", len(lh) == 2, f"got {len(lh)}")
    check("listings: the first observation survives intact",
          lh and lh[0]["price"] == 34.0 and lh[0]["sales_lifetime_est"] == 812)
    check("listings: lifetime and 30-day estimates occupy different columns",
          lh[0]["sales_lifetime_est"] == 812 and lh[0]["sales_30d_est"] is None
          and lh[1]["sales_30d_est"] == 540 and lh[1]["sales_lifetime_est"] is None)
    check("listings: each sales figure records how it was produced",
          lh[0]["sales_basis"] == "review_ratio" and lh[1]["sales_basis"] == "daily_badge_x30")
    check("listings: badge_present disambiguates a zero from a missing badge",
          lh[0]["daily_sales"] == 0 and lh[0]["badge_present"] == 0
          and lh[1]["badge_present"] == 1)

    # Flaws are LLM output and must not fabricate a metrics row for an unseen listing.
    db.upsert_listing_flaws("9999999999", "- clasp breaks\n- smaller than advertised")
    check("listings: flaws for an unobserved listing do not invent a metrics row",
          db.get_listing("9999999999") is None)

    db.upsert_listing_flaws("4502693975", "- clasp breaks")
    joined = db.get_listing("4502693975")
    check("listings: get_listing joins the latest flaws and keeps legacy keys",
          joined and joined["top_flaws"] == "- clasp breaks"
          and joined["estimated_sales"] == 540 and joined["price"] == 31.5,
          f"got {joined and joined.get('estimated_sales')}")

    db.upsert_listing_metrics("7777777777", "Shop2", 12.0, 300, 15000, "SLOW")
    check("listings: legacy upsert_listing_metrics still works and now appends",
          (lambda l: l and l["sales_lifetime_est"] == 300
           and l["sales_basis"] == "unspecified")(db.get_listing("7777777777")))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
