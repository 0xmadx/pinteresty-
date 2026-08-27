import re
import json
import time
import urllib.parse
from core.guards import soft_parse
from etsy.analytics.derivations import parse_price
from core.request_cache import (RequestCache, TTL_METERED, TTL_TREND_SERIES)
from core.session_manager import SessionManager
from core.endpoints_manager import EndpointManager
from core.settings import ScraperConfig

class SessionDown(RuntimeError):
    """A private (seller) endpoint returned 401/403 — the session is stale or absent.

    A distinct type so callers and the operator can tell "your browser is off" apart
    from "the endpoint is broken" or "Etsy said no". This is exactly the confusion that
    once made a working endpoint look like a bug: the browser was off, the private
    session was dead, and the empty result read like a code failure. 401 = stale
    session, never a rate limit (that is 429). See CLAUDE.md and docs 10_session_layer.
    """


def _money(value):
    """"$17.10" -> 17.10. None when there is no number to read.

    Etsy ships the median price band as formatted strings. Returning None rather than
    0.0 on failure matters: 0.0 would be a free product, which passes every margin
    floor and turns an unreadable price into a guaranteed `go` (N-02).
    """
    if value is None or isinstance(value, (int, float)):
        return value
    cleaned = re.sub(r"[^\d.]", "", str(value))
    if not cleaned or cleaned.count(".") > 1:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


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
        # Floats, because the profit model multiplies these. Etsy sends the median band
        # as FORMATTED STRINGS ("$17.10"), the same shape trap as review counts arriving
        # as "1459" — a consumer doing arithmetic on it raises, and one doing string
        # work on it silently produces nonsense. Coerced here rather than at the caller
        # so there is one place that knows the wire shape.
        "price_low": _money(_pick(median, "median_price_low", "medianPriceLow")),
        "price_high": _money(_pick(median, "median_price_high", "medianPriceHigh")),
        # The formatted originals, for display without re-formatting.
        "price_low_text": _pick(median, "median_price_low", "medianPriceLow"),
        "price_high_text": _pick(median, "median_price_high", "medianPriceHigh"),
        # A DIFFERENT, wider band Etsy also ships as floats. Kept distinct rather than
        # used as a fallback: median 17.10-20.90 against bar 12.67-25.33 for the same
        # term are not interchangeable, and substituting one would move the margin.
        "price_bar_low": _pick(median, "median_price_bar_low_float", "medianPriceBarLowFloat"),
        "price_bar_high": _pick(median, "median_price_bar_high_float", "medianPriceBarHighFloat"),
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


def parse_chart_series(chart):
    """The 12-month volume CURVE per term — the half of this response nobody read.

    Every caller of `get_chart_series` reads `term_summaries` and discards `series`,
    which carries a full monthly search-volume curve for each term. The system has
    been paying for Etsy's own seasonality on every batch call and throwing it away
    (D-45). One live response, `days=365`:

        christmas ornament   peak Nov 163,930 · trough Feb 1,758   -> 93.2x
        mom necklace         peak Dec  16,683 · trough Jun 5,698   ->  2.9x

    ⚠️ **The last bucket is PARTIAL.** The response carries
    `is_last_bucket_partial: true`, and the final point is the current month counted
    so far. Read naively it is a collapse — `felt garland`'s apparent trough was the
    partial month, not a real low. That flag rides on every returned curve so no
    consumer can miss it.

    ⚠️ **Terms Etsy cannot size are OMITTED, not zeroed.** Asked for four terms, the
    response carried three; `linen apron` was simply absent. A missing term is
    unmeasured (N-02) and callers get no entry rather than an empty curve.
    """
    chart = chart or {}
    partial = bool(_pick(chart, "is_last_bucket_partial", "isLastBucketPartial",
                         default=False))
    out = {}
    for entry in _pick(chart, "series", default=[]) or []:
        term = _pick(entry, "search_term", "searchTerm")
        # Only the volume series is a demand curve; the endpoint can carry others.
        if not term or _pick(entry, "series_type", "seriesType") != "search_volume":
            continue
        points = []
        for p in entry.get("points") or []:
            value = p.get("value")
            if value is None:
                continue
            points.append({"label": p.get("label"), "value": value,
                           "timestamp": p.get("timestamp")})
        if points:
            out[term] = {"points": points, "last_is_partial": partial,
                         "granularity": _pick(chart, "granularity", default=None)}
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
    # `search_term` is the spelling the LLM keyword endpoint actually uses, in both the
    # enqueue's `cached_data.results` and the poll body. It was missing here, so even
    # after the enqueue/poll reads were fixed every edge still resolved to None and the
    # recursion produced nothing — the snake_case bug at a third layer.
    for key in ("search_term", "searchTerm", "query", "term", "keyword"):
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
            # A stale seller session (browser/extension off) surfaces here as 401/403.
            # Raising rather than returning None stops an entire hunt from silently
            # producing "nothing winnable" when the real cause is a dead session —
            # the mis-diagnosis this guard exists to prevent.
            if resp.status_code in (401, 403):
                raise SessionDown(
                    f"results-data returned {resp.status_code} — seller session stale or "
                    f"absent. Is the browser + extension running? Check: "
                    f"python -m core.vault_status")
            print(f"[-] results-data failed: {resp.status_code}")
            return None

        return self.cache.get_or_fetch(f"results_data_{query.replace(' ', '_')}",
                                       TTL_METERED, _fetch, source="etsy_private")

    def get_chart_series(self, terms, days=365):
        """Fetches the time-series chart data.

        ⚠️ Callers historically read ONLY `term_summaries` from this response and threw
        `series` away — a free 12-month volume curve per term, on every call the whole
        project has ever made. Use `parse_chart_series()` to get it (D-45).

        `include_trendline` is left False deliberately: probed 2026-08-20 against
        `christmas ornament`, True and False return byte-identical key structures. The
        flag does nothing on this endpoint, so setting it would only imply it did.
        """
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
            # 401/403 on a private call is a stale or absent SELLER session, not a
            # broken endpoint — almost always the browser/extension is not running so
            # the vault holds no live etsy_private cookies. Say that plainly and stop,
            # rather than looping ten times and returning None as if the code were
            # wrong. This is the failure that got mis-diagnosed as an endpoint bug once
            # already; the message now points at the real cause and the check that
            # confirms it. (CLAUDE.md: 401 = stale session, not 429.)
            if resp.status_code in (401, 403):
                raise SessionDown(
                    f"etsy_private returned {resp.status_code} — the seller session is "
                    f"stale or absent. Is the browser + extension running on a Shop "
                    f"Manager tab? Confirm with: python -m core.vault_status")
            if resp.status_code not in [200, 202]:
                print(f"[-] enqueue failed: {resp.status_code}")
                continue
                
            data = resp.json()

            # ⚠️ THE SNAKE_CASE BUG, ONE FUNCTION DEEPER. Verified on the wire
            # 2026-08-15: the enqueue response is
            #     {"run_id": "...", "thread_id": "...", "cached_data": null}
            # and this code read runId / threadId / cachedData, so it printed
            # "No runId/threadId returned" ten times and returned None — every time,
            # since the endpoint was written. Recursive keyword expansion has therefore
            # NEVER produced an edge, which is why `ssr_graph_pipeline` could not grow
            # past its seed.
            #
            # The poll payload below already used snake_case, so the request side was
            # right and only the response side was wrong — exactly the asymmetry that
            # made the original D-24 bug survive three explanations.
            cached = _pick(data, "cached_data", "cachedData")
            if cached:
                # A backend cache hit may repeat earlier results; dedupe regardless.
                for r in cached.get("results", []) or []:
                    q = edge_term(r)
                    if q and q not in seen_queries:
                        seen_queries.add(q)
                        all_results.append(r)
                continue

            run_id = _pick(data, "run_id", "runId")
            thread_id = _pick(data, "thread_id", "threadId")

            if not run_id or not thread_id:
                print(f"[-] enqueue returned neither run_id nor runId; keys were "
                      f"{sorted(data)}")
                continue
                
            poll_url = f"https://www.etsy.com/api/v3/ajax/shop/{{shop_id}}/marketplace-insights/llm-exploratory-keywords/search/poll"
            poll_payload = {
                "run_id": run_id,
                "thread_id": thread_id,
                "search_term": keyword
            }
            
            # Polling Loop.
            #
            # Probed live 2026-08-15: the LLM run is genuinely asynchronous and takes a
            # few seconds to produce anything. Two behaviours the old loop got wrong:
            #   * a poll that arrives before the run is ready returns 400 with a `null`
            #     body — NOT 202 — and the old loop treated any non-200/202 as fatal
            #     and broke on the first one, so it never reached the ready state
            #   * a flat 1.5s backoff polled 400 ten times and gave up; an escalating
            #     wait reached the 200 in two or three tries
            # So 400/202/null are all "still cooking, keep waiting", and only a 200 with
            # a parseable result list ends the loop. A 401/403/429 is a real session or
            # throttle failure and still stops.
            backoff = 2.0
            got_data = False
            for attempt in range(max_retries):
                time.sleep(backoff)
                backoff = min(backoff * 1.4, 8.0)   # 2, 2.8, 3.9, 5.5, 7.7, 8, ...
                p_resp = self.session.request("POST", poll_url, headers=self.headers,
                                              platform="etsy_private",
                                              data=json.dumps(poll_payload))

                if p_resp.status_code in (401, 403, 429):
                    print(f"[-] poll auth/throttle failure: {p_resp.status_code}")
                    break

                if p_resp.status_code == 200 and p_resp.text.strip() not in ("", "null"):
                    # A 200 whose body will not parse is not the same as "still working".
                    # Recorded so a shape change surfaces instead of shrinking the set.
                    with soft_parse("private.poll_response", keyword=keyword):
                        p_data = p_resp.json()
                        # `edge_term`, not r["query"]: the producer keys these on `query`
                        # and older consumers read `searchTerm` — the helper stops them
                        # drifting apart again.
                        results = _pick(p_data or {}, "results", "search_terms")
                        if results:
                            for r in results:
                                q = edge_term(r)
                                if q and q not in seen_queries:
                                    seen_queries.add(q)
                                    all_results.append(r)
                            got_data = True
                            break
                # 400 / 202 / 200-null: the run is not ready yet. Keep polling.

            if not got_data:
                print(f"  [~] run for '{keyword}' did not yield within {max_retries} polls")
        
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
