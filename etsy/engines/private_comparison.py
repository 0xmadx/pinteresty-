import json
import os
from etsy.api.private.api import EtsyPrivateAPI, parse_term_summaries
from core.runlog import logged_stage

class PrivateComparisonPipeline:
    def __init__(self, keywords, days=30):
        """
        Takes up to 3 keywords to mathematically compare their demand and competition.
        """
        self.keywords = keywords[:3] # Etsy's API hard limit is 3, even though UI says 2.
        self.days = days
        self.api = EtsyPrivateAPI()

    @logged_stage("private_comparison")
    def run(self):
        print(f"\n[PRIVATE COMPARISON] Initializing Zero-Quota limit bypass for: {self.keywords}")
        
        # 1. Zero-Quota Extraction (via chart-series-data)
        chart_data = self.api.get_chart_series(self.keywords, days=self.days)
        # snake_case: the API returns term_summaries, not termSummaries. Reading the
        # camelCase key made this bail out on every run.
        summaries = parse_term_summaries(chart_data)
        if not summaries:
            print("[-] Failed to extract comparison data.")
            return
        
        # 2. Mathematical Comparison
        results = []
        for s in summaries:
            term = s["keyword"]
            vol = s["volume"] or 0
            listings = s["supply"] or 0
            
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

