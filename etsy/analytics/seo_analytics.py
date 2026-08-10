import os
import sys
import json
import re

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from etsy.api.public.api import EtsyPublicAPI
from etsy.api.public.listing_api import get_listing_data

class SEOAnalyticsPipeline:
    def __init__(self, listing_id):
        self.listing_id = str(listing_id)
        self.api = EtsyPublicAPI()
        
        self.seo_cache = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "seo", "cache")
        os.makedirs(self.seo_cache, exist_ok=True)
        
    def run(self):
        print(f"\n==========================================================")
        print(f"        STARTING SEO ANALYTICS PIPELINE: {self.listing_id}")
        print(f"==========================================================")
        
        print(f"\n[PHASE 1] Extracting SEO Data...")
        listing_data = get_listing_data(self.listing_id, self.api)
        if not listing_data:
            print("[-] Failed to fetch listing data.")
            return
            
        title = listing_data.get('title', '')
        description = listing_data.get('description', '')
        shop_name = listing_data.get('shop_name', 'Unknown')
        
        print(f"[+] Title Extracted: {len(title)} chars")
        print(f"[+] Description Extracted: {len(description)} chars")
        
        print(f"\n[PHASE 2] Analyzing Keyword Density...")
        
        # Simple extraction of common keywords in title
        words = re.findall(r'\b\w{4,}\b', title.lower())
        word_freq = {}
        for w in words:
            word_freq[w] = word_freq.get(w, 0) + 1
            
        sorted_keywords = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
        
        result = {
            "listing_id": self.listing_id,
            "shop_name": shop_name,
            "title": title,
            "description": description[:500] + "..." if len(description) > 500 else description,
            "top_title_keywords": [k for k, v in sorted_keywords]
        }
        
        report_path = os.path.join(self.seo_cache, f"seo_report_{self.listing_id}.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=4)
        print(f"[+] Final Report cached to: {report_path}")
        
        print("\n\n=========================================================================================")
        print(f"                                   SEO BLUEPRINT REPORT")
        print("=========================================================================================")
        print(f"Title: {title}")
        print(f"\n[Top Repeated Title Keywords]")
        for kw, count in sorted_keywords:
            if count > 1:
                print(f" - {kw} ({count} uses)")
            else:
                print(f" - {kw}")
                
        print(f"\n[Description Snippet]")
        print(f"{result['description'][:200]}...")
        print("=========================================================================================\n")

if __name__ == "__main__":
    pipeline = SEOAnalyticsPipeline("1238067877")
    pipeline.run()
