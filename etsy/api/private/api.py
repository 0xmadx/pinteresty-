import json
import time
import urllib.parse
from core.guards import soft_parse
from core.request_cache import (RequestCache, TTL_METERED, TTL_TREND_SERIES)
from core.session_manager import SessionManager
from core.endpoints_manager import EndpointManager
from core.settings import ScraperConfig

class EtsyPrivateAPI:
    def __init__(self, cache=None):
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        self.manager = EndpointManager()
        # Shared cache-with-TTL. The metered endpoints matter most here: a hit saves
        # scarce daily quota, not just latency. Injectable for tests.
        self.cache = cache or RequestCache()
        
        # Load the base headers, cookies, and shop_id from the .env file (synced by the Chrome Extension)
        try:
            import os
            from dotenv import load_dotenv
            load_dotenv()
            
            # 1. Shop ID
            self.shop_id = os.getenv("ETSY_SHOP_ID")
            if not self.shop_id:
                raise ValueError("ETSY_SHOP_ID not found in .env. Please run the Chrome Extension on your Etsy Shop Manager.")
                
            # 2. CSRF Token
            csrf_token = os.getenv("ETSY_CSRF_TOKEN")
            if not csrf_token:
                raise ValueError("ETSY_CSRF_TOKEN not found in .env. Please run the Chrome Extension on your Etsy Shop Manager.")
            
            self.headers = {
                "x-csrf-token": csrf_token,
                "accept": "*/*",
                "content-type": "application/json"
            }
            
            # 3. Cookies
            import json
            cookie_json = os.getenv("ETSY_COOKIES")
            if cookie_json:
                self.cookies = json.loads(cookie_json)
            else:
                self.cookies = {}
            
        except Exception as e:
            print(f"Failed to initialize API: {e}")
            self.cookies = {}
            self.headers = {}
            self.shop_id = None

    def get_results_data(self, query):
        """Fetches the master payload (volume, supply, cvr bucket, median price, top 20 listings).

        TTL_METERED (7 days): this is the most accurate source in the system — real
        search volume, real CVR, real median price. It was cached for 30 days on the
        belief that it is quota-limited; no quota has ever been observed here, and these
        are the numbers that move, so it is re-read at roughly the batch cadence instead.
        """
        def _fetch():
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{self.shop_id}/marketplace-insights/results-data?query={encoded_query}&search_term_hash=&search_trigger=similar_term"
            resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)
            if resp.status_code == 200:
                return resp.json()
            print(f"[-] results-data failed: {resp.status_code}")
            return None

        return self.cache.get_or_fetch(f"results_data_{query.replace(' ', '_')}",
                                       TTL_METERED, _fetch, source="etsy_private")

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
        """Enqueues an LLM keyword job multiple times to extract a massive, deduplicated list of edges.

        TTL_METERED (30 days): each call runs `iterations` enqueue+poll rounds, so a cache
        hit saves a large batch of requests, not one. The keyword graph is stable.
        """
        return self.cache.get_or_fetch(
            f"similar_keywords_{keyword.replace(' ', '_')}", TTL_METERED,
            lambda: self._fetch_similar_keywords(keyword, max_retries, iterations),
            source="etsy_private")

    def _fetch_similar_keywords(self, keyword, max_retries, iterations):
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
                    # A 200 whose body will not parse is not the same as "still working" —
                    # it used to fall through to the next attempt and, once retries ran
                    # out, return silently with fewer keywords than the crawl asked for.
                    # Recorded now, so a shape change surfaces instead of shrinking the
                    # result set.
                    with soft_parse("private.poll_response", keyword=keyword):
                        p_data = p_resp.json()
                        if p_data and "results" in p_data:
                            results = p_data["results"]
                            for r in results:
                                q = r.get("query")
                                if q and q not in seen_queries:
                                    seen_queries.add(q)
                                    all_results.append(r)
                            break # Break the poll loop on success
                elif p_resp.status_code == 202:
                    # 202 Accepted means still processing
                    continue
                else:
                    print(f"[-] poll failed: {p_resp.status_code}")
                    break
        
        if all_results:
            print(f"  [+] Extracted a total of {len(all_results)} deduplicated edges!")
            return all_results

        print("[-] Failed to fetch any similar keywords.")
        return None

    def get_trending_terms(self, taxonomy_id=199):
        """
        Fetches category-level trending keywords (does NOT consume daily quota).

        TTL_TREND_SERIES (7 days): trending terms are a weekly-scale signal, so re-fetching
        more often buys nothing — the same reasoning that fixes the Pinterest T-3 keys.
        """
        def _fetch():
            url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{self.shop_id}/marketplace-insights/trending-search-terms-v2?taxonomy_id={taxonomy_id}"
            resp = self.session.request("GET", url, headers=self.headers, cookies=self.cookies)
            if resp.status_code == 200:
                return resp.json()
            print(f"[-] trending-search-terms-v2 failed: {resp.status_code}")
            return None

        return self.cache.get_or_fetch(f"trending_terms_{taxonomy_id}", TTL_TREND_SERIES,
                                       _fetch, source="etsy_private")
