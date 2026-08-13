import re
import argparse


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
        
        # 1. Run Financials (Single Listing Pipeline)
        print("\n[>>>] INITIATING PHASE 1: FINANCIAL INTELLIGENCE [<<<]")
        try:
            financial_pipeline = SingleListingPipeline(self.listing_id)
            financial_pipeline.run()
        except Exception as e:
            print(f"[-] Financial Pipeline Failed: {e}")
            
        # 2. Run Sentiment (DeepSeek AI Review Pipeline)
        print("\n[>>>] INITIATING PHASE 2: CUSTOMER SENTIMENT & AI FLAWS [<<<]")
        try:
            sentiment_pipeline = SentimentAnalyticsPipeline(self.listing_id)
            sentiment_pipeline.run()
        except Exception as e:
            print(f"[-] Sentiment Pipeline Failed: {e}")
            
        # 3. Run SEO (Reverse-Engineer Tags & Materials)
        print("\n[>>>] INITIATING PHASE 3: SEO REVERSE-ENGINEERING [<<<]")
        try:
            seo_pipeline = SEOAnalyticsPipeline(self.listing_id)
            seo_pipeline.run()
        except Exception as e:
            print(f"[-] SEO Pipeline Failed: {e}")
            
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
