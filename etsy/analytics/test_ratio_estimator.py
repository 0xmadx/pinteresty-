"""Offline tests for the ratio estimator. No network; a temp database.

The module used to scan `public/data/raw/` — a directory that has never existed — so it
returned None on every call. These tests pin the rewritten version against the database,
and pin the three refusals that keep it from inventing a number.

Run:  python -m etsy.analytics.test_ratio_estimator
"""
import os
import sys
import tempfile

from core.database import MarketDatabase
from etsy.analytics.ratio_estimator import estimate_listing_sales

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
    db = MarketDatabase(db_path=os.path.join(tempfile.mkdtemp(), "m.db"))

    # A listing observed with 40 reviews, in a shop measured at 5000 sales / 1000 reviews.
    db.record_listing(listing_id="111", shop_name="ShopA", price=24.0, total_reviews=40)
    db.record_shop_observation("ShopA", total_sales=5000, total_reviews=1000,
                               collected_at="2026-08-01T00:00:00+00:00")

    r = estimate_listing_sales("111", db=db)
    check("a stored listing + stored shop yields an estimate with NO network",
          r is not None and r["shop_source"] == "shop_observations", f"got {r}")
    check("ratio 5000/1000 = 5.0", r["ratio"] == 5.0, f"got {r['ratio']}")
    check("40 reviews x 5.0 = 200 estimated lifetime sales",
          r["estimated_sales"] == 200, f"got {r['estimated_sales']}")
    check("the estimate carries its basis, so it is never mistaken for measured",
          r["basis"] == "review_ratio", f"got {r['basis']}")

    # --- the three refusals ---------------------------------------------------------------
    print()
    check("an unobserved listing returns None rather than guessing",
          estimate_listing_sales("does-not-exist", db=db) is None)

    # A listing with NO recorded review count must not be treated as zero reviews —
    # that would report "0 estimated sales", a confident wrong answer.
    db.record_listing(listing_id="222", shop_name="ShopA", price=10.0, total_reviews=None)
    check("a listing with an unmeasured review count yields None, not 0 sales",
          estimate_listing_sales("222", db=db) is None)

    # A shop with zero reviews has no ratio.
    db.record_listing(listing_id="333", shop_name="DeadShop", price=10.0, total_reviews=5)
    db.record_shop_observation("DeadShop", total_sales=0, total_reviews=0,
                               collected_at="2026-08-01T00:00:00+00:00")

    class NoScrape:
        def get_shop_metrics(self, name):
            return None

    import etsy.analytics.ratio_estimator as mod
    original = mod.ShopScraper
    mod.ShopScraper = lambda api: NoScrape()
    try:
        check("a shop with no usable metrics yields None",
              estimate_listing_sales("333", db=db, public_api=object()) is None)
    finally:
        mod.ShopScraper = original

    # --- a genuinely zero-review listing is distinct from an unmeasured one ---------------
    print()
    db.record_listing(listing_id="444", shop_name="ShopA", price=10.0, total_reviews=0)
    r = estimate_listing_sales("444", db=db)
    check("a listing measured at 0 reviews is handled without crashing",
          r is None or r["estimated_sales"] in (0, None), f"got {r}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
