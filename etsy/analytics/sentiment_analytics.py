import os
import sys
import json

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from etsy.api.public.listing_api import get_listing_data
from etsy.api.public.reviews_api import get_review_details
from core.llm_client import LLMClient
from core.database import MarketDatabase

class SentimentAnalyticsPipeline:
    def __init__(self, listing_id):
        self.listing_id = str(listing_id)
        self.api = EtsyPublicAPI()
        self.llm = LLMClient()
        self.db = MarketDatabase()
        
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.seo_cache, exist_ok=True)
        
    def run(self):
        print(f"\n==========================================================")
        print(f"      STARTING SENTIMENT ANALYTICS PIPELINE: {self.listing_id}")
        print(f"==========================================================")
        
        print(f"\n[PHASE 1] Extracting Shop & Security Tokens...")
        listing_data = get_listing_data(self.listing_id, self.api)
        if not listing_data:
            print("[-] Failed to fetch listing data.")
            return
            
        shop_id = listing_data.get('shop_id')
        csrf = listing_data.get('csrf_token')
        shop_name = listing_data.get('shop_name', 'Unknown')
        print(f"[+] Shop ID: {shop_id}, CSRF Valid: {bool(csrf)}")
        
        print(f"\n[PHASE 2] Fetching Deep Dive Reviews...")
        reviews = get_review_details(self.listing_id, public_api=self.api, shop_id=shop_id, csrf_token=csrf)
        print(f"[+] Extracted {len(reviews)} reviews for text analysis.")
        
        print(f"\n[PHASE 3] Analyzing Customer Pain Points...")
        
        negative_reviews = [r for r in reviews if r['rating'] <= 3]
        positive_reviews = [r for r in reviews if r['rating'] >= 4]
        
        print(f"[+] Found {len(negative_reviews)} Critical Reviews (1-3 Stars)")
        print(f"[+] Found {len(positive_reviews)} Positive Reviews (4-5 Stars)")
        
        ai_summary = "No critical reviews found to analyze."
        if negative_reviews:
            print(f"[+] Sending {len(negative_reviews)} reviews to DeepSeek AI for analysis...")
            # Combine reviews into a single text block
            combined_text = "\n\n".join([r['text'] for r in negative_reviews])
            ai_summary = self.llm.analyze_sentiment(combined_text)
            print("[+] AI Analysis Complete.")
            
        result = {
            "listing_id": self.listing_id,
            "shop_name": shop_name,
            "total_extracted": len(reviews),
            "critical_count": len(negative_reviews),
            "positive_count": len(positive_reviews),
            "ai_pain_point_summary": ai_summary,
            "sample_critical_reviews": [r['text'] for r in negative_reviews[:3]]
        }
        
        report_path = os.path.join(self.seo_cache, f"sentiment_report_{self.listing_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        print(f"[+] Final Report cached to: {report_path}")
        
        # Save to Master Database
        if ai_summary != "No critical reviews found to analyze.":
            try:
                self.db.upsert_listing_flaws(self.listing_id, ai_summary)
                print(f"[+] Saved DeepSeek Flaws to Market Database.")
            except Exception as e:
                print(f"[-] Failed to save to database: {e}")
        
        print("\n\n=========================================================================================")
        print(f"                               CUSTOMER SENTIMENT REPORT: {self.listing_id}")
        print("=========================================================================================")
        print(f"Shop Name: {shop_name}")
        print(f"Total Reviews Scanned: {len(reviews)}")
        print(f"Critical Reviews (1-3 Stars): {len(negative_reviews)}")
        print(f"\n[DeepSeek AI: Top Pain Points Detected]")
        print(ai_summary)
            
        print(f"\n[Sample Critical Feedback]")
        for i, text in enumerate(result['sample_critical_reviews']):
            print(f" {i+1}. \"{text[:100]}...\"")
        print("=========================================================================================\n")

if __name__ == "__main__":
    pipeline = SentimentAnalyticsPipeline("1238067877")
    pipeline.run()
