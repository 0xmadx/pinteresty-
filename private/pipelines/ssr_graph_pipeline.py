import os
import sys
import json
import re
import time
import urllib.parse

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.endpoints_manager import EndpointManager
from core.session_manager import SessionManager
from core.settings import ScraperConfig
from core.graph_db import GraphDB

class SSRGraphPipeline:
    def __init__(self, db_path="data/etsy_graph.db"):
        print("Initializing Recursive SSR Graph Pipeline...")
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        self.db = GraphDB(db_path=db_path)
        
        # We need the cookies from req_1 or similar to be authenticated
        manager = EndpointManager()
        try:
            with open('inputs/curl_commands/private/req_1.py', 'r', encoding='utf-8') as f:
                manager.parse_curl_command("req_1", f.read())
            req_config = manager.get_endpoint("req_1")
            self.cookies = req_config.get("cookies", {})
            self.headers = req_config.get("headers", {})
            
            # Clean headers
            self.sanitized_headers = {k: v for k, v in self.headers.items() if k.lower() not in [
                "user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
                "sec-ch-ua-full-version-list", "sec-ch-ua-arch", "sec-ch-ua-bitness"
            ]}
        except Exception as e:
            print(f"Warning: Failed to load cookies from req_1.py: {e}")
            self.cookies = {}
            self.sanitized_headers = {}

    def fetch_node_ssr(self, term):
        encoded_term = urllib.parse.quote_plus(term)
        url = f"https://www.etsy.com/your/shops/me/marketplace-insights/search?query={encoded_term}&search_trigger=similar_term"
        
        print(f"  [GET] {url}")
        resp = self.session.request("GET", url, headers=self.sanitized_headers, cookies=self.cookies)
        
        if resp.status_code != 200:
            print(f"  [-] Failed to fetch {term}: HTTP {resp.status_code}")
            return None
            
        # Extract script tags
        scripts = re.findall(r'<script[^>]*>(.*?)</script>', resp.text, re.DOTALL)
        target_script = None
        for s in scripts:
            if 'Etsy.Context=' in s and 'marketplace_insights_search' in s:
                target_script = s
                break
                
        if not target_script:
            print(f"  [-] Failed to find target script tag for {term}")
            return None
            
        # Parse the JSON blob
        match = re.search(r'Etsy\.Context=(.*?);(?=window|$)', target_script, re.DOTALL)
        if not match:
            print(f"  [-] Failed to find Etsy.Context inside script for {term}")
            return None
            
        try:
            ctx = json.loads(match.group(1))
            return ctx.get('data', {}).get('initial_data', {}).get('marketplace_insights_search')
        except Exception as e:
            print(f"  [-] Failed to parse JSON blob for {term}: {e}")
            return None

    def _safe_get(self, d, keys, default=None):
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def parse_and_persist(self, term, data, depth, parent_id):
        if not data:
            return None
            
        term_id = data.get('searchTermId')
        if not term_id:
            # If the search term is invalid or has no data, Etsy might not return an ID
            print(f"  [-] No searchTermId found for {term}. Skipping.")
            return None
            
        stats = data.get('stats', {})
        wow = data.get('wowData', {}) or {}
        price_data = data.get('competitivePriceData', {}) or {}
        
        node = {
            'term_id': str(term_id),
            'term': term,
            'volume': stats.get('searchVolume', 0),
            'supply': stats.get('avgTotalListings', 0),
            'cvr_raw': stats.get('queryCvr', 0.0),
            'wow_value': wow.get('value', 0.0),
            'wow_trend': wow.get('trendDirection', ''),
            'price_low': price_data.get('medianPriceLow'),
            'price_high': price_data.get('medianPriceHigh'),
            'depth': depth,
            'parent_id': parent_id,
            'series': data.get('dailyStats', []),
            'listings': self._safe_get(data, ['competitiveResearchListingCards', 'listingCards'], []),
            'edges': self._safe_get(data, ['similarSearchTerms', 'results'], [])
        }
        
        self.db.add_node(node)
        return node

    def run_bfs(self, seed, max_depth=2, max_nodes=50):
        print(f"\n--- Starting BFS Graph Traversal ---")
        print(f"Seed: '{seed}' | Max Depth: {max_depth} | Max Nodes: {max_nodes}\n")
        
        # Initialize frontier with seed if not already visited
        if not self.db.is_visited(seed):
            self.db.push_frontier(seed, 0, None)
            
        nodes_processed = 0
        
        while nodes_processed < max_nodes:
            item = self.db.pop_frontier()
            if not item:
                print("\n[+] Frontier is empty. Traversal complete.")
                break
                
            term = item['term']
            depth = item['depth']
            parent_id = item['parent_id']
            
            if depth > max_depth:
                # We skip processing this node's URL, but don't break as there might be other valid nodes
                continue
                
            print(f"[{nodes_processed+1}/{max_nodes}] Depth {depth}: Parsing '{term}'...")
            
            # 1. Fetch SSR
            data = self.fetch_node_ssr(term)
            if not data:
                continue
                
            # 2. Parse & Persist
            node = self.parse_and_persist(term, data, depth, parent_id)
            if not node:
                continue
                
            print(f"  [+] Saved node: Vol={node['volume']}, Supply={node['supply']}, CVR={node['cvr_raw']:.6f}")
            
            # 3. Process Edges (Gating)
            if depth < max_depth:
                valid_edges = 0
                for edge in node['edges']:
                    edge_term = edge.get('searchTerm')
                    if not edge_term:
                        continue
                        
                    edge_cvr = edge.get('cvr', 0)
                    edge_vol = edge.get('searchVolume', 0)
                    edge_supply = edge.get('avgTotalListings', 1)
                    
                    # GATE: CVR bucket >= 2 (Typical) and Volume > 10
                    # The UI edge table uses bucketed CVR, so we use bucket logic for the gate
                    if edge_cvr >= 2 and edge_vol > 10:
                        self.db.push_frontier(edge_term, depth + 1, node['term_id'])
                        valid_edges += 1
                        
                print(f"  [+] Pushed {valid_edges} highly qualified edges to frontier.")
                
            nodes_processed += 1
            
            # Polite delay
            time.sleep(2)
            
        print(f"\n--- Traversal Complete ---")
        print(f"Processed {nodes_processed} nodes.")

if __name__ == "__main__":
    pipeline = SSRGraphPipeline()
    # We start with a depth of 1 and a small node limit for testing
    pipeline.run_bfs("parents anniversary gift", max_depth=1, max_nodes=5)
