import json
import os
import time
from collections import deque
from etsy.api.private.api import EtsyPrivateAPI, edge_term
from core.runlog import logged_stage

class PrivateRecursiveSpider:
    def __init__(self, seed_keyword, max_depth=2, max_nodes=50):
        """
        Recursively crawls Etsy's AI suggestion engine to map out an entire sub-domain.
        Now Hyper-Optimized using Batch Metric Extraction.
        """
        self.seed = seed_keyword
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.api = EtsyPrivateAPI()
        
        self.visited = set()
        self.graph = {} # Maps keyword -> list of suggested keywords
        self.node_metrics = {} # Maps keyword -> {volume, listings, demand_ratio}

    @logged_stage("private_recursive_spider")
    def run(self):
        print(f"\n[SPIDER] Initializing Recursive Spider for seed: '{self.seed}'")
        print(f"[SPIDER] Max Depth: {self.max_depth} | Max Nodes: {self.max_nodes}")
        
        # STEP 1: BFS CRAWL (Building the Graph)
        queue = deque([(self.seed, 0)])
        nodes_processed = 0
        
        while queue and nodes_processed < self.max_nodes:
            current_keyword, current_depth = queue.popleft()
            
            if current_keyword in self.visited:
                continue
                
            self.visited.add(current_keyword)
            nodes_processed += 1
            
            print(f"\n  🕸️ [Depth {current_depth}] Crawling Node {nodes_processed}/{self.max_nodes}: '{current_keyword}'")
            
            # Extract Sub-Domain edges via AI Engine
            if current_depth < self.max_depth:
                edges = self.api.get_similar_keywords(current_keyword, iterations=3)
                if edges:
                    extracted_terms = []
                    for e in edges:
                        term = edge_term(e)
                        if term:
                            extracted_terms.append(term)
                            if term not in self.visited:
                                queue.append((term, current_depth + 1))
                    
                    self.graph[current_keyword] = extracted_terms
                    print(f"      Found {len(extracted_terms)} sub-domain branches!")
                else:
                    self.graph[current_keyword] = []
                    
        # STEP 2: HYPER-OPTIMIZED BATCH METRIC EXTRACTION
        print(f"\n  [+] Crawl Phase Complete. Commencing Batch Metric Extraction...")
        kw_list = list(self.visited)
        chunks = [kw_list[i:i + 3] for i in range(0, len(kw_list), 3)]
        
        for idx, chunk in enumerate(chunks):
            print(f"      -> Batch extracting metrics for chunk {idx+1}/{len(chunks)}: {chunk}")
            time.sleep(0.5)
            
            chart = self.api.get_chart_series(chunk, days=365)
            if chart and "termSummaries" in chart:
                for s in chart["termSummaries"]:
                    term = s.get("searchTerm")
                    vol = s.get("searchVolume", 0)
                    listings = s.get("avgTotalListings", 0)
                    
                    ratio = round(vol / listings, 4) if listings > 0 else 0
                    
                    self.node_metrics[term] = {
                        "search_volume": vol,
                        "total_listings": listings,
                        "demand_ratio": ratio
                    }
                    
        # STEP 3: SAVE FINAL NETWORK MAP
        os.makedirs("etsy/data/reports", exist_ok=True)
        report_path = f"etsy/data/reports/spider_map_{self.seed.replace(' ', '_')}.json"
        
        final_payload = {
            "seed": self.seed,
            "total_nodes_mapped": nodes_processed,
            "max_depth_reached": self.max_depth,
            "node_metrics": self.node_metrics,
            "graph_edges": self.graph
        }
        
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(final_payload, f, indent=4)
            
        print(f"\n[+] Spider successfully mapped and scored {nodes_processed} nodes.")
        print(f"[+] Atlas map saved to: {report_path}")

