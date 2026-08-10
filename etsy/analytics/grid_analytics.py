import sys
import os
import json
import datetime
import argparse
from pathlib import Path

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from core.shop_scraper import ShopScraper
from etsy.api.public.listing_api import get_listing_data
from etsy.api.public.reviews_api import get_recent_reviews
from core.database import MarketDatabase

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
        
        # Override CVR if it exists in the database
        db_keyword = self.db.get_keyword(self.query)
        if db_keyword and db_keyword.get("query_cvr"):
            self.cvr = db_keyword["query_cvr"]
            print(f"[*] Pulled exact CVR ({self.cvr}) from Market Database for '{self.query}'")
        
        # Setup cache directories
        self.raw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "public", "data", "raw")
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.raw_dir, exist_ok=True)
        os.makedirs(self.seo_cache, exist_ok=True)
        
        self.query_slug = self.query.replace(' ', '_')
        
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
            
            # Lifetime Sales (Ratio Estimator)
            lifetime_sales = 0
            estimated_views = 0
            shop_data = shop_database.get(shop_name)
            if shop_data and shop_data.get('total_sales') and shop_data.get('total_reviews'):
                ratio = shop_data['total_sales'] / shop_data['total_reviews']
                lifetime_sales = int(review_count * ratio)
                
            # 💥 LIVE DEMAND OVERRIDE 💥
            daily_sales = listing_stats.get("daily_sales", 0)
            daily_views = listing_stats.get("daily_views", 0)
            if daily_sales > 0:
                lifetime_sales = daily_sales * 30
                
            if daily_views > 0:
                estimated_views = daily_views * 30
            else:
                estimated_views = int(lifetime_sales / self.cvr)
                
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
                "lifetime_sales": lifetime_sales,
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
        
        # Save to Master Database
        for res in results:
            try:
                self.db.upsert_listing_metrics(
                    listing_id=res["listing_id"],
                    shop_name=res["shop_name"],
                    price=res["price"],
                    est_sales=res["lifetime_sales"],
                    est_views=res["estimated_views"],
                    velocity=res["velocity"],
                    daily_sales=res.get("daily_sales", 0),
                    daily_views=res.get("daily_views", 0),
                    scarcity_stock=res.get("scarcity_stock", 0),
                    demand_signals=json.dumps(res.get("demand_signals", []))
                )
            except Exception as e:
                pass
        print(f"[+] Saved {len(results)} listings to Market Database.")
        
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
