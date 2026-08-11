import os
import json
import datetime
import argparse
from pathlib import Path


from etsy.api.public.api import EtsyPublicAPI
from core.shop_scraper import ShopScraper
from etsy.api.public.listing_api import get_listing_data
from etsy.api.public.reviews_api import get_recent_reviews
from core.database import MarketDatabase
from etsy.analytics.derivations import estimate_sales, estimate_views
from core import runlog
from core.runlog import logged_stage

def parse_date(date_str):
    try:
        return datetime.datetime.strptime(date_str, "%b %d, %Y")
    except ValueError:
        return None

class GridAnalyticsPipeline:
    def __init__(self, query, filters=None, max_listings=10, cvr=0.02):
        self.query = query
        self.filters = filters or {}
        self.max_listings = max_listings
        self.cvr = cvr
        
        self.api = EtsyPublicAPI()
        self.shop_scraper = ShopScraper(self.api)
        self.db = MarketDatabase()
        
        # Override CVR if it exists in the database. Track where it came from: views are
        # derived by dividing by this, so a measured CVR and the 0.02 fallback yield
        # numbers of very different quality.
        self.cvr_source = "default"
        db_keyword = self.db.get_keyword(self.query)
        if db_keyword and db_keyword.get("query_cvr"):
            self.cvr = db_keyword["query_cvr"]
            # The stored row records whether *it* was measured; inherit that rather than
            # assuming a database hit means a real measurement.
            self.cvr_source = db_keyword.get("cvr_source") or "measured"
            print(f"[*] Pulled CVR ({self.cvr}, source={self.cvr_source}) from Market Database for '{self.query}'")
        else:
            print(f"[*] No stored CVR for '{self.query}' — using default {self.cvr}")
        
        # Setup cache directories
        self.raw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "public", "data", "raw")
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.seo_cache, exist_ok=True)
        
        self.query_slug = self.query.replace(' ', '_')
        
    @logged_stage("grid_analytics")
    def run(self):
        print(f"\n==========================================================")
        print(f"      STARTING GRID ANALYTICS PIPELINE: '{self.query.upper()}'")
        print(f"==========================================================")
        
        # --- PHASE 1: Grid Extraction ---
        print("\n[PHASE 1] Extracting Grid...")
        grid_data = self.api.get_public_search(self.query, filters=self.filters)
        if not grid_data or not grid_data.get('cards'):
            print("[-] Failed to fetch grid data or no cards found.")
            return
            
        cards = grid_data['cards'][:self.max_listings]
        print(f"[+] Extracted top {len(cards)} listings.")
        
        # Extract unique shops
        unique_shops = set()
        for card in cards:
            if card.get('shop_name'):
                unique_shops.add(card.get('shop_name'))
                
        print(f"[+] Found {len(unique_shops)} unique shops.")
        
        # --- PHASE 2: Batch Shop Scraping ---
        print("\n[PHASE 2] Batch Scraping Shop Data...")
        shop_database = {}
        batch_shops_path = os.path.join(self.raw_dir, f"batch_shops_{self.query_slug}.json")
        
        for shop in unique_shops:
            print(f"  -> Scraping Shop: {shop}")
            metrics = self.shop_scraper.get_shop_metrics(shop)
            if metrics:
                shop_database[shop] = metrics
                
        # Save Phase 2 State
        with open(batch_shops_path, "w", encoding="utf-8") as f:
            json.dump(shop_database, f, indent=4)
        print(f"[+] Shop data cached to: {batch_shops_path}")
        
        # --- PHASE 3: Listing Velocity ---
        print("\n[PHASE 3] Fetching Review Velocities...")
        velocity_database = {}
        batch_reviews_path = os.path.join(self.raw_dir, f"batch_reviews_{self.query_slug}.json")
        
        for card in cards:
            lid = card.get('listing_id')
            if not lid:
                continue
                
            print(f"  -> Scraping Listing Page: {lid}")
            listing_data = get_listing_data(lid, self.api)
            
            recent_dates = []
            favorites = 0
            in_cart = 0
            daily_sales = 0
            daily_views = 0
            scarcity = 0
            demand_sigs = []
            
            if listing_data:
                favorites = listing_data.get('favorites', 0)
                in_cart = listing_data.get('in_cart', 0)
                daily_sales = listing_data.get('daily_sales', 0)
                daily_views = listing_data.get('daily_views', 0)
                scarcity = listing_data.get('scarcity_stock', 0)
                demand_sigs = listing_data.get('demand_signals', [])
                shop_id = listing_data.get('shop_id')
                csrf_token = listing_data.get('csrf_token')
                
                print(f"  -> Fetching Reviews for Listing: {lid}")
                recent_dates = get_recent_reviews(lid, public_api=self.api, shop_id=shop_id, csrf_token=csrf_token)
                
            velocity_database[str(lid)] = {
                "recent_dates": recent_dates,
                "favorites": favorites,
                "in_cart": in_cart,
                "daily_sales": daily_sales,
                "daily_views": daily_views,
                "scarcity_stock": scarcity,
                "demand_signals": demand_sigs
            }
            
        # Save Phase 3 State
        with open(batch_reviews_path, "w", encoding="utf-8") as f:
            json.dump(velocity_database, f, indent=4)
        print(f"[+] Velocity data cached to: {batch_reviews_path}")
        
        # --- PHASE 4: The Calculator ---
        print("\n[PHASE 4] Calculating Market Report...")
        results = []
        
        for i, card in enumerate(cards):
            lid = card.get('listing_id')
            shop_name = card.get('shop_name')
            review_count = card.get('review_count', 0)
            
            listing_stats = velocity_database.get(str(lid), {})
            
            # 💥 LIVE DEMAND OVERRIDE 💥
            shop_data = shop_database.get(shop_name) or {}
            daily_sales = listing_stats.get("daily_sales", 0)
            daily_views = listing_stats.get("daily_views", 0)

            # B-03: pass the measured daily rate so a badge claiming more than the whole
            # shop sells gets clamped. None when this shop has never been tracked —
            # unmeasured, so nothing to clamp against, and no clamp is applied.
            est = estimate_sales(
                review_count=review_count,
                shop_total_sales=shop_data.get('total_sales'),
                shop_total_reviews=shop_data.get('total_reviews'),
                daily_sales=daily_sales,
                shop_sales_per_day=self.db.latest_shop_rate(shop_name) if shop_name else None,
            )
            sales_lifetime_est, sales_30d_est = est.lifetime, est.thirty_day
            lifetime_sales, sales_basis = est.chosen, est.basis
            if est.note:
                print(f"      [!] {lid}: {est.note}")
            estimated_views, views_basis = estimate_views(
                lifetime_sales, daily_views, self.cvr, self.cvr_source)
                
            # Velocity Calculator
            velocity_score = "DEAD 💀"
            days_since_last = -1
            
            listing_stats = velocity_database.get(str(lid), {})
            recent_dates = listing_stats.get("recent_dates", [])
            favorites = listing_stats.get("favorites", 0)
            in_cart = listing_stats.get("in_cart", 0)
            
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
                    
            results.append({
                "rank": i + 1,
                "listing_id": lid,
                "shop_name": shop_name,
                "price": card.get("price"),
                "total_reviews": review_count,
                "estimated_views": estimated_views,
                "views_basis": views_basis,
                "lifetime_sales": lifetime_sales,
                "sales_lifetime_est": sales_lifetime_est,
                "sales_30d_est": sales_30d_est,
                "sales_basis": sales_basis,
                "velocity": velocity_score,
                "days_since_last_review": days_since_last,
                "favorites": favorites,
                "in_cart": listing_stats.get("in_cart", 0),
                "daily_sales": daily_sales,
                "daily_views": daily_views,
                "scarcity_stock": listing_stats.get("scarcity_stock", 0),
                "demand_signals": listing_stats.get("demand_signals", [])
            })
            
        # Save Phase 4 Final State
        report_path = os.path.join(self.seo_cache, f"grid_report_{self.query_slug}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        print(f"[+] Final Report cached to: {report_path}")
        
        # Save to Master Database. Appends one observation per listing, with provenance.
        #
        # Failures are counted and reported rather than swallowed: the previous version
        # wrapped this in `except Exception: pass` and then printed a success line with the
        # full listing count, so a run where every write failed looked identical to one
        # where every write succeeded.
        saved, failed = 0, []
        for res in results:
            try:
                self.db.record_listing(
                    listing_id=res["listing_id"],
                    shop_name=res["shop_name"],
                    price=res["price"],
                    sales_lifetime_est=res.get("sales_lifetime_est"),
                    sales_30d_est=res.get("sales_30d_est"),
                    sales_basis=res.get("sales_basis"),
                    estimated_views=res["estimated_views"],
                    views_basis=res.get("views_basis"),
                    velocity_score=res["velocity"],
                    daily_sales=res.get("daily_sales", 0),
                    daily_views=res.get("daily_views", 0),
                    scarcity_stock=res.get("scarcity_stock", 0),
                    badge_present=bool(res.get("demand_signals")),
                    demand_signals=res.get("demand_signals", []),
                    total_reviews=res.get("total_reviews"),
                )
                saved += 1
            except Exception as e:
                failed.append((res.get("listing_id"), str(e)))

        print(f"[+] Recorded {saved}/{len(results)} listing observations.")
        # Health question 1 ("rows written") and 4 read these off the stage record.
        runlog.count(rows_in=len(results), rows_out=saved, errors=len(failed))
        if failed:
            print(f"[-] {len(failed)} write(s) FAILED — the report above is incomplete:")
            for lid, err in failed[:5]:
                print(f"    {lid}: {err}")
        
        # Render Report
        print("\n\n================================================================================================================")
        print(f"                               GRID MARKET REPORT: {self.query.upper()}")
        print("================================================================================================================")
        print(f"{'Rank':<5} | {'Listing ID':<12} | {'Shop':<18} | {'Views (Est)':<12} | {'Sales (Est)':<12} | {'Velocity':<10} | {'Favs':<8} | {'Cart':<5} | {'Last Review'}")
        print("-" * 115)
        for res in results:
            days = f"{res['days_since_last_review']}d ago" if res['days_since_last_review'] >= 0 else "Unknown"
            print(f"#{res['rank']:<4} | {res['listing_id']:<12} | {res['shop_name'][:18]:<18} | {res['estimated_views']:<12,} | {res['lifetime_sales']:<12,} | {res['velocity']:<10} | {res['favorites']:<8,} | {res['in_cart']:<5} | {days}")
        print("================================================================================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Grid Analytics Pipeline with specific filters.")
    parser.add_argument("--seed", type=str, default="leather journal", help="The search query.")
    parser.add_argument("--filters", type=str, default="{}", help="JSON string of filters (e.g., '{\"attr_1\": \"1220\"}')")
    parser.add_argument("--max_listings", type=int, default=3, help="Max listings to analyze.")
    parser.add_argument("--cvr", type=float, default=0.02, help="Exact CVR from Private API.")
    
    args = parser.parse_args()
    
    try:
        filters_dict = json.loads(args.filters)
    except json.JSONDecodeError:
        print("[-] Invalid JSON string provided for --filters. Using empty filters.")
        filters_dict = {}
        
    pipeline = GridAnalyticsPipeline(args.seed, filters=filters_dict, max_listings=args.max_listings, cvr=args.cvr)
    pipeline.run()
