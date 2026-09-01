import os
import json
import datetime


from etsy.api.public.api import EtsyPublicAPI
from etsy.api.public.listing_api import get_listing_data
from etsy.api.public.reviews_api import get_recent_reviews
from core.shop_scraper import ShopScraper
from core.database import MarketDatabase
from etsy.analytics.derivations import estimate_sales, estimate_views
from core.runlog import logged_stage

def parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%b %d, %Y")
    except ValueError:
        return None

class SingleListingPipeline:
    def __init__(self, listing_id, cvr=0.02, cvr_source="default"):
        self.listing_id = str(listing_id)
        self.cvr = cvr
        # Where the conversion rate came from. Views are derived by dividing by it, so a
        # measured CVR and the 0.02 assumption produce numbers of very different quality
        # that used to be stored identically. Callers with a real CVR pass "measured".
        self.cvr_source = cvr_source
        self.api = EtsyPublicAPI()
        self.shop_scraper = ShopScraper(self.api)
        # One handle for the run: read (the measured shop rate, for the B-03 clamp) and
        # write (the observation) previously constructed two separate connections.
        self.db = MarketDatabase()
        
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.seo_cache, exist_ok=True)
        
    @logged_stage("single_listing_analytics")
    def run(self):
        print(f"\n==========================================================")
        print(f"      STARTING SINGLE LISTING PIPELINE: {self.listing_id}")
        print(f"==========================================================")
        
        # 1. Scrape Listing HTML for basics
        print(f"\n[PHASE 1] Scraping Listing HTML...")
        listing_data = get_listing_data(self.listing_id, self.api)
        if not listing_data:
            print("[-] Failed to scrape listing page.")
            return
            
        shop_name = listing_data.get('shop_name', 'Unknown')
        shop_id = listing_data.get('shop_id')
        favorites = listing_data.get('favorites', 0)
        in_cart = listing_data.get('in_cart', 0)
        exact_review_count = listing_data.get('exact_review_count', 0)
        rating_value = listing_data.get('rating_value', 0.0)
        price = listing_data.get('price', 0.0)
        csrf = listing_data.get('csrf_token')
        demand_signals = listing_data.get('demand_signals', [])
        
        # N-02: None means the badge was absent, i.e. unmeasured — NOT zero demand.
        # Defaulting to 0 put "we couldn't see it" and "nothing sold" on the same path.
        daily_sales = listing_data.get('daily_sales')
        daily_views = listing_data.get('daily_views')
        scarcity_stock = listing_data.get('scarcity_stock')
        
        print(f"[+] Found Shop: {shop_name}")
        print(f"[+] Listing Price: ${price:.2f}")
        print(f"[+] Listing Exact Reviews: {exact_review_count}")
        print(f"[+] Favorites: {favorites}")
        print(f"[+] In Cart: {in_cart}")
        
        if demand_signals:
            print("\n[!] LIVE DEMAND SIGNALS DETECTED:")
            for sig in demand_signals:
                print(f"    -> 🔥 {sig}")
            if daily_sales: print(f"    [Parsed] Daily Sales Velocity: {daily_sales}")
            if daily_views: print(f"    [Parsed] Daily Views Velocity: {daily_views}")
            if scarcity_stock: print(f"    [Parsed] Scarcity Stock Left: {scarcity_stock}")
        
        # 2. Scrape Shop Data for Ratio Estimator
        print(f"\n[PHASE 2] Scraping Shop Data...")
        shop_metrics = None
        if shop_name and shop_name != 'Unknown':
            shop_metrics = self.shop_scraper.get_shop_metrics(shop_name)
            
        # 3. Scrape Reviews for Velocity
        print(f"\n[PHASE 3] Fetching Review Velocity...")
        recent_dates = get_recent_reviews(self.listing_id, public_api=self.api, target_shop_id=shop_id, csrf_token=csrf)
        total_reviews = len(recent_dates) # We don't have the exact listing review count unless we parse it. We'll use shop ratio against something, or just use velocity.
        
        # 4. Calculate final stats & Exact Estimation
        print(f"\n[PHASE 4] Calculating Market Report...")
        
        # Exact Sales Estimation Math (LD+JSON Upgrade)
        shop_total_sales = shop_metrics.get('total_sales', 0) if shop_metrics else 0
        shop_total_reviews = shop_metrics.get('total_reviews', 0) if shop_metrics else 0
        
        sales_ratio = 0.0
        if shop_total_reviews > 0:
            sales_ratio = shop_total_sales / shop_total_reviews
            
        # B-03: the badge is a measurement *conditioned on its own value* — it renders
        # only above a platform threshold — so it is an upper bound, not the display
        # figure it used to be. shop_sales_per_day clamps a badge claiming more than the
        # whole shop sells; None means this shop was never tracked, so nothing clamps.
        est = estimate_sales(
            review_count=exact_review_count,
            shop_total_sales=shop_total_sales,
            shop_total_reviews=shop_total_reviews,
            daily_sales=daily_sales,
            shop_sales_per_day=self.db.latest_shop_rate(shop_name) if shop_name else None,
        )
        sales_lifetime_est, sales_30d_est = est.lifetime, est.thirty_day
        listing_estimated_sales, sales_basis = est.chosen, est.basis
        if est.note:
            print(f"[!] {est.note}")
        if est.is_upper_bound:
            print(f"[!] No shop ratio available — the sales figure below is an UPPER "
                  f"BOUND derived from the badge, not a best estimate.")
        estimated_revenue = listing_estimated_sales * price
        estimated_views, views_basis = estimate_views(
            listing_estimated_sales, daily_views, self.cvr, self.cvr_source)
        
        velocity_score = "DEAD 💀"
        days_since_last = -1
        
        parsed_dates = [parse_date(d) for d in recent_dates if parse_date(d)]
        if parsed_dates:
            parsed_dates.sort(reverse=True)
            newest = parsed_dates[0]
            days_since_last = (datetime.datetime.now() - newest).days
            
            if days_since_last <= 7:
                velocity_score = "HOT 🔥"
            elif days_since_last <= 30:
                velocity_score = "STEADY 📈"
            else:
                velocity_score = "SLOW 🐢"
                
        result = {
            "listing_id": self.listing_id,
            "shop_name": shop_name,
            "favorites": favorites,
            "in_cart": in_cart,
            "exact_review_count": exact_review_count,
            "rating": rating_value,
            "price": price,
            "estimated_views": estimated_views,
            "estimated_sales": listing_estimated_sales,
            "estimated_revenue": estimated_revenue,
            "velocity": velocity_score,
            "days_since_last_review": days_since_last,
            "shop_total_sales": shop_total_sales,
            "shop_total_reviews": shop_total_reviews,
            "demand_signals": demand_signals,
            "daily_sales_velocity": daily_sales,
            "daily_views_velocity": daily_views,
            "scarcity_stock": scarcity_stock
        }
        
        report_path = os.path.join(self.seo_cache, f"single_report_{self.listing_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        print(f"[+] Final Report cached to: {report_path}")
        
        # --- SAVE TO MARKET INTELLIGENCE DB ---
        # Appends one observation. record_listing carries the provenance the old
        # upsert_listing_metrics could not express, so a reader can tell a measured price
        # from a twice-derived view count.
        collected_at = self.db.record_listing(
            listing_id=self.listing_id,
            shop_name=shop_name,
            price=price,
            sales_lifetime_est=sales_lifetime_est,
            sales_30d_est=sales_30d_est,
            sales_basis=sales_basis,
            estimated_views=estimated_views,
            views_basis=views_basis,
            velocity_score=velocity_score,
            daily_sales=daily_sales,
            daily_views=daily_views,
            scarcity_stock=scarcity_stock,
            # An empty signal list means no urgency badge was rendered, which is why the
            # daily_* fields are 0 — not evidence that nothing sold.
            badge_present=bool(demand_signals),
            demand_signals=demand_signals,
            total_reviews=exact_review_count,
        )
        print(f"[+] Recorded observation for {self.listing_id} at {collected_at}")
        print(f"    sales basis: {sales_basis} | views basis: {views_basis}")
        
        print("\n\n=======================================================================================================================================")
        print(f"                               SINGLE LISTING REPORT: {self.listing_id}")
        print("======================================================================================================================================================")
        print(f"{'Listing ID':<12} | {'Shop':<18} | {'Views (Est)':<12} | {'Sales (Est)':<12} | {'Revenue ($)':<12} | {'Velocity':<10} | {'Favs':<8} | {'Cart':<5} | {'Reviews':<7} | {'Stars':<5}")
        print("-" * 150)
        revenue_str = f"${result['estimated_revenue']:,.2f}"
        print(f"{result['listing_id']:<12} | {result['shop_name'][:18]:<18} | {result['estimated_views']:<12,} | {result['estimated_sales']:<12,} | {revenue_str:<12} | {result['velocity']:<10} | {result['favorites']:<8,} | {result['in_cart']:<5} | {result['exact_review_count']:<7} | {result['rating']:<5}")
        print("======================================================================================================================================================\n")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run the Single Listing Analytics Pipeline.")
    parser.add_argument("--id", type=str, default="1238067877", help="The listing ID.")
    parser.add_argument("--cvr", type=float, default=0.02, help="Exact CVR from Private API.")
    args = parser.parse_args()
    
    pipeline = SingleListingPipeline(args.id, cvr=args.cvr)
    pipeline.run()
