import json
import urllib.parse
from bs4 import BeautifulSoup
import re
import os
from core.guards import soft_parse
from core.request_cache import RequestCache, TTL_LISTING_TAGS, TTL_SERP
from core.session_manager import SessionManager
from core.settings import ScraperConfig
from etsy.analytics import product_type

# A page this small is an interstitial, a challenge or an error — not a listing. Every
# parser below refuses it rather than reporting "no badges found", because an empty
# read of a blocked page is the shape that quietly writes zeroes into the database.
MIN_LISTING_PAGE_BYTES = 50_000

# Etsy has used several wordings for the cart badge and adds more. Each is tried; if
# the page is healthy and NONE match, that is a parser alert, never an absence.
#
# ⚠️ PROBED 2026-09-01, and the answer was NO. Listing 1864690497 — 7,700 reviews,
# ranked page one for `personalized gift`, a 707KB fully-rendered page — carries
# NEITHER a cart count NOR a "bought in the past 24 hours" badge in its server-side
# HTML. Favourites are there (`54,148 favorites`, linked to that listing's own
# favoriters page, so listing-level and not the shop's total). The cart count the
# operator saw lives on `/cart/?show_cart=<id>`, reached by ADDING TO CART.
#
# That is not reachable here: SessionManager claims a freshly shuffled profile per
# request (session_manager.py -> cookie_vault random.shuffle), so an add and a read
# run as two different buyer identities and the second sees an empty cart. Session
# affinity would mean extending the access layer, which is forbidden.
#
# The patterns stay — they cost nothing, older listings may still render the badge,
# and the canary below distinguishes "no badge" from "reworded badge" if Etsy ever
# puts it back.
_CART_PATTERNS = (
    r"[Ii]n\s+([\d,]+)\s+(?:people[’']s\s+)?carts?",
    r"([\d,]+)\s+(?:people\s+)?(?:have\s+)?(?:this\s+)?in\s+(?:their\s+)?carts?",
)
_FAVORITES_PATTERNS = (
    r"([\d,]+)\s+favorites?\b",
    r"([\d,]+)\s+people\s+(?:have\s+)?favorited",
)
# "23 bought in the past 24 hours" / "23 sold in the last 24 hours".
_BOUGHT_PATTERNS = (
    r"([\d,]+)\s+(?:bought|sold)\s+in\s+the\s+(?:past|last)\s+24\s+hours",
)


def _first_int(html, patterns):
    """First pattern that matches wins; None when none do. Never 0 as a fallback."""
    for pattern in patterns:
        m = re.search(pattern, html or "")
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def parse_listed_on(html):
    """`Listed on Sep 1, 2026` -> `2026-09-01`. None when the page does not say.

    ⚠️⚠️ **THIS IS NOT THE CREATION DATE. It resets on renewal.** Measured 2026-09-01
    on listing 1864690497 (KvYshopUS), which carries **7,700 reviews** and reports
    `Listed on Sep 1, 2026` — that day. Etsy listings auto-renew roughly every four
    months and the displayed date moves with the renewal, so a four-year-old
    best-seller and a genuinely new listing print the same string.

    Read as an age, this number would have called that listing brand new. It is the
    exact shape of failure this project exists to prevent, and the reason the field is
    reported with `age_days_lower_bound` and a renewal flag rather than as "age" —
    see `listing_age()`.

    `core/database.py` was still half right for the wrong reason: it said Etsy does not
    publish a creation date. It does not — but the reason is renewal, not the absence
    of a date on the page, and the date IS on the page and is worth having.

    Returns an ISO date so it sorts and subtracts. A date that does not parse returns
    None rather than today, because "we could not read it" and "it is new" are the two
    readings this must never confuse.
    """
    from datetime import datetime
    m = re.search(r"Listed on\s+([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})", html or "")
    if not m:
        return None
    with soft_parse("listing.listed_on"):
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}",
                                 "%b %d %Y").date().isoformat()
    return None


# Above this, a listing that claims to be days old is claiming something its review
# count contradicts — reviews accrue over months, not hours. Deliberately low: the
# point is to catch an obvious contradiction, not to model review velocity.
RENEWAL_REVIEW_THRESHOLD = 20


def listing_age(listed_on, review_count=None, now=None):
    """Turn a displayed listing date into an age claim honest about renewal.

    The date only ever establishes that the listing is **at least** this old, so the
    output is a LOWER BOUND, never an age. Where the review count contradicts a
    young-looking date, the bound is reported as uninformative rather than quietly
    passed on as a honeymoon signal.

    `honeymoon` is therefore three-valued and never a bare boolean:
      True   — young AND nothing contradicts it
      False  — old enough that it plainly is not in a honeymoon
      None   — the date says young and the reviews say otherwise: RENEWED, unknown
    """
    from datetime import date, datetime
    if not listed_on:
        return {"listed_on": None, "age_days_lower_bound": None, "honeymoon": None,
                "basis": "unmeasured",
                "note": "no date on the page — not the same as a new listing"}

    today = now or date.today()
    try:
        parsed = datetime.strptime(listed_on, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return {"listed_on": listed_on, "age_days_lower_bound": None,
                "honeymoon": None, "basis": "unparseable"}

    days = (today - parsed).days
    looks_new = days <= 90
    contradicted = looks_new and (review_count or 0) >= RENEWAL_REVIEW_THRESHOLD

    if contradicted:
        return {
            "listed_on": listed_on, "age_days_lower_bound": days,
            "review_count": review_count, "honeymoon": None,
            "basis": "renewal_suspected",
            "note": f"date says {days}d old but the listing carries {review_count} "
                    f"reviews — Etsy resets this on auto-renewal, so the true age is "
                    f"UNKNOWN and certainly greater. Not a honeymoon candidate.",
        }
    return {
        "listed_on": listed_on, "age_days_lower_bound": days,
        "review_count": review_count, "honeymoon": looks_new,
        "basis": "derived",
        "note": "a LOWER bound — Etsy resets this date on auto-renewal, so the "
                "listing is at least this old and may be far older. Nothing here "
                "can prove a listing is new; it can only fail to contradict it.",
    }


def parse_listing_live(html, listing_id=None):
    """Cart count, favourites and the 24h bought badge — the volatile trio.

    Threshold-gated, every one of them: Etsy renders these only above some level, so
    a missing badge is *below the threshold*, never zero (N-02). Each value is None
    unless read, with a `*_present` boolean beside it so a consumer can tell "we
    looked and there was no badge" from "we never looked".
    """
    html = html or ""
    healthy = len(html) >= MIN_LISTING_PAGE_BYTES
    if not healthy:
        # Refuse rather than report three absences from a page that is not a listing.
        return {"listing_id": listing_id, "basis": "page_too_small",
                "bytes": len(html), "in_cart": None, "favorites": None,
                "bought_24h": None,
                "note": f"page under {MIN_LISTING_PAGE_BYTES} bytes — blocked or an "
                        f"interstitial, not a quiet listing. Nothing is claimed."}

    in_cart = _first_int(html, _CART_PATTERNS)
    favorites = _first_int(html, _FAVORITES_PATTERNS)
    bought = _first_int(html, _BOUGHT_PATTERNS)

    # The canary. A healthy page where nothing matched is far more likely to be a
    # reworded badge than three simultaneously quiet signals — and a silent regex
    # failure is indistinguishable from a quiet listing, which is precisely the
    # failure mode this project exists to prevent.
    alert = healthy and in_cart is None and favorites is None and bought is None
    return {
        "listing_id": listing_id, "basis": "measured", "bytes": len(html),
        "in_cart": in_cart, "in_cart_present": in_cart is not None,
        "favorites": favorites, "favorites_present": favorites is not None,
        "bought_24h": bought, "bought_24h_present": bought is not None,
        "parser_alert": alert,
        "note": ("Page loaded fine and NOT ONE known badge wording matched. Suspect a "
                 "reworded badge before believing this listing is quiet — check the "
                 "HTML and widen the patterns."
                 if alert else
                 "Absent = below Etsy's display threshold, NOT zero (N-02). "
                 "bought_24h is an upper bound on a single day and must not be x30'd "
                 "into a month without clamping against the shop's measured rate."),
    }


class EtsyPublicAPI:
    def __init__(self, cache=None):
        self.config = ScraperConfig()
        self.session = SessionManager(self.config)
        # Shared cache-with-TTL, replacing the two hand-rolled file caches this client
        # used to keep (which never expired). Injectable so tests pass a temp one.
        self.cache = cache or RequestCache()
        
        self.headers = {
            'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'accept-language': 'en-US,en;q=0.9',
            'user-agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

    def get_public_search(self, query, filters: dict = None):
        """Fetches the public search SERP and extracts supply, ranked organic IDs and card metrics.

        Etsy does not ship a `window.__INITIAL_STATE__` blob on this page. The numbers we
        need are split across three places, all of which `parse_search_html` handles:
          * a props JSON in an inline script  -> total supply + the ranked organic id list
          * hidden `<form>` inputs, one per card -> id, title, url, prices, ad/organic flag
          * the card markup itself             -> rating, review count, shop name and age
        Only the first 12 of the 48 page-1 slots are server-rendered; the rest are lazy
        loaded through the `neu/specs/listingCards` POST (see filter_relevant_aftersearch.py).
        """
        filters = filters or {}

        # Cache key from query + sorted filters, so the same search is asked once per TTL
        # window regardless of dict ordering. TTL_SERP (1 day): rankings shift, but not
        # hour to hour. A failed fetch returns None and is not cached (see request_cache).
        suffix = "".join(f"_{k}_{str(v).lower()}" for k, v in sorted(filters.items()))
        key = f"public_search_{query.replace(' ', '_')}{suffix}"

        def _fetch():
            params = {"q": query}
            params.update(filters)
            # Explicit is often appended by default on Etsy searches
            if "explicit" not in params:
                params["explicit"] = "1"
            url = f"https://www.etsy.com/search?{urllib.parse.urlencode(params)}"
            resp = self.session.request("GET", url, headers=self.headers, platform="etsy")
            if resp.status_code != 200:
                print(f"[-] public search failed: {resp.status_code}")
                return None
            return self.parse_search_html(resp.text, query) or None

        return self.cache.get_or_fetch(key, TTL_SERP, _fetch, source="etsy_public")

    @staticmethod
    def _parse_count(text):
        """'(4.2k)' -> 4200, '(19.8k)' -> 19800, '(312)' -> 312."""
        if not text:
            return None
        m = re.search(r'([\d.,]+)\s*([km]?)', text.strip().lower().strip('()'))
        if not m:
            return None
        try:
            value = float(m.group(1).replace(',', ''))
        except ValueError:
            return None
        return int(value * {'k': 1_000, 'm': 1_000_000}.get(m.group(2), 1))

    @staticmethod
    def _price_float(text):
        if not text:
            return None
        m = re.search(r'([\d,]+\.?\d*)', text)
        return float(m.group(1).replace(',', '')) if m else None

    def parse_search_html(self, html, query):
        """Turns a raw SERP page into the supply/competition payload. Pure function, no I/O."""
        soup = BeautifulSoup(html, 'html.parser')

        def first_int(pattern):
            m = re.search(pattern, html)
            return int(m.group(1)) if m else None

        # --- Page-level supply signals -------------------------------------------------
        result = {
            "query": query,
            # Total competing listings for the query. This is the free, unlimited
            # equivalent of Marketplace Insights' metered `avg_total_listings`.
            "total_results": first_int(r'"organic_listings_count"\s*:\s*(\d+)'),
            "results_per_page": first_int(r'"result_count"\s*:\s*(\d+)'),
            "current_page": first_int(r'"initial_current_page"\s*:\s*(\d+)'),
            "total_pages": first_int(r'"initial_total_pages"\s*:\s*(\d+)'),
            "organic_listing_ids": [],
            "cards": [],
        }

        # The ranked organic id list for this page, in rank order.
        #
        # This used to require `"result_count"` within 200 characters BEFORE the
        # array, on the theory that proximity identified the page-level list. It
        # does not: measured on the wire 2026-08-20, the nearest preceding keys are
        # `bucket_id` / `user_id` / `is_async`, and `result_count` is nowhere near.
        # So the pattern never matched and `organic_listing_ids` was ALWAYS EMPTY —
        # silently, because an empty list is a plausible value for a page with no
        # results.
        #
        # The array itself is the identifying feature: per-card analytics payloads
        # carry a single id, the page-level one carries the full ranking (41 on
        # "personalized towel", against 6 organic cards that render server-side).
        # Taking the longest match is what distinguishes them, and that check was
        # already here — it was the proximity constraint that was wrong.
        for m in re.finditer(r'"listing_ids"\s*:\s*\[([\d,\s]+)\]', html):
            ids = [int(x) for x in m.group(1).split(',') if x.strip()]
            if len(ids) > len(result["organic_listing_ids"]):
                result["organic_listing_ids"] = ids

        # --- Card-level competition signals --------------------------------------------
        # The hidden add-to-cart form nested inside each card carries the clean fields;
        # the surrounding markup carries the social proof. The form has to be read from
        # within the card and not from a global id map: a listing can hold both an
        # organic slot and an ad slot on the same page, and a map would collapse the two.
        for card in soup.select('div.v2-listing-card'):
            lid = card.get('data-listing-id')
            if not lid:
                continue
            meta = {}
            for form in card.find_all('form'):
                inputs = {i.get('name'): i.get('value') for i in form.find_all('input', attrs={'name': True})}
                if 'organic_listings_count' in inputs:
                    meta = inputs
                    break
            text = card.get_text(' ', strip=True)
            stars = card.select_one('clg-static-review-stars')
            age = re.search(r'(\d+)\s+years?\s+on\s+Etsy', text)
            shop = card.select_one('.clickable-shop-name')

            price = meta.get('formatted_discounted_price') or meta.get('formatted_original_price')
            result["cards"].append({
                "listing_id": lid,
                "title": meta.get('listing_title'),
                "url": meta.get('listing_url'),
                "shop_id": card.get('data-shop-id'),
                "shop_name": shop.get_text(strip=True) if shop else None,
                # `listing_source` is Etsy's own label; the visible "Ad from shop" string
                # is the fallback for cards that ship without the hidden form.
                "is_ad": meta.get('listing_source') == 'ads' or 'Ad from shop' in text,
                "shop_years_on_etsy": int(age.group(1)) if age else None,
                "rating": float(stars['rating']) if stars and stars.get('rating') else None,
                "review_count": self._parse_count(stars.get('review-count-text')) if stars else None,
                "price": self._price_float(price),
                "original_price": self._price_float(meta.get('formatted_original_price')),
                "percent_discount": int(meta['percent_discount']) if meta.get('percent_discount') else None,
                "free_shipping": 'Free shipping' in text,
                "star_seller": bool(card.select_one('[data-star-seller-badge]')),
                "image_url": meta.get('listing_image_url'),
            })

        return result if result["total_results"] is not None or result["cards"] else None

    # Etsy runs TWO autocomplete endpoints and they do not agree. Measured 2026-09-01
    # on the same queries, same session:
    #
    #   suggestions_ajax.php                 badge reel -> 14    halloween -> 16
    #   /api/v3/ajax/public/search/suggestions           -> 10               -> 10
    #
    # and each carries terms the other misses (`badge reel personalized`, `vintage`,
    # `accessories` only on ajax; `halloween`, `charms`, `miffy` only on v3). Reading
    # one endpoint would silently halve the candidate set, so both are read and
    # merged. Two public requests, buyer session, no seller cost.
    _SUGGEST_AJAX = "https://www.etsy.com/suggestions_ajax.php"
    _SUGGEST_V3 = "https://www.etsy.com/api/v3/ajax/public/search/suggestions"

    def get_search_suggestions(self, query):
        """Etsy's OWN search-box autocomplete — what buyers actually type.

        **Why this is not `similar_keywords`.** That one is
        `llm-exploratory-keywords`: LLM-GENERATED adjacencies, on the SELLER session,
        ~10 requests per expansion. This is the real query stream — the phrases
        buyers type into the box — on the BUYER session, 2 requests, no seller risk.
        Use this to find candidates and spend the private tier only to size them.

        Measured 2026-09-01, `badge reel` -> nurse · medical · healthcare · funny ·
        cute · charms · halloween · fall · personalized · vintage. It surfaced the
        same healthcare cluster and the same seasonal hooks that a paid LLM expansion
        of that term found, for none of the seller-account cost.

        ⚠️ **No volume and no supply.** These are candidate STRINGS. A suggestion is
        evidence people type it, never evidence it is winnable — size them through
        `compare` (3 terms per request) before ranking anything.

        ⚠️ **The ordering is Etsy's, and Etsy is not neutral (B-01).** A curated
        sample of real queries, not a demand ranking.

        ⚠️ **They do NOT rotate.** Ten consecutive calls returned byte-identical
        lists — and because `SessionManager` shuffles a different buyer profile per
        request, that was ten identities getting one answer, so it is not per-user
        personalisation either. Calling repeatedly to "collect more" buys nothing.
        Day-to-day drift is a separate question and needs storing, not re-calling.

        Wire facts, each probed rather than assumed:
          * `version` is INERT — dropped or set to garbage, the same 14 rows come
            back. Nothing here expires, so no build string has to be kept current.
          * `extras` is NOT inert — dropping it costs 3 of 14 rows.
          * `limit`/`language`/`country`/`lang` are inert on the v3 endpoint.
          * ajax mixes in a shop-name row that is raw HTML (`<span class=...>`), not
            a query. It is dropped; counted, it would pose as a keyword.
          * `simplified_queries` (v3) is ALWAYS EMPTY — the same category as
            `similar_search_terms` and `market_gap_recommendations`. Do not build on it.
        """
        import json as _json

        def _clean(rows, out, source, seen):
            for row in rows or []:
                q = (row or {}).get("query")
                if not q or "<" in q:          # the shop-name row is markup
                    continue
                if q.strip().lower() == (query or "").strip().lower():
                    continue                   # Etsy echoes the input as row 0
                if q not in seen:
                    seen[q] = source
                    out.append(q)

        def _fetch():
            out, seen = [], {}
            extras = _json.dumps({"expt": "sft_nortn", "lang": "en-US", "extras": []})
            params = {"extras": extras, "search_query": query, "search_type": "all",
                      "pathname": "/search", "previous_query": query}
            url = self._SUGGEST_AJAX + "?" + urllib.parse.urlencode(params)
            ajax_n = v3_n = 0
            # Success is tracked from the STATUS, never from the row count. Keyed off
            # rows, "both endpoints errored" and "both answered and Etsy has no
            # completions for this term" collapse into one state — and they are
            # opposite claims: one is our failure, one is a fact about the term (N-02).
            ok_ajax = ok_v3 = False
            with soft_parse("search.suggestions_ajax", query=query):
                resp = self.session.request("GET", url, headers=self.headers,
                                            platform="etsy")
                if resp.status_code == 200:
                    ok_ajax = True
                    before = len(out)
                    _clean(resp.json().get("results"), out, "ajax", seen)
                    ajax_n = len(out) - before

            url2 = self._SUGGEST_V3 + "?" + urllib.parse.urlencode({"query": query})
            with soft_parse("search.suggestions_v3", query=query):
                resp2 = self.session.request("GET", url2, headers=self.headers,
                                             platform="etsy")
                if resp2.status_code == 200:
                    ok_v3 = True
                    before = len(out)
                    _clean(resp2.json().get("results"), out, "v3", seen)
                    v3_n = len(out) - before

            if not ok_ajax and not ok_v3:
                # NEITHER endpoint answered. An empty list here would read as "Etsy
                # has no suggestions for this term" — a claim about the market — when
                # the truth is we never got an answer (N-02).
                return None
            return {"query": query, "suggestions": out, "sources": seen,
                    "from_ajax_only": ajax_n, "added_by_v3": v3_n,
                    # A partial answer is not a full one, and the caller must be able
                    # to tell: with one endpoint down the candidate set is roughly
                    # halved, and a short list would otherwise read as a narrow niche.
                    "endpoints_ok": [n for n, ok in (("ajax", ok_ajax), ("v3", ok_v3))
                                     if ok],
                    "partial": not (ok_ajax and ok_v3),
                    "basis": "measured" if (ok_ajax and ok_v3) else "partial"}

        # TTL_SERP (1 day): autocomplete tracks what is being typed NOW, which is the
        # whole reason to read it. A long TTL would turn a live signal into a stale one.
        return self.cache.get_or_fetch(f"suggest2_{query}", TTL_SERP, _fetch,
                                       source="etsy_public")

    def get_listing_data(self, listing_id):
        """Scrapes a public listing page: tags, breadcrumb, type, age, broadened queries.

        TTL_LISTING_TAGS (30 days): a seller's tags and category rarely change, so this
        is the cheapest thing in the system to reuse.

        ⚠️ **Everything here must be slow-moving or immutable.** Volatile numbers — the
        cart count, favourites, today's badge — belong in `get_listing_live()`, which
        never caches. A month-old cart count served as current is a freshness bug that
        looks exactly like a fresh reading.

        Cache key is versioned (`_v2`). Adding a field without bumping it would leave
        30-day-old entries returning None for the new keys, and a *measured* value
        reading as *unmeasured* is N-02 inverted — just as wrong, and harder to spot.
        """
        def _fetch():
            url = f"https://www.etsy.com/listing/{listing_id}"
            resp = self.session.request("GET", url, headers=self.headers, platform="etsy")
            if resp.status_code != 200:
                return None
            html = resp.text
            soup = BeautifulSoup(html, 'html.parser')

            result = {
                "breadcrumb": [],
                "tags": [],
                # Product type from the SAME html already fetched for tags — zero extra
                # calls. The markers (a personalization form field, "Digital download")
                # were being discarded with the rest of the page. D-22 makes this
                # mandatory: type decides the margin floor a candidate is judged against.
                "product_type": product_type.detect_from_html(html).get("product_type"),
                # Etsy's own broadened/expanded query set for this listing — see the
                # tag block below. None until proven otherwise, never [] (N-02).
                "broadened_queries": None,
                # When the listing went live. This is the honeymoon signal, and it is
                # on HTML we were already paying for.
                "listed_on": parse_listed_on(html),
            }

            # 1. Extract Breadcrumb from LD+JSON
            # Several LD+JSON blocks per page; only one is the BreadcrumbList, so most
            # iterations legitimately find nothing. soft_parse keeps that tolerance but
            # records the failures, so a changed schema is distinguishable from the
            # ordinary misses instead of both yielding a silently empty list.
            for script in soup.find_all('script', type='application/ld+json'):
                with soft_parse("listing.breadcrumb_ld_json", listing_id=listing_id):
                    data = json.loads(script.string)
                    if data.get('@type') == 'BreadcrumbList':
                        items = data.get('itemListElement', [])
                        # Sort by position just in case
                        items.sort(key=lambda x: x.get('position', 0))
                        result['breadcrumb'] = [item.get('name') for item in items if item.get('name')]

            # 2. Extract Tags from Listzilla JSON
            for script in soup.find_all('script', type='text/json', attrs={'data-neu-spec-placeholder-data': '1'}):
                with soft_parse("listing.listzilla_tags", listing_id=listing_id):
                    data = json.loads(script.string)
                    if data.get('spec_name') == 'Listzilla_ApiSpecs_Tags_Landing':
                        tags = data.get('args', {}).get('click_queries', [])
                        # Etsy allows 13 tags, so the first 13 are the seller's own.
                        result['tags'] = tags[:13]
                        # The TAIL is Etsy's own broadened/expanded queries for this
                        # listing — what the marketplace thinks it is also about. It
                        # was being truncated away. It is the thing that separates a
                        # genuine accidental keyword (Etsy ranks a listing for a term
                        # its seller never claimed) from Etsy's synonym layer merely
                        # doing its job, and those need different responses.
                        result['broadened_queries'] = tags[13:]
            return result

        # _v2: `listed_on` and `broadened_queries` were added 2026-09-01. Reusing the
        # old key would serve 30-day-old entries that lack them, and their absence
        # would read as "this listing has no date" rather than "this blob predates the
        # field".
        return self.cache.get_or_fetch(f"public_listing_v2_{listing_id}",
                                       TTL_LISTING_TAGS, _fetch, source="etsy_public")

    def get_listing_live(self, listing_id):
        """The volatile demand signals: cart count, favourites, today's badge.

        Deliberately a SEPARATE call from `get_listing_data` even though it reads the
        same page, because these move hourly and tags do not. `TTL_LIVE = 0` — never
        cached, exactly as `core/request_cache.py` intended when it named the tier
        "stock, 'N in cart', today's badge".

        ⚠️ **Every number here is threshold-gated: Etsy renders these badges only above
        some level.** So a missing badge means *below the display threshold*, never
        zero (N-02), and every field is None-by-default with a `*_present` flag beside
        it. `derivations.py` documents the same trap for `daily_sales`: a 0 there means
        "no badge rendered" far more often than it means "nothing sold", and treating
        the two alike manufactures a dead listing or a runaway one.

        ⚠️ If the page loads and NONE of the known wordings match, that is reported as
        `parser_alert`, not as an absence. Etsy rewords these badges, and a reworded
        badge failing silently to `None` is indistinguishable from a genuinely quiet
        listing — the single most dangerous shape in this codebase.
        """
        url = f"https://www.etsy.com/listing/{listing_id}"
        resp = self.session.request("GET", url, headers=self.headers, platform="etsy")
        if resp.status_code != 200:
            return {"listing_id": listing_id, "basis": "fetch_failed",
                    "status": resp.status_code}
        return parse_listing_live(resp.text, listing_id=listing_id)
