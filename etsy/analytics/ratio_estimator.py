"""
ratio_estimator.py

Layer: analytics/ (I/O — reads the market database, scrapes a shop page only if needed)
Purpose: estimate one listing's lifetime sales from its shop's sales-to-reviews ratio.

Key decision: this reads the DATABASE, not a directory of raw SERP dumps. The
previous version scanned `public/data/raw/` for `public_search_*.json` — a directory
that has never existed in this repo, for files that no longer exist on disk (the
SERP cache now lives in request_cache.db). It therefore returned None on every call,
at line 43, always. Nothing called it, so nothing noticed.

It also duplicated the ratio arithmetic that `derivations.sales_ratio` /
`estimate_sales` own, which is the code B-06 is about — so a fix there would not
have reached this copy.

⚠️ B-06 (uniform review propensity): this ratio assumes every product in a shop is
reviewed at the same rate. A $12 sticker and a $200 custom piece are not. The result
carries `basis="review_ratio"` and should be treated as the weakest sales estimate
available — prefer the measured daily delta (`shop_observations.sales_per_day`)
wherever it exists.
"""
from core.database import MarketDatabase
from core.runlog import logged_stage
from core.shop_scraper import ShopScraper
from etsy.analytics.derivations import estimate_sales, sales_ratio
from etsy.api.public.api import EtsyPublicAPI


@logged_stage("ratio_estimator")
def estimate_listing_sales(listing_id, public_api=None, db=None):
    """Estimate a listing's lifetime sales. Returns None when it cannot be computed.

    Receives: a listing_id that must already have been observed (grid_analytics or
              single_listing_analytics writes it to listing_observations).
    Emits: {listing_id, shop_name, ratio, estimated_sales, basis, shop_source} or None.

    Refuses rather than guesses at three points: an unobserved listing, a listing whose
    review count was never captured, and a shop with no reviews to divide by. The old
    version defaulted a missing review count to 0, which silently produced "0 estimated
    sales" — a confident wrong answer rather than an absent one.
    """
    db = db or MarketDatabase()

    listing = db.get_listing(listing_id)
    if not listing:
        print(f"[-] Listing {listing_id} has never been observed. Run grid_analytics or "
              f"single_listing_analytics on it first.")
        return None

    shop_name = listing.get("shop_name")
    listing_review_count = listing.get("total_reviews")
    if not shop_name:
        print(f"[-] Listing {listing_id} was observed but carries no shop name.")
        return None
    if listing_review_count is None:
        # Not the same as zero reviews. A listing nobody has reviewed yields no ratio
        # estimate at all; a listing whose count we failed to read must not be reported
        # as having sold nothing.
        print(f"[-] Listing {listing_id} has no recorded review count — unmeasured, "
              f"which is not the same as zero. No estimate.")
        return None

    # Prefer the stored shop observation: it is already measured, and it costs no
    # request. Only scrape when this shop has never been tracked.
    shop = db.latest_shop_observation(shop_name)
    shop_source = "shop_observations"
    if not shop or not shop.get("total_sales") or not shop.get("total_reviews"):
        shop_source = "scraped"
        public_api = public_api or EtsyPublicAPI()
        shop = ShopScraper(public_api).get_shop_metrics(shop_name)

    if not shop or not shop.get("total_sales") or not shop.get("total_reviews"):
        print(f"[-] No usable shop metrics for '{shop_name}' — cannot form a ratio.")
        return None

    ratio = sales_ratio(shop["total_sales"], shop["total_reviews"])
    if ratio is None:
        print(f"[-] Shop '{shop_name}' has no reviews to divide by.")
        return None

    # The shared derivation, so a fix to the sales maths reaches this caller too.
    est = estimate_sales(review_count=listing_review_count,
                         shop_total_sales=shop["total_sales"],
                         shop_total_reviews=shop["total_reviews"])

    if est.lifetime is None:
        # A listing with zero reviews has no ratio estimate: reviews are the only input
        # this method has. Reporting 0 sales would be a claim, not a measurement — the
        # listing may simply be new.
        print(f"[-] Listing {listing_id} has {listing_review_count} review(s); the ratio "
              f"method needs at least one. No estimate — this is not a claim of 0 sales.")
        return None

    print("\n--- Estimated Sales Report ---")
    print(f"Shop: {shop_name}  (metrics from {shop_source})")
    print(f"Shop Total Sales: {shop['total_sales']:,}")
    print(f"Shop Total Reviews: {shop['total_reviews']:,}")
    print(f"Shop Sales-to-Review Ratio: {ratio:.2f} (1 review = {ratio:.2f} sales)")
    print(f"Listing ID: {listing_id}")
    print(f"Listing Reviews: {listing_review_count:,}")
    print(f"Estimated Listing Sales: {est.lifetime:,}  [basis={est.basis}]")
    print(f"⚠️  Assumes every product in this shop is reviewed at the same rate (B-06). "
          f"The measured daily delta is a stronger signal where available.")
    print("------------------------------\n")

    return {
        "listing_id": listing_id,
        "shop_name": shop_name,
        "ratio": ratio,
        "estimated_sales": est.lifetime,
        "basis": est.basis,
        "shop_source": shop_source,
    }


if __name__ == "__main__":
    import sys
    estimate_listing_sales(sys.argv[1] if len(sys.argv) > 1 else "4502693975")
