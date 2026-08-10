import os
import sys
import glob
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from core.endpoints_manager import EndpointManager
from src.services.executor import EndpointExecutor
from core.session_manager import SessionManager
from core.settings import ScraperConfig

class PrivateScoringPipeline:
    def __init__(self):
        print("Initializing Quota-Optimized Private Scoring Pipeline...")
        self.config = ScraperConfig()
        self.session_manager = SessionManager(self.config)
        self.endpoint_manager = EndpointManager()
        self.executor = EndpointExecutor(self.session_manager, self.endpoint_manager)
        
        # Load only private endpoints
        files = glob.glob(os.path.join("inputs", "curl_commands", "private", "*.py"))
        for file in files:
            if "__init__" in file:
                continue
            name = os.path.basename(file).replace('.py', '')
            with open(file, 'r', encoding='utf-8') as f:
                content = f.read()
                if "curl " in content:
                    self.endpoint_manager.parse_curl_command(name, content)
        
    def _private_execute(self, endpoint_name, payload_str):
        config = self.endpoint_manager.get_endpoint(endpoint_name)
        if not config:
            raise Exception(f"Endpoint {endpoint_name} not found in private registry.")
            
        url = config["url_template"]
        method = config["method"]
        headers = config.get("headers", {})
        
        sanitized_headers = {k: v for k, v in headers.items() if k.lower() not in [
            "user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
            "sec-ch-ua-full-version-list", "sec-ch-ua-arch", "sec-ch-ua-bitness"
        ]}
        
        cookies = config.get("cookies", {})
        
        response = self.session_manager.request(
            method=method, 
            url=url, 
            headers=sanitized_headers, 
            cookies=cookies,
            data=payload_str.encode('utf-8')
        )
        return response.text

    def run_scoring(self, seed_keyword):
        print(f"\n--- Phase 1: Free Discovery for '{seed_keyword}' ---")
        
        base_dir = os.path.join("data", "private_pipelines", "scoring_runs", seed_keyword.replace(" ", "_"))
        os.makedirs(base_dir, exist_ok=True)
        
        # 1. Hit req_1 (/enqueue)
        try:
            req_1_payload = json.dumps({"keyword": seed_keyword})
            enqueue_resp = self._private_execute("req_1", req_1_payload)
            
            enqueue_data = json.loads(enqueue_resp)
            
            extracted_terms = []
            def extract_terms_recursive(node):
                if isinstance(node, dict):
                    if "searchTerm" in node and "searchVolume" in node and "avgTotalListings" in node:
                        extracted_terms.append(node)
                    for k, v in node.items():
                        extract_terms_recursive(v)
                elif isinstance(node, list):
                    for item in node:
                        extract_terms_recursive(item)
            
            extract_terms_recursive(enqueue_data)
            
            # If no terms are found, it's likely an async cache miss
            if not extracted_terms:
                run_id = enqueue_data.get("runId")
                if run_id:
                    print(f"[-] Cache miss! Etsy started async run (runId: {run_id}).")
                    print(f"[-] We must poll the /poll endpoint to get the results, but we don't have the cURL for it yet!")
                else:
                    print("[-] Failed to find any keywords in the payload.")
                return
                
            print(f"[+] Discovered {len(extracted_terms)} free keywords!")
            
            # 2. Phase 2: Local Scoring
            print(f"\n--- Phase 2: Local Scoring ---")
            scored_candidates = []
            
            for term_data in extracted_terms:
                term = term_data.get("searchTerm")
                vol = term_data.get("searchVolume")
                supply = term_data.get("avgTotalListings")
                cvr = term_data.get("cvr", 0)
                
                if vol is None or supply is None:
                    continue
                    
                # Gate 1: CVR must be Typical (2) or higher
                if cvr < 2:
                    continue
                    
                # Gate 2: Ignore extreme long tail with zero supply or weird negative supply
                if supply <= 0:
                    continue
                    
                demand_supply_ratio = vol / supply
                
                scored_candidates.append({
                    "searchTerm": term,
                    "searchVolume": vol,
                    "avgTotalListings": supply,
                    "cvr": cvr,
                    "opportunity_score": demand_supply_ratio
                })
                
            # Rank candidates by highest opportunity score
            scored_candidates = sorted(scored_candidates, key=lambda x: x["opportunity_score"], reverse=True)
            
            print(f"[+] Filtered down to {len(scored_candidates)} highly qualified candidates.")
            
            # Save the full ranked list
            with open(os.path.join(base_dir, "ranked_candidates.json"), "w", encoding="utf-8") as f:
                json.dump(scored_candidates, f, indent=4)
            
            if not scored_candidates:
                print("[-] No candidates passed the CVR gating. Aborting.")
                return
                
            # 3. Phase 3: Sniper Execution
            print(f"\n--- Phase 3: Sniper Execution (Quota Preservation) ---")
            top_candidate = scored_candidates[0]
            winner_term = top_candidate["searchTerm"]
            
            print(f"[!] WINNER: '{winner_term}'")
            print(f"    Volume: {top_candidate['searchVolume']}, Supply: {top_candidate['avgTotalListings']}")
            print(f"    Score : {top_candidate['opportunity_score']:.6f}")
            print(f"    Burning 1 quota point to fetch 365-day chart...")
            
            req_3_payload = json.dumps({
                "search_terms": [winner_term],
                "days": 365,
                "include_trendline": True,
                "include_wow_data": True,
                "include_search_volume": True,
                "include_avg_total_listings": True
            })
            
            try:
                chart_resp = self._private_execute("req_3", req_3_payload)
                safe_term = "".join(c for c in winner_term if c.isalnum() or c in (' ', '_', '-')).replace(" ", "_")
                
                with open(os.path.join(base_dir, f"WINNER_{safe_term}_365days.json"), "w", encoding="utf-8") as f:
                    f.write(chart_resp)
                    
                print(f"[+] Successfully extracted 365-day chart for '{winner_term}'")
            except Exception as e:
                print(f"[-] Failed chart for {winner_term}: {e}")
                    
        except Exception as e:
            print(f"[-] Pipeline Error: {e}")


if __name__ == "__main__":
    pipeline = PrivateScoringPipeline()
    seed = "anniversary gift"
    pipeline.run_scoring(seed)
    print("\n--- QUOTA-OPTIMIZED PIPELINE COMPLETE ---")
