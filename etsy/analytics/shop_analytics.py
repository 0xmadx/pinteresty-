import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from core.shop_scraper import ShopScraper

class ShopAnalyticsPipeline:
    def __init__(self, shop_name):
        self.shop_name = str(shop_name)
        self.api = EtsyPublicAPI()
        self.shop_scraper = ShopScraper(self.api)
        
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.seo_cache, exist_ok=True)
        
    def run(self):
        print(f"\n==========================================================")
        print(f"       STARTING SHOP ANALYTICS PIPELINE: {self.shop_name}")
        print(f"==========================================================")
        
        # 1. Scrape Shop Data
        print(f"\n[PHASE 1] Scraping Shop Data for {self.shop_name}...")
        shop_metrics = self.shop_scraper.get_shop_metrics(self.shop_name)
        
        if not shop_metrics:
            print("[-] Failed to scrape shop page.")
            return
            
        total_sales = shop_metrics.get('total_sales') or 0
        total_reviews = shop_metrics.get('total_reviews') or 0
        active_listings = shop_metrics.get('active_listings') or 0
        
        # 2. Calculate Market Ratios
        print(f"\n[PHASE 2] Calculating Market Ratios...")
        
        # Ratio: How many sales per review?
        sales_ratio = 0.0
        if total_reviews > 0:
            sales_ratio = total_sales / total_reviews
            
        # Ratio: How many sales per active listing?
        sales_per_listing = 0.0
        if active_listings > 0:
            sales_per_listing = total_sales / active_listings
            
        result = {
            "shop_name": self.shop_name,
            "total_sales": total_sales,
            "total_reviews": total_reviews,
            "active_listings": active_listings,
            "sales_ratio": round(sales_ratio, 2),
            "sales_per_listing": round(sales_per_listing, 2)
        }
        
        # 3. Save State
        report_path = os.path.join(self.seo_cache, f"shop_report_{self.shop_name.lower()}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        print(f"[+] Final Report cached to: {report_path}")
        
        # 4. Render Report
        print("\n\n=========================================================================================")
        print(f"                               SHOP ANALYTICS REPORT: {self.shop_name.upper()}")
        print("=========================================================================================")
        print(f"{'Total Sales':<15} | {'Total Reviews':<15} | {'Active Items':<15} | {'Sales/Review':<15} | {'Sales/Item':<15}")
        print("-" * 85)
        print(f"{total_sales:<15,} | {total_reviews:<15,} | {active_listings:<15,} | {round(sales_ratio, 2):<15} | {round(sales_per_listing, 2):<15}")
        print("=========================================================================================\n")

if __name__ == "__main__":
    pipeline = ShopAnalyticsPipeline("EngraveGiftLab")
    pipeline.run()
