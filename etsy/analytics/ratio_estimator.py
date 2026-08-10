import os
import sys

# Ensure core and public endpoints are importable
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from core.shop_scraper import ShopScraper
import json

def estimate_listing_sales(listing_id, public_api=None):
    """
    Given a listing ID, scrapes the listing's public SERP data (if cached) to find its shop name
    and review count, then fetches the shop's total sales and reviews to estimate the listing's sales.
    """
    if public_api is None:
        public_api = EtsyPublicAPI()
        
    # We need the listing's review count and shop name.
    # We can pull this from our cached SERP results in `public/data/raw/` for now.
    # In a fully productionized system, we would query our DB or make a fresh SERP request.
    
    listing_review_count = None
    shop_name = None
    
    # Simple hack to find the listing in our cached raw SERP data:
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "public", "data", "raw")
    if os.path.exists(cache_dir):
        for filename in os.listdir(cache_dir):
            if filename.startswith("public_search_") and filename.endswith(".json"):
                with open(os.path.join(cache_dir, filename), "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for card in data.get("cards", []):
                        if str(card.get("listing_id")) == str(listing_id):
                            listing_review_count = card.get("review_count")
                            shop_name = card.get("shop_name")
                            break
                if shop_name:
                    break
                    
    if not shop_name:
        print(f"[-] Could not find listing {listing_id} in local SERP cache.")
        return None
        
    if not listing_review_count:
        listing_review_count = 0
        
    print(f"[+] Found Listing {listing_id} in Shop '{shop_name}' with {listing_review_count} reviews.")
    
    # 2. Fetch Shop Metrics
    scraper = ShopScraper(public_api)
    shop_metrics = scraper.get_shop_metrics(shop_name)
    
    if not shop_metrics or not shop_metrics.get("total_sales") or not shop_metrics.get("total_reviews"):
        print("[-] Failed to retrieve full shop metrics for ratio calculation.")
        return None
        
    total_sales = shop_metrics["total_sales"]
    total_reviews = shop_metrics["total_reviews"]
    
    if total_reviews == 0:
        print("[-] Shop has 0 reviews, cannot calculate ratio.")
        return None
        
    # 3. Calculate Ratio
    ratio = total_sales / total_reviews
    estimated_sales = int(listing_review_count * ratio)
    
    print("\n--- Estimated Sales Report ---")
    print(f"Shop: {shop_name}")
    print(f"Shop Total Sales: {total_sales:,}")
    print(f"Shop Total Reviews: {total_reviews:,}")
    print(f"Shop Sales-to-Review Ratio: {ratio:.2f} (1 review = {ratio:.2f} sales)")
    print(f"Listing ID: {listing_id}")
    print(f"Listing Reviews: {listing_review_count:,}")
    print(f"Estimated Listing Sales: {estimated_sales:,}")
    print("------------------------------\n")
    
    return {
        "listing_id": listing_id,
        "shop_name": shop_name,
        "ratio": ratio,
        "estimated_sales": estimated_sales
    }

if __name__ == "__main__":
    # Test with the known HIDEAcraftedleather listing
    estimate_listing_sales("4502693975")
