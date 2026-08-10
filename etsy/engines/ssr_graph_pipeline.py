import os
import sys
import json
import time
import argparse
from typing import List, Dict

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from core.graph_db import GraphDB
from etsy.api.private.api import EtsyPrivateAPI

def extract_node_data(api: EtsyPrivateAPI, term: str) -> dict:
    """Uses the API wrapper to get the master payload for a single node."""
    data = api.get_results_data(term)
    if not data:
        return None
        
    stats = data.get("stats", {})
    return {
        "term_id": str(stats.get("search_term_hash", stats.get("searchTermHash", ""))),
        "term": term,
        "volume": stats.get("searchVolume", 0),
        "supply": stats.get("avgTotalListings", 0),
        "cvr_raw": stats.get("queryCvr", stats.get("query_cvr", 0)),
        "wow_value": data.get("wow_data", data.get("wowData", {})).get("value", 0.0) if data.get("wow_data") or data.get("wowData") else 0.0,
        "wow_trend": data.get("wow_data", data.get("wowData", {})).get("trendDirection", "") if data.get("wow_data") or data.get("wowData") else "",
        "price_low": data.get("competitivePriceData", {}).get("searchTermMedianPrice", {}).get("medianPriceBarLowFloat"),
        "price_high": data.get("competitivePriceData", {}).get("searchTermMedianPrice", {}).get("medianPriceBarHighFloat"),
        "listings": data.get("competitiveResearchListingCards", []),
        "series": data.get("dailyStats", {}).get("stats", [])
    }

def extract_edges(api: EtsyPrivateAPI, term: str) -> List[Dict]:
    """Uses the API wrapper's LLM polling to get ~180 similar keywords as edges."""
    print(f"  [>] Fetching LLM edges for '{term}'...")
    results = api.get_similar_keywords(term)
    if not results:
        return []
        
    edges = []
    for r in results:
        edges.append({
            "term": r.get("searchTerm", ""),
            "volume": r.get("searchVolume", 0),
            "supply": r.get("avgTotalListings", 0),
            "cvr_bucket": r.get("cvr", 0)
        })
    return edges

def run_bfs(seed_term: str, max_depth: int, max_nodes: int):
    print("\nInitializing Recursive Pipeline...")
    api = EtsyPrivateAPI()
    db = GraphDB()
    
    # Initialize DB with the seed term
    if not db.is_visited(seed_term):
        db.push_frontier(seed_term, depth=0, parent_id=None)
        
    print("\n--- Starting BFS Graph Traversal ---")
    print(f"Seed: '{seed_term}' | Max Depth: {max_depth} | Max Nodes: {max_nodes}\n")
    
    nodes_processed = 0
    
    while nodes_processed < max_nodes:
        # 1. Get next unvisited node from frontier
        current_node = db.pop_frontier()
        if not current_node:
            print("\n[+] Frontier is empty. Traversal complete.")
            break
            
        term = current_node['term']
        current_depth = current_node['depth']
        parent_id = current_node['parent_id']
        
        print(f"[{nodes_processed+1}/{max_nodes}] Depth {current_depth}: Parsing '{term}'...")
        
        # 2. Fetch the node's master payload to save its stats
        node_data = extract_node_data(api, term)
        if node_data and node_data.get("volume", 0) > 0:
            
            # Fetch edges for this node (if not at max depth)
            edges = []
            if current_depth < max_depth:
                edges = extract_edges(api, term)
                node_data["edges"] = edges
            else:
                print(f"  [~] Reached max depth ({max_depth}). Skipping edge extraction.")
                node_data["edges"] = []
                
            node_data["depth"] = current_depth
            node_data["parent_id"] = parent_id
            
            # Save the node with all stats, listings, chart, and edges
            db.add_node(node_data)
            print(f"  [+] Saved node: Vol={node_data['volume']}, Supply={node_data['supply']}, CVR={node_data['cvr_raw']:.6f}")
            
            # Process edges
            qualified_edges = [e for e in edges if e.get("volume", 0) > 100]
            
            for edge in qualified_edges:
                child_term = edge['term']
                db.push_frontier(child_term, depth=current_depth + 1, parent_id=node_data['term_id'])
                    
            if edges:
                print(f"  [+] Pushed {len(qualified_edges)} highly qualified edges to frontier.")
        else:
            print(f"  [-] Failed to fetch valid stats for '{term}'")
            
        nodes_processed += 1
        time.sleep(1) # Polite delay between terms
        
    print("\n--- Traversal Complete ---")
    print(f"Processed {nodes_processed} nodes.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=str, default="parents anniversary gift")
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--max_nodes", type=int, default=5)
    args = parser.parse_args()
    
    run_bfs(args.seed, args.depth, args.max_nodes)
