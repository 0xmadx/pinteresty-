import re
import argparse
import traceback


from etsy.analytics.single_listing_analytics import SingleListingPipeline
from etsy.analytics.sentiment_analytics import SentimentAnalyticsPipeline
from etsy.analytics.seo_analytics import SEOAnalyticsPipeline
from core.database import MarketDatabase
from core.runlog import logged_stage

class MasterListingAnalyzer:
    def __init__(self, url):
        self.url = url
        self.listing_id = self.extract_listing_id(url)
        self.db = MarketDatabase()
        
    def extract_listing_id(self, url):
        # Etsy URLs usually look like: https://www.etsy.com/listing/123456789/product-name
        match = re.search(r'listing/(\d+)', url)
        if match:
            return match.group(1)
        # If they just passed the raw ID by mistake, catch it
        if url.isdigit():
            return url
        return None
        
    @logged_stage("master_listing_analyzer")
    def run(self):
        print("\n=========================================================================================")
        print("                        ETSY URL X-RAY ANALYZER")
        print("=========================================================================================")
        
        if not self.listing_id:
            print("[-] Error: Could not extract a valid 10-digit listing ID from the URL.")
            print("    Please provide a valid URL (e.g., https://www.etsy.com/listing/123456789/...)")
            return
            
        print(f"[*] Extracted Target Listing ID: {self.listing_id}")
        
        # Each phase is caught so one failure does not abort the other two — but the
        # catch used to print a bare one-line message and move on, and that is how an
        # AttributeError on the FIRST LINE of listing_api.get_listing_data went
        # unnoticed for the project's life. All three phases raised it. All three
        # printed "Failed: 'EtsyPublicAPI' object has no attribute 'cookies'" among a
        # wall of banner output, and the run reported itself complete.
        #
        # A pipeline that fails must look like a failure, so: the traceback is printed,
        # the failures are collected, and the summary states them at the end where the
        # reader is actually looking.
        failures = []
        for label, phase, pipeline_cls in (
                ("FINANCIAL INTELLIGENCE", 1, SingleListingPipeline),
                ("CUSTOMER SENTIMENT & AI FLAWS", 2, SentimentAnalyticsPipeline),
                ("SEO REVERSE-ENGINEERING", 3, SEOAnalyticsPipeline)):
            print(f"\n[>>>] INITIATING PHASE {phase}: {label} [<<<]")
            try:
                pipeline_cls(self.listing_id).run()
            except Exception as e:
                traceback.print_exc()
                failures.append(f"PHASE {phase} ({label}): {type(e).__name__}: {e}")
                print(f"[-] PHASE {phase} FAILED — {type(e).__name__}: {e}")

        if failures:
            print("\n" + "!" * 89)
            print(f"  {len(failures)} of 3 PHASES FAILED — the report below is INCOMPLETE")
            for f in failures:
                print(f"    - {f}")
            print("!" * 89)


        # 4. Master Report
        print("\n=========================================================================================")
        print(f"                     X-RAY COMPLETE: {self.listing_id}")
        print("=========================================================================================")
        
        # Pull final unified state from the database
        listing_state = self.db.get_listing(self.listing_id)
        if listing_state:
            shop = listing_state.get("shop_name", "Unknown")
            views = listing_state.get("estimated_views", 0)
            sales = listing_state.get("estimated_sales", 0)
            vel = listing_state.get("velocity_score", "Unknown")
            flaws = listing_state.get("top_flaws", "No flaws recorded.")
            
            print(f"Shop Name: {shop}")
            print(f"Estimated Lifetime Views: {views:,}")
            print(f"Estimated Lifetime Sales: {sales:,}")
            print(f"Velocity Status: {vel}")
            print("\n[DeepSeek Top Flaws]:")
            print(flaws)
            
        print("\n[+] All metrics have been permanently saved to 'market_intelligence.db'.")
        print("=========================================================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drop an Etsy Listing URL to instantly X-Ray it.")
    parser.add_argument("--url", type=str, required=True, help="The Etsy Listing URL (or just the ID).")
    
    args = parser.parse_args()
    analyzer = MasterListingAnalyzer(args.url)
    analyzer.run()
