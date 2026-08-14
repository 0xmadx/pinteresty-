import json
import time
import argparse
from typing import List, Dict


from core.graph_db import GraphDB
from etsy.api.private.api import EtsyPrivateAPI, edge_term, parse_results_data
from etsy.analytics.derivations import parse_price
from core.runlog import logged_stage

def extract_node_data(api: EtsyPrivateAPI, term: str) -> dict:
    """Uses the API wrapper to get the master payload for a single node."""
    data = api.get_results_data(term)
    if not data:
        return None
        
    # One parser for the whole response — it reads the API's real snake_case names.
    # This block previously hedged between spellings for some fields and not others,
    # so volume, supply, prices and listings all came back empty.
    stats = data.get("stats", {})
    p = parse_results_data(data)
    return {
        "term_id": str(stats.get("search_term_hash", stats.get("searchTermHash", ""))),
        "term": term,
        "volume": p["volume"] or 0,
        "supply": p["supply"] or 0,
        "cvr_raw": p["cvr"] or 0,
        "wow_value": p["wow_change"] or 0.0,
        "wow_trend": p["wow_direction"] or "",
        "price_low": parse_price(p["price_low"]),
        "price_high": parse_price(p["price_high"]),
        "listings": p["listings"],
        "series": (data.get("daily_stats") or data.get("dailyStats") or {}).get("stats", []),
    }

def extract_edges(api: EtsyPrivateAPI, term: str) -> List[Dict]:
    """Uses the API wrapper's LLM polling to get ~180 similar keywords as edges."""
    print(f"  [>] Fetching LLM edges for '{term}'...")
    results = api.get_similar_keywords(term)
    if not results:
        return []
        
    edges = []
    for r in results:
        # edge_term accepts whichever key the enqueue response uses (query vs
        # searchTerm) — reading one spelling produced an empty term on every edge.
        edges.append({
            "term": edge_term(r) or "",
            "volume": r.get("search_volume", r.get("searchVolume", 0)),
            "supply": r.get("avg_total_listings", r.get("avgTotalListings", 0)),
            "cvr_bucket": r.get("cvr", 0)
        })
    return edges

@logged_stage("ssr_graph_bfs")
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

    reclaimed = db.reclaim_stale()
    if reclaimed:
        print(f"[+] Reclaimed {reclaimed} term(s) left claimed by an interrupted run.")

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
            db.complete_frontier(term)
        elif node_data:
            # A real answer, just an uninteresting one: the term exists and has no
            # measurable volume. Answered, not failed — do not retry it forever.
            db.complete_frontier(term)
            print(f"  [-] '{term}' has no measurable volume — recorded, not retried")
        else:
            # The fetch itself failed. Hand the claim back so the next run retries it
            # rather than dropping the term from the crawl without telling anyone.
            db.release_frontier(term)
            print(f"  [!] Fetch failed for '{term}' — returned to the frontier")

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
