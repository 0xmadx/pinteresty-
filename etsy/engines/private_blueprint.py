import json
import os
from etsy.api.private.api import EtsyPrivateAPI
from etsy.analytics.derivations import parse_price
from core.database import MarketDatabase
from core.runlog import logged_stage

class PrivateBlueprintPipeline:
    def __init__(self, target_keyword):
        """
        Deep-dives into a single keyword to extract Pricing, Conversion, and Competitors.
        """
        self.keyword = target_keyword
        self.api = EtsyPrivateAPI()
        self.db = MarketDatabase()

    @logged_stage("private_blueprint")
    def run(self):
        print(f"\n[BLUEPRINT] Initializing Product Blueprint for: '{self.keyword}'")
        
        # 1. Fetch Master Payload from results-data
        data = self.api.get_results_data(self.keyword)
        if not data:
            print(f"[-] Failed to extract blueprint data for '{self.keyword}'")
            return
            
        stats = data.get("stats", {})
        prices = data.get("competitivePriceData", {}).get("searchTermMedianPrice", {})
        competitors = data.get("competitiveResearchListingCards", [])
        
        # 2. Extract Key Metrics
        vol = stats.get("searchVolume", 0)
        listings = stats.get("avgTotalListings", 0)
        cvr_bucket = stats.get("cvr")
        cvr_raw = stats.get("queryCvr")
        
        low_price = prices.get("medianPriceLow", "Unknown")
        high_price = prices.get("medianPriceHigh", "Unknown")
        
        # 3. Format Competitors
        top_competitors = []
        
        # Safely handle if competitors is a dictionary instead of a list
        if isinstance(competitors, dict):
            competitors = competitors.get("listingCards", [])
            
        if competitors and isinstance(competitors, list):
            for c in competitors[:10]: # Top 10
                # Extract formatted price if it's a dict
                raw_price = c.get("price", "")
                price_str = raw_price.get("formattedPrice", "") if isinstance(raw_price, dict) else raw_price
                
                top_competitors.append({
                    "title": c.get("title", ""),
                    "price": price_str,
                    "shop": c.get("shopName", ""),
                    "rating": c.get("rating", 0),
                    "reviews": c.get("numberOfReviews", 0),
                    "url": c.get("listingUrl", "")
                })
            
        # 4. Generate Blueprint Report
        blueprint = {
            "keyword": self.keyword,
            "metrics": {
                "search_volume": vol,
                "competition": listings,
                "conversion_rate_score": cvr_bucket,
                "conversion_rate_raw": cvr_raw
            },
            "pricing": {
                "median_buyer_paid_low": low_price,
                "median_buyer_paid_high": high_price
            },
            "top_competitors": top_competitors
        }
        
        print(f"\n[BLUEPRINT] Final Report Extracted:")
        print(f"    - True Demand: {vol}")
        print(f"    - CVR Score  : {cvr_bucket}")
        print(f"    - Buyer Price: {low_price} to {high_price}")
        print(f"    - Competitors Analyzed: {len(top_competitors)}")
        
        # Save to disk
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/private_blueprint_{self.keyword.replace(' ', '_')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(blueprint, f, indent=4)
        print(f"\n[+] Product Blueprint saved to {report_path}")
        
        # Save to Master Database.
        #
        # P-3: this used to call upsert_keyword, which stamps cvr_source='unspecified'
        # for every write — so a CVR the API actually returned and the 0.02 fallback
        # landed as the same untagged number, the exact measured-vs-derived hole this
        # system exists to close. record_keyword carries the real provenance.
        #
        # The price defaults did the same thing more quietly: an "Unknown" price became
        # 0.0, a real measured value indistinguishable from missing. parse_price returns
        # None for the unreadable cases, and price_basis records whether either end of
        # the band was actually measured.
        cvr_measured = cvr_raw not in (None, 0, "")
        low = parse_price(low_price)
        high = parse_price(high_price)
        price_basis = "measured" if (low is not None or high is not None) else "absent"
        try:
            self.db.record_keyword(
                keyword=self.keyword,
                source="etsy_private",
                volume=vol,
                competition=listings,
                cvr=cvr_raw if cvr_measured else 0.02,
                cvr_source="measured" if cvr_measured else "default",
                price_low=low,
                price_high=high,
                price_basis=price_basis,
            )
            print(f"[+] Saved '{self.keyword}' metrics to Market Database "
                  f"(cvr_source={'measured' if cvr_measured else 'default'}).")
        except Exception as e:
            print(f"[-] Failed to save to database: {e}")

