import json
import time
import urllib.parse
from core.session_manager import SessionManager
from core.endpoints_manager import EndpointManager
from core.settings import ScraperConfig

class EtsyPrivateAPI:
    def __init__(self):
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        self.manager = EndpointManager()
        
        # Load the base headers and cookies from a known good req (e.g. req_5 which is enqueue)
        try:
            with open('private/endpoints/req_5.py', 'r', encoding='utf-8') as f:
                self.manager.parse_curl_command("base", f.read())
            req_config = self.manager.get_endpoint("base")
            self.cookies = req_config.get("cookies", {})
            self.headers = req_config.get("headers", {})
            
            # Clean headers to let session_manager handle TLS impersonation
            self.headers = {k: v for k, v in self.headers.items() if k.lower() not in [
                "user-agent", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
                "sec-ch-ua-full-version-list", "sec-ch-ua-arch", "sec-ch-ua-bitness", "content-length"
            ]}
            
            # Extract shop ID from the URL
            url = req_config.get("url_template", "")
            import re
            match = re.search(r'/shop/(\d+)/', url)
            self.shop_id = match.group(1) if match else "56057851"
            
        except Exception as e:
            print(f"Failed to initialize API: {e}")
            self.cookies = {}
            self.headers = {}
            self.shop_id = "56057851"

    def get_results_data(self, query):
        """Fetches the master payload (volume, supply, cvr bucket, median price, top 20 listings)"""
        # --- Cache Check ---
        import os
        cache_file = f"etsy/data/cache/results_data_{query.replace(' ', '_')}.json"
        if os.path.exists(cache_file):
            print(f"  [+] Loading results_data for '{query}' from cache.")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
                
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{self.shop_id}/marketplace-insights/results-data?query={encoded_query}&search_term_hash=&search_trigger=similar_term"
        
        resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)
        if resp.status_code == 200:
            data = resp.json()
            # Save to cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
            
        print(f"[-] results-data failed: {resp.status_code}")
        return None

    def get_chart_series(self, terms, days=365):
        """Fetches the time-series chart data (burns quota if cold!)"""
        url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{self.shop_id}/marketplace-insights/chart-series-data"
        payload = {
            "search_terms": terms if isinstance(terms, list) else [terms],
            "days": days,
            "include_trendline": False,
            "include_wow_data": True,
            "include_search_volume": True,
            "include_avg_total_listings": True
        }
        
        resp = self.session.request("POST", url, headers=self.headers, cookies=self.cookies, data=json.dumps(payload))
        if resp.status_code == 200:
            return resp.json()
        print(f"[-] chart-series-data failed: {resp.status_code}")
        return None

    def get_similar_keywords(self, keyword, max_retries=10, iterations=10):
        """Enqueues an LLM keyword job multiple times to extract a massive, deduplicated list of edges."""
        # --- Cache Check ---
        import os
        cache_file = f"etsy/data/cache/similar_keywords_{keyword.replace(' ', '_')}.json"
        if os.path.exists(cache_file):
            print(f"  [+] Loading similar_keywords for '{keyword}' from cache.")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
                
        enqueue_url = f"https://www.etsy.com/api/v3/ajax/shop/{self.shop_id}/marketplace-insights/llm-exploratory-keywords/search/enqueue"
        payload = {"keyword": keyword}
        
        all_results = []
        seen_queries = set()
        
        for i in range(iterations):
            print(f"  [~] Suggestion LLM Iteration {i+1}/{iterations}...")
            
            resp = self.session.request("POST", enqueue_url, headers=self.headers, cookies=self.cookies, data=json.dumps(payload))
            if resp.status_code not in [200, 202]:
                print(f"[-] enqueue failed: {resp.status_code}")
                continue
                
            data = resp.json()
            
            # If Etsy returned a backend cache, it might just be the exact same results. We'll still deduplicate them.
            if data.get("cachedData"):
                results = data["cachedData"].get("results", [])
                for r in results:
                    q = r.get("query")
                    if q and q not in seen_queries:
                        seen_queries.add(q)
                        all_results.append(r)
                continue
                
            run_id = data.get("runId")
            thread_id = data.get("threadId")
            
            if not run_id or not thread_id:
                print("[-] No runId/threadId returned from enqueue.")
                continue
                
            poll_url = f"https://www.etsy.com/api/v3/ajax/shop/{self.shop_id}/marketplace-insights/llm-exploratory-keywords/search/poll"
            poll_payload = {
                "run_id": run_id,
                "thread_id": thread_id,
                "search_term": keyword
            }
            
            # Polling Loop
            for attempt in range(max_retries):
                time.sleep(1.5) # Polite backoff
                p_resp = self.session.request("POST", poll_url, headers=self.headers, cookies=self.cookies, data=json.dumps(poll_payload))
                
                if p_resp.status_code == 200:
                    try:
                        p_data = p_resp.json()
                        if p_data and "results" in p_data:
                            results = p_data["results"]
                            for r in results:
                                q = r.get("query")
                                if q and q not in seen_queries:
                                    seen_queries.add(q)
                                    all_results.append(r)
                            break # Break the poll loop on success
                    except Exception:
                        pass
                elif p_resp.status_code == 202:
                    # 202 Accepted means still processing
                    continue
                else:
                    print(f"[-] poll failed: {p_resp.status_code}")
                    break
        
        if all_results:
            print(f"  [+] Extracted a total of {len(all_results)} deduplicated edges!")
            # Save to cache
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(all_results, f)
            return all_results
            
        print("[-] Failed to fetch any similar keywords.")
        return None

    def get_trending_terms(self, taxonomy_id=199):
        """
        Fetches category-level trending keywords (does NOT consume daily quota).
        """
        import os
        cache_file = f"etsy/data/cache/trending_terms_{taxonomy_id}.json"
        if os.path.exists(cache_file):
            print(f"  [+] Loading trending terms for category '{taxonomy_id}' from cache.")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
                
        url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{self.shop_id}/marketplace-insights/trending-search-terms-v2?taxonomy_id={taxonomy_id}"
        resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)
        
        if resp.status_code == 200:
            data = resp.json()
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            return data
            
        print(f"[-] trending-search-terms-v2 failed: {resp.status_code}")
        return None
