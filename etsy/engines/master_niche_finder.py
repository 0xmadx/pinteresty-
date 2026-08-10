import json
import os
import time
from collections import deque
from etsy.api.private.api import EtsyPrivateAPI

class MasterNicheFinder:
    def __init__(self, seed_keyword, max_depth=2, max_nodes=50):
        """
        The Hyper-Optimized Batch Engine.
        Crawls sub-keywords deeply, batches them to the comparison endpoint for speed,
        and only uses the deep-dive endpoint on the absolute winners.
        """
        self.seed = seed_keyword
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.api = EtsyPrivateAPI()

    def run(self):
        print(f"\n[MASTER ENGINE] Initializing Hyper-Optimized Spider for seed: '{self.seed}'")
        print(f"[MASTER ENGINE] Max Depth: {self.max_depth} | Max Nodes: {self.max_nodes}")
        
        # STEP 1: DEEP RECURSIVE CRAWL (BFS)
        print(f"\n  [1] Executing Deep Crawl...")
        keywords_to_analyze = set([self.seed])
        queue = deque([(self.seed, 0)])
        
        while queue and len(keywords_to_analyze) < self.max_nodes:
            current_keyword, current_depth = queue.popleft()
            
            print(f"      🕸️ [Depth {current_depth}] Mapping node '{current_keyword}'...")
            
            if current_depth < self.max_depth:
                edges = self.api.get_similar_keywords(current_keyword, iterations=2)
                if edges:
                    for e in edges:
                        term = e.get("searchTerm")
                        if term and term not in keywords_to_analyze:
                            keywords_to_analyze.add(term)
                            queue.append((term, current_depth + 1))
                            if len(keywords_to_analyze) >= self.max_nodes:
                                break
                                
        kw_list = list(keywords_to_analyze)
        print(f"\n      [+] Crawl Complete! Discovered {len(kw_list)} unique micro-niches.")
        
        # STEP 2: BATCH METRIC EXTRACTION (The Optimization)
        print(f"\n  [2] Fast-Extracting Metrics via Batched Comparison Payloads...")
        scored_niches = []
        
        # Split into chunks of 3 for the chart-series-data endpoint
        chunks = [kw_list[i:i + 3] for i in range(0, len(kw_list), 3)]
        
        for idx, chunk in enumerate(chunks):
            print(f"      -> Batch processing chunk {idx+1}/{len(chunks)}: {chunk}")
            time.sleep(0.5) # Be polite
            
            chart = self.api.get_chart_series(chunk, days=365)
            if chart and "termSummaries" in chart:
                for s in chart["termSummaries"]:
                    term = s.get("searchTerm")
                    vol = s.get("searchVolume", 0)
                    listings = s.get("avgTotalListings", 0)
                    
                    # Base Mathematical Scoring
                    opportunity_score = round((vol / listings) * 1000, 2) if listings > 0 else 0
                    
                    scored_niches.append({
                        "keyword": term,
                        "volume": vol,
                        "competition": listings,
                        "base_opportunity_score": opportunity_score
                    })
                    
        # STEP 3: FIND THE "RIGHT SPOT"
        # Sort by opportunity score
        scored_niches = sorted(scored_niches, key=lambda x: x["base_opportunity_score"], reverse=True)
        top_3 = scored_niches[:3]
        
        print(f"\n  [3] Found the 'Right Spot'! Top 3 Micro-Niches Across All Layers:")
        for idx, niche in enumerate(top_3):
            print(f"      🏆 #{idx+1} '{niche['keyword']}': Score {niche['base_opportunity_score']} (Vol: {niche['volume']}, Comp: {niche['competition']})")
            
        # STEP 4: SINGLE DEEP DIVE ON WINNERS
        print(f"\n  [4] Executing Deep-Dive on Winners to Extract True Pricing & CVR...")
        final_winners = []
        
        for niche in top_3:
            kw = niche["keyword"]
            print(f"      -> Extracting Absolute Truth for '{kw}'...")
            time.sleep(1)
            
            data = self.api.get_results_data(kw)
            if data and "stats" in data:
                cvr = data["stats"].get("cvr", 0)
                prices = data.get("competitivePriceData", {}).get("searchTermMedianPrice", {})
                low_price = prices.get("medianPriceLow", "Unknown")
                high_price = prices.get("medianPriceHigh", "Unknown")
                
                niche["cvr_bucket"] = cvr
                niche["pricing_band"] = f"{low_price} to {high_price}"
                final_winners.append(niche)
                
                print(f"         [!] Verified: CVR={cvr} | Buyer Pays: {niche['pricing_band']}")
        
        # FINAL OUTPUT
        final_report = {
            "seed": self.seed,
            "max_depth_scanned": self.max_depth,
            "total_niches_analyzed": len(kw_list),
            "top_3_deep_dive": final_winners,
            "all_scored_niches": scored_niches
        }
        
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/hyper_master_niche_{self.seed.replace(' ', '_')}.json"
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_report, f, indent=4)
            
        print(f"\n[+] Master Engine Complete! Final Blueprint saved to: {report_path}")
        return final_report
