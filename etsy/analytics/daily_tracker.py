import os
import sys
import json
from datetime import datetime

# Ensure core and public endpoints are importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from core.shop_scraper import ShopScraper

TRACKING_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracking_data.json")

def run_daily_tracker(shops_to_track):
    """
    Given a list of shop names, runs the daily tracker to compute the sales delta.
    """
    public_api = EtsyPublicAPI()
    scraper = ShopScraper(public_api)
    
    # Load existing tracking data
    tracking_data = {}
    if os.path.exists(TRACKING_FILE):
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            try:
                tracking_data = json.load(f)
            except json.JSONDecodeError:
                pass
                
    today = datetime.now().strftime("%Y-%m-%d")
    
    for shop_name in shops_to_track:
        print(f"[*] Tracking: {shop_name}")
        metrics = scraper.get_shop_metrics(shop_name)
        
        if not metrics or not metrics.get("total_sales"):
            print(f"[-] Failed to get sales data for {shop_name}")
            continue
            
        current_sales = metrics["total_sales"]
        current_reviews = metrics.get("total_reviews", 0)
        
        shop_history = tracking_data.get(shop_name, {})
        last_recorded = shop_history.get("last_recorded_date")
        last_sales = shop_history.get("last_recorded_sales")
        
        # Calculate Delta
        if last_recorded and last_sales is not None:
            sales_delta = current_sales - last_sales
            if last_recorded == today:
                print(f"    -> Already tracked today. Total: {current_sales:,} (+{sales_delta:,} since last run today)")
            else:
                print(f"    -> New Daily Delta! Since {last_recorded}: +{sales_delta:,} Sales")
        else:
            print(f"    -> First time tracking this shop. Baseline set at {current_sales:,} Sales.")
            
        # Update tracking object
        tracking_data[shop_name] = {
            "last_recorded_date": today,
            "last_recorded_sales": current_sales,
            "last_recorded_reviews": current_reviews,
            "history_log": shop_history.get("history_log", []) + [{
                "date": today,
                "sales": current_sales,
                "reviews": current_reviews
            }]
        }
        
    # Save back to file
    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(tracking_data, f, indent=4)
        
    print(f"\n[+] Tracking complete. Data saved to {TRACKING_FILE}")

if __name__ == "__main__":
    # Test tracking run on two popular shops
    run_daily_tracker(["HIDEAcraftedleather", "EngraveGiftLab"])
