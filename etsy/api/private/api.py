import json
import time
import urllib.parse
from core.guards import soft_parse
from etsy.analytics.derivations import parse_price
from core.request_cache import (RequestCache, TTL_METERED, TTL_TREND_SERIES)
from core.session_manager import SessionManager
from core.endpoints_manager import EndpointManager
from core.settings import ScraperConfig

def _pick(d, *names, default=None):
    """First present key out of several spellings."""
    for n in names:
        if isinstance(d, dict) and d.get(n) is not None:
            return d[n]
    return default


def parse_results_data(payload):
    """Normalise a `results-data` response into a stable shape.

    ⚠️ THE BUG THIS EXISTS TO KILL. Etsy returns **snake_case**; every consumer in
    this repo was reading **camelCase**, so each got None and wrote nothing:

        API                                  code was reading
        search_volume                        searchVolume
        avg_total_listings                   avgTotalListings
        query_cvr                            cvr
        competitive_price_data               competitivePriceData
        competitive_research_listing_cards   competitiveResearchListingCards
        listing_cards[].number_of_reviews    numberOfReviews

    Verified live 2026-08-12: "mom necklace" returns 12,867 searches, 351,677
    listings, CVR 0.000256, $17.10-$20.90, 20 competitor cards — all of which the
    pipelines were reading as empty. That, not the quota and not the broken import,
    is why every table had 0 rows.

    Both spellings are accepted so a future API change in either direction cannot
    silently zero the system again.
    """
    payload = payload or {}
    stats = payload.get("stats") or {}
    price_block = payload.get("competitive_price_data") or payload.get("competitivePriceData") or {}
    median = _pick(price_block, "search_term_median_price", "searchTermMedianPrice", default={}) or {}
    cards_box = (payload.get("competitive_research_listing_cards")
                 or payload.get("competitiveResearchListingCards") or {})
    raw_cards = _pick(cards_box, "listing_cards", "listingCards", default=None)
    if raw_cards is None:
        raw_cards = cards_box if isinstance(cards_box, list) else []
    wow = payload.get("wow_data") or {}
    quota = payload.get("quota_data") or {}

    return {
        "keyword": _pick(stats, "search_term", "searchTerm"),
        # query_cvr is the real rate; `cvr` is an ordinal bucket and is often 0.
        "volume": _pick(stats, "search_volume", "searchVolume"),
        "supply": _pick(stats, "avg_total_listings", "avgTotalListings"),
        "cvr": _pick(stats, "query_cvr", "queryCvr"),
        "cvr_bucket": stats.get("cvr"),
        "price_low": _pick(median, "median_price_low", "medianPriceLow"),
        "price_high": _pick(median, "median_price_high", "medianPriceHigh"),
        # Etsy's OWN week-over-week momentum — free, and previously unread.
        "wow_change": wow.get("value"),
        "wow_direction": wow.get("trend_direction"),
        "listings": [normalise_listing_card(c) for c in (raw_cards or [])],
        # Reported by the API itself. Observed to stay at 15/15 across repeated
        # distinct calls, i.e. this endpoint does not consume it (D-14).
        "quota_total": quota.get("total_quota"),
        "quota_remaining": quota.get("remaining_quota"),
        "quota_reached": payload.get("is_quota_reached"),
        "similar_terms": payload.get("similar_search_terms"),
        "market_gap": payload.get("market_gap_recommendations"),
    }


def normalise_listing_card(card):
    """One competitor listing, in the shape the analytics layer expects.

    `review_count` is the name `survivorship.survivor_bound` reads; the API calls it
    `number_of_reviews`.
    """
    card = card or {}

    # The API sends review counts as STRINGS ("1459") and price as a nested dict.
    # survivor_bound compares review_count with `> 0`, and the profit model needs a
    # float — both would have silently mis-handled the raw shapes.
    raw_reviews = _pick(card, "number_of_reviews", "numberOfReviews")
    try:
        reviews = int(str(raw_reviews).replace(",", "")) if raw_reviews is not None else None
    except (TypeError, ValueError):
        reviews = None   # unreadable is unknown, never 0 (N-02)

    price_block = card.get("price")
    if isinstance(price_block, dict):
        price_text = _pick(price_block, "formatted_price", "formattedPrice")
        is_discounted = price_block.get("is_discounted")
    else:
        price_text, is_discounted = price_block, None

    return {
        "listing_id": _pick(card, "id", "listing_id", "listingId"),
        "title": card.get("title"),
        "review_count": reviews,
        "rating": card.get("rating"),
        "shop_name": _pick(card, "shop_name", "shopName"),
        "price_text": price_text,
        "price": parse_price(price_text),
        "is_discounted": is_discounted,
        "url": _pick(card, "listing_url", "listingUrl"),
        "is_star_seller": _pick(card, "is_star_seller", "isStarSeller"),
        "badge_text": _pick(card, "badge_text", "badgeText"),
    }


def parse_term_summaries(chart):
    """Rows out of a `chart-series-data` response.

    Same defect: the API returns `term_summaries` with `search_volume` /
    `avg_total_listings`; the callers read `termSummaries` / `searchVolume`, so the
    batch measurement step produced an empty list on every run.
    """
    chart = chart or {}
    rows = _pick(chart, "term_summaries", "termSummaries", default=[]) or []
    out = []
    for s in rows:
        out.append({
            "keyword": _pick(s, "search_term", "searchTerm"),
            "volume": _pick(s, "search_volume", "searchVolume"),
            "supply": _pick(s, "avg_total_listings", "avgTotalListings"),
            "wow_change": (s.get("wow_data") or {}).get("value"),
        })
    return out


def edge_term(edge):
    """The keyword out of one `get_similar_keywords` edge, whichever key it uses.

    ⚠️ The producer and the consumers disagreed. `_fetch_similar_keywords` de-duplicates
    on `r["query"]` and appends the whole object, while `master_niche_finder` and
    `private_recursive_spider` both read `e["searchTerm"]`. If the response carries only
    `query`, every consumer gets None, no term is ever added to the frontier, and the
    crawl silently stops at the seed — which looks identical to "the API returned
    nothing". Accepting either key removes the guess; callers must use this rather than
    indexing a key directly.
    """
    if not isinstance(edge, dict):
        return None
    for key in ("searchTerm", "query", "term", "keyword"):
        value = edge.get(key)
        if value:
            return value
    return None


class EtsyPrivateAPI:
    def __init__(self, cache=None):
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        self.manager = EndpointManager()
        # Shared cache-with-TTL. The metered endpoints matter most here: a hit saves
        # scarce daily quota, not just latency. Injectable for tests.
        self.cache = cache or RequestCache()
        
        self.headers = {
            "accept": "*/*",
            "content-type": "application/json"
        }

    def get_results_data(self, query):
        """Fetches the master payload (volume, supply, cvr bucket, median price, top 20 listings).

        TTL_METERED (7 days): this is the most accurate source in the system — real
        search volume, real CVR, real median price. It was cached for 30 days on the
        belief that it is quota-limited; no quota has ever been observed here, and these
        are the numbers that move, so it is re-read at roughly the batch cadence instead.
        """
        def _fetch():
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{{shop_id}}/marketplace-insights/results-data?query={encoded_query}&search_term_hash=&search_trigger=similar_term"
            resp = self.session.request("GET", url, headers=self.headers, platform="etsy_private")
            if resp.status_code == 200:
                return resp.json()
            print(f"[-] results-data failed: {resp.status_code}")
            return None

        return self.cache.get_or_fetch(f"results_data_{query.replace(' ', '_')}",
                                       TTL_METERED, _fetch, source="etsy_private")

    def get_chart_series(self, terms, days=365):
        """Fetches the time-series chart data (burns quota if cold!)"""
        url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{{shop_id}}/marketplace-insights/chart-series-data"
        payload = {
            "search_terms": terms if isinstance(terms, list) else [terms],
            "days": days,
            "include_trendline": False,
            "include_wow_data": True,
            "include_search_volume": True,
            "include_avg_total_listings": True
        }
        
        resp = self.session.request("POST", url, headers=self.headers, platform="etsy_private", data=json.dumps(payload))
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
        enqueue_url = f"https://www.etsy.com/api/v3/ajax/shop/{{shop_id}}/marketplace-insights/llm-exploratory-keywords/search/enqueue"
        payload = {"keyword": keyword}

        all_results = []
        seen_queries = set()

        for i in range(iterations):
            print(f"  [~] Suggestion LLM Iteration {i+1}/{iterations}...")
            
            resp = self.session.request("POST", enqueue_url, headers=self.headers, platform="etsy_private", data=json.dumps(payload))
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
                
            poll_url = f"https://www.etsy.com/api/v3/ajax/shop/{{shop_id}}/marketplace-insights/llm-exploratory-keywords/search/poll"
            poll_payload = {
                "run_id": run_id,
                "thread_id": thread_id,
                "search_term": keyword
            }
            
            # Polling Loop
            for attempt in range(max_retries):
                time.sleep(1.5) # Polite backoff
                p_resp = self.session.request("POST", poll_url, headers=self.headers, platform="etsy_private", data=json.dumps(poll_payload))
                
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
            url = f"https://www.etsy.com/api/v3/ajax/bespoke/shop/{{shop_id}}/marketplace-insights/trending-search-terms-v2?taxonomy_id={taxonomy_id}"
            resp = self.session.request("GET", url, headers=self.headers, platform="etsy_private")
            if resp.status_code == 200:
                return resp.json()
            print(f"[-] trending-search-terms-v2 failed: {resp.status_code}")
            return None

        return self.cache.get_or_fetch(f"trending_terms_{taxonomy_id}", TTL_TREND_SERIES,
                                       _fetch, source="etsy_private")
