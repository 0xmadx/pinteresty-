import json
import os
from etsy.api.private.api import EtsyPrivateAPI

class PrivateComparisonPipeline:
    def __init__(self, keywords, days=30):
        """
        Takes up to 3 keywords to mathematically compare their demand and competition.
        """
        self.keywords = keywords[:3] # Etsy's API hard limit is 3, even though UI says 2.
        self.days = days
        self.api = EtsyPrivateAPI()

    def run(self):
        print(f"\n[PRIVATE COMPARISON] Initializing Zero-Quota limit bypass for: {self.keywords}")
        
        # 1. Zero-Quota Extraction (via chart-series-data)
        chart_data = self.api.get_chart_series(self.keywords, days=self.days)
        if not chart_data or "termSummaries" not in chart_data:
            print("[-] Failed to extract comparison data.")
            return
            
        summaries = chart_data["termSummaries"]
        
        # 2. Mathematical Comparison
        results = []
        for s in summaries:
            term = s.get("searchTerm", "")
            vol = s.get("searchVolume", 0)
            listings = s.get("avgTotalListings", 0)
            
            # Demand vs Supply Ratio
            ratio = round(vol / listings, 4) if listings > 0 else 0
            
            results.append({
                "keyword": term,
                "volume": vol,
                "listings": listings,
                "demand_ratio": ratio
            })
            
        # Sort by best ratio (Highest Volume relative to Lowest Competition)
        results = sorted(results, key=lambda x: x["demand_ratio"], reverse=True)
        
        print(f"\n[PRIVATE COMPARISON] Final Results (Ranked by Demand Ratio):")
        for idx, r in enumerate(results):
            winner_tag = "🏆 [WINNER]" if idx == 0 else "   [LOSER]"
            print(f" {winner_tag} '{r['keyword']}':")
            print(f"      Search Volume : {r['volume']}")
            print(f"      Total Listings: {r['listings']}")
            print(f"      Demand Ratio  : {r['demand_ratio']}")
            
        # Save to disk
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/private_comparison_{self.keywords[0].replace(' ', '_')}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4)
        print(f"\n[+] Private comparison report saved to {report_path}")

