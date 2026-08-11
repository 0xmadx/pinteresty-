"""Offline tests for the sales/views derivations. No network, no database.

This is the first test covering any code under `etsy/`. It exists because these four
functions produce the numbers the entire product ranks on, and until they were extracted
from the pipelines the only way to exercise them was to make live requests.

Run:  python -m etsy.analytics.test_derivations
"""
import sys

from etsy.analytics.derivations import (BASIS_VALUES, estimate_sales, estimate_views,
                                        sales_ratio, velocity_from_days)

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
    # --- sales_ratio ------------------------------------------------------------------
    check("ratio: 5000 sales / 1000 reviews = 5.0", sales_ratio(5000, 1000) == 5.0)
    check("ratio: no reviews yields None, not 0.0 that would zero every estimate",
          sales_ratio(5000, 0) is None)
    check("ratio: no sales yields None", sales_ratio(0, 1000) is None)

    # --- estimate_sales ---------------------------------------------------------------
    e = estimate_sales(review_count=200, shop_total_sales=5000, shop_total_reviews=1000)
    check("sales: 200 reviews x ratio 5.0 = 1000 lifetime",
          e.lifetime == 1000 and e.chosen == 1000 and e.basis == "review_ratio",
          f"got {e.lifetime}/{e.chosen}/{e.basis}")
    check("sales: no badge means no 30-day figure", e.thirty_day is None)
    check("sales: a ratio estimate is a point estimate, not a bound",
          e.is_upper_bound is False)

    # B-03: the badge only renders above a platform threshold, so it is observed only
    # on above-threshold days. It is a CEILING, and must not displace the point estimate.
    e = estimate_sales(review_count=200, shop_total_sales=5000, shop_total_reviews=1000,
                       daily_sales=18)
    check("B-03: the badge yields a 30-day UPPER BOUND, not a point estimate",
          e.thirty_day == 540 and e.thirty_day_is_bound is True,
          f"got {e.thirty_day}/{e.thirty_day_is_bound}")
    check("B-03: the badge no longer displaces the ratio for display",
          e.chosen == 1000 and e.basis == "review_ratio",
          f"got chosen={e.chosen} basis={e.basis}")
    check("sales: the badge does NOT destroy the lifetime estimate",
          e.lifetime == 1000, f"got {e.lifetime}")

    # With no shop ratio there is no point estimate at all — only a ceiling. Returning
    # it is fine; pretending it is a midpoint is not.
    e = estimate_sales(review_count=200, daily_sales=18)
    check("B-03: with only a badge, the ceiling is used but flagged as one",
          e.chosen == 540 and e.is_upper_bound is True
          and e.basis == "daily_badge_x30_upper_bound",
          f"got chosen={e.chosen} bound={e.is_upper_bound} basis={e.basis}")

    # The calibration B-03 asks for: a single listing cannot outsell its whole shop.
    # shop_sales_per_day comes from the measured daily delta (shop_observations).
    e = estimate_sales(review_count=200, daily_sales=18, shop_sales_per_day=4.0)
    check("B-03: a badge implying more than the SHOP sells is clamped to the shop rate",
          e.thirty_day == 120 and e.basis == "daily_badge_x30_clamped_to_shop",
          f"got {e.thirty_day}/{e.basis}")
    check("B-03: the clamp says why, so the number is not silently altered",
          "exceeds" in e.note.lower(), f"got {e.note!r}")
    check("B-03: a badge within the shop's measured rate is left alone",
          estimate_sales(review_count=200, daily_sales=3,
                         shop_sales_per_day=40.0).thirty_day == 90)
    check("B-03: an unmeasured shop rate does not clamp — None is not zero",
          estimate_sales(review_count=200, daily_sales=18,
                         shop_sales_per_day=None).thirty_day == 540)

    e = estimate_sales(review_count=200, daily_sales=0)
    check("sales: no shop data and no badge reports 'absent', not a fabricated 0",
          e.lifetime is None and e.thirty_day is None and e.basis == "absent",
          f"got {e.lifetime}/{e.thirty_day}/{e.basis}")
    check("sales: daily_sales=0 means 'no badge rendered', never a 0-sales claim",
          estimate_sales(review_count=200, daily_sales=0).thirty_day is None)

    # --- estimate_views ---------------------------------------------------------------
    views, basis = estimate_views(sales=540, daily_views=1200)
    check("views: a live views badge is a measurement and wins",
          views == 36000 and basis == "daily_views_x30", f"got {views}/{basis}")

    views, basis = estimate_views(sales=1000, daily_views=0, cvr=0.02, cvr_source="default")
    check("views: falling back to CVR records that the CVR was assumed",
          views == 50000 and basis == "sales_div_cvr_default", f"got {views}/{basis}")

    views, basis = estimate_views(sales=1000, daily_views=0, cvr=0.031, cvr_source="measured")
    check("views: a measured CVR is recorded differently from the default",
          views == 32258 and basis == "sales_div_cvr_measured", f"got {views}/{basis}")

    views, basis = estimate_views(sales=0, daily_views=0)
    check("views: nothing to divide reports 'absent'", views == 0 and basis == "absent")

    # --- velocity ---------------------------------------------------------------------
    check("velocity: 3 days -> HOT", velocity_from_days(3)[0].startswith("HOT"))
    check("velocity: 20 days -> STEADY", velocity_from_days(20)[0].startswith("STEADY"))
    check("velocity: 90 days -> SLOW", velocity_from_days(90)[0].startswith("SLOW"))
    check("velocity: no reviews found -> DEAD with basis 'absent'",
          velocity_from_days(-1)[0].startswith("DEAD") and velocity_from_days(-1)[1] == "absent")
    check("velocity: None is handled like no data", velocity_from_days(None)[0].startswith("DEAD"))

    # --- the vocabulary is closed -----------------------------------------------------
    produced = {
        estimate_sales(200, 5000, 1000).basis,
        estimate_sales(200, 5000, 1000, 18).basis,
        estimate_sales(200, daily_sales=18).basis,
        estimate_sales(200, daily_sales=18, shop_sales_per_day=1.0).basis,
        estimate_sales(200).basis,
        estimate_views(540, 1200)[1],
        estimate_views(1000, 0, 0.02, "default")[1],
        estimate_views(1000, 0, 0.031, "measured")[1],
        estimate_views(0, 0)[1],
    }
    check("every basis produced is in the documented vocabulary",
          produced <= BASIS_VALUES, f"stray: {produced - BASIS_VALUES}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
