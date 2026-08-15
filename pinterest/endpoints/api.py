"""Cache-first Pinterest Trends client.

Mirrors the shape of `private/endpoints/api.py` and `public/endpoints/api.py`: one class, one
method per endpoint, every call checked against a local cache first. Pinterest has no quota,
but it does rate-limit and every response is `cache-control: private`, so the cache is the only
thing between a re-run and another 300-800ms round trip per call.

Behaviour here is pinned by `pinterest/tests/test_live_endpoints.py` — read that before
changing any of the header or parameter handling.
"""
import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path

import httpx

from core.request_cache import RequestCache, TTL_TAXONOMY, TTL_TREND_SERIES
from .constants import (FASHION_TRIPLE, ORDER_BY, PREDICTED_DAYS, SHOPPING_DAYS_RANGE,
                        SHOPPING_REGIONS, SPOTLIGHT_EVENT, SPOTLIGHT_REGIONS,
                        TOP_LIMIT_MAX, VERTICALS)
from .series_store import SeriesStore

ROOT = Path(__file__).resolve().parents[2]
COOKIE_FILE = ROOT / "pinterest_cookies.json"
CACHE_DIR = ROOT / "pinterest" / "data" / "cache"
BASE = "https://trends.pinterest.com"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


def _slug(value):
    """Filename-safe slug.

    Truncating alone is not safe for cache keys: two different 50-term lists share their first
    120 characters and would collide onto one cache file, silently returning the wrong series.
    Anything long keeps a readable head plus a hash of the full value.
    """
    text = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    if len(text) <= 120:
        return text
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]
    return f"{text[:100]}_{digest}"


class PinterestTrendsAPI:
    @staticmethod
    def _session_cookies():
        """Pinterest cookies from the vault, falling back to the legacy .env variable.

        The vault is tried first because it is what the Chrome extension actually
        fills now. The fallback is kept rather than deleted so this is not a breaking
        change for a machine still running the old setup — but if both are empty the
        original error is re-raised, since a Pinterest call with no session is a
        refusal, not something to paper over.
        """
        try:
            from core.cookie_vault import RedisCookieVault
            from core.settings import ScraperConfig
            account = RedisCookieVault(ScraperConfig()).get_valid_account("pinterest")
            cookies = account.get("cookies_json")
            if isinstance(cookies, dict) and cookies:
                return cookies
        except Exception:
            # Vault unreachable or empty — fall through to the legacy path so the
            # operator gets the original, actionable message rather than a Redis
            # stack trace.
            pass

        from pinterest.core.client import get_pinterest_cookies
        return get_pinterest_cookies()

    def __init__(self, cache=True, delay=0.6, store=True, cookies=None):
        # D-28 moved sessions into the Redis vault, but only the Etsy tier was
        # migrated: this class still called get_pinterest_cookies(), which reads
        # PINTEREST_COOKIES from .env — a variable nothing writes any more. So the
        # whole Pinterest tier raised on construction while the vault held working
        # profiles the entire time.
        #
        # This composes the pieces that already exist (RedisCookieVault) rather than
        # adding session mechanics; `pinterest/core/client.py` stays untouched and is
        # still the fallback, so an operator with a populated .env is unaffected.
        self.cookies = cookies or self._session_cookies()
        self.cache = cache
        self.delay = delay
        self._end_date = None
        # Per-term series store. related_terms/prefix_match hand back a full weekly series
        # for every term they suggest; without this it is discarded and re-bought from
        # /metrics/. Set store=False to force every series to come off the wire.
        self.store = SeriesStore() if store else None
        self.saved_requests = 0
        # The shared request cache, replacing bespoke JSON files under CACHE_DIR. Kept in
        # a pinterest-scoped DB so a cache flush here never touches the Etsy cache.
        self._backend = RequestCache(db_path=str(CACHE_DIR / "request_cache.db"))
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        self.client = httpx.Client(
            base_url=BASE,
            cookies=self.cookies,
            timeout=httpx.Timeout(30.0),
            headers={
                "accept": "application/json, text/javascript, */*; q=0.01",
                "accept-language": "en-US,en;q=0.9",
                "referer": f"{BASE}/search?country=US",
                "user-agent": USER_AGENT,
                "x-requested-with": "XMLHttpRequest",
            },
        )

    # -- plumbing ----------------------------------------------------------------------
    @staticmethod
    def _check_region(region):
        """Shopping accepts only US, CA and GB+IE — the wider search region groups 400 here."""
        if region not in SHOPPING_REGIONS:
            raise ValueError(f"shopping region must be one of {SHOPPING_REGIONS}; "
                             f"{region!r} returns 400")

    @staticmethod
    def _check_not_vertical(ids):
        """Level-1 vertical ids are valid only in parent_product_categories."""
        bad = [i for i in ids if str(i) in VERTICALS]
        if bad:
            raise ValueError(f"{bad} are level-1 verticals — valid only as "
                             f"parent_product_categories, never as product_category_id(s). "
                             f"The server returns 400, and one bad id fails the whole call.")

    # Prefix -> TTL. Weekly trend series expire in a week (belt-and-suspenders on top of
    # the date-in-key fix that already closed T-3); demographics and taxonomy move slowly.
    _TTL_BY_PREFIX = (
        ("metrics_", TTL_TREND_SERIES), ("related_", TTL_TREND_SERIES),
        ("prefix_", TTL_TREND_SERIES), ("trends_", TTL_TREND_SERIES),
        ("cat_metrics_", TTL_TREND_SERIES), ("top_categories_", TTL_TREND_SERIES),
        ("demographics_", TTL_TAXONOMY), ("cat_demographics_", TTL_TAXONOMY),
        ("product_categories", TTL_TAXONOMY), ("top_products_", TTL_TAXONOMY),
        ("featured_", TTL_TAXONOMY), ("editorial_", TTL_TAXONOMY),
        ("moments_", TTL_TAXONOMY),
    )

    def _ttl_for(self, key):
        for prefix, ttl in self._TTL_BY_PREFIX:
            if key.startswith(prefix):
                return ttl
        return TTL_TREND_SERIES   # unknown -> the conservative weekly default

    def _cached(self, key):
        # self.cache stays the on/off flag callers pass; the backend does the storage.
        # Migrated off bespoke never-expiring JSON files onto the shared request cache,
        # so these entries expire and finally feed the runlog cache_hits/misses counters.
        if not self.cache:
            return None
        data = self._backend.get(key, self._ttl_for(key))
        if data is not None:
            print(f"  [+] cache hit: {key}")
        return data

    def _store(self, key, data):
        return self._backend.put(key, data, source="pinterest")

    def _get(self, path, **params):
        time.sleep(self.delay)
        r = self.client.get(path, params=params)
        if r.status_code != 200:
            print(f"[-] {path} failed: {r.status_code} {r.text[:120]}")
            return None
        return r.json()

    def _api_resource(self, inner_url, payload=None, source_url="/?country=US",
                      handler="trends/index.js", expect=None):
        """The /resource/ApiResource/get/ envelope.

        `x-pinterest-pws-handler` is MANDATORY — without it the whole family returns
        403 Invalid Resource Request. Its value is never validated. Returns
        resource_response.data with the 63-key client_context (which carries account PII)
        dropped.
        """
        body = {"options": {"url": inner_url, "data": payload or {}}, "context": {}}
        time.sleep(self.delay)
        r = self.client.get(
            "/resource/ApiResource/get/",
            params={"source_url": source_url,
                    "data": json.dumps(body, separators=(",", ":"))},
            headers={"x-pinterest-pws-handler": handler,
                     "x-pinterest-source-url": source_url},
        )
        if r.status_code != 200:
            print(f"[-] {inner_url} failed: {r.status_code} {r.text[:120]}")
            return None
        wrapper = r.json().get("resource_response", {})
        if expect and wrapper.get("endpoint_name") != expect:
            print(f"[-] {inner_url}: expected handler {expect}, got {wrapper.get('endpoint_name')}")
            return None
        return wrapper.get("data")

    # -- 1. the date everything hangs off ------------------------------------------------
    def latest_available_date(self):
        """Pinterest's most recent complete data week. Never hardcode a date."""
        if self._end_date:
            return self._end_date
        data = self._get("/latest_available_date/")
        self._end_date = (data or {}).get("date")
        return self._end_date

    # -- 2. discovery --------------------------------------------------------------------
    def top_trends(self, preset="growing", country="US", interests=None, age=None,
                   gender=None, moments=None, keywords=None, end_date=None, limit=None):
        """The discovery table. `preset` is a key of constants.PRESETS.

        Only presets 'growing' and 'seasonal' come back velocity-sorted; 'top_monthly' and
        'top_yearly' are volume-sorted, so row order is not momentum order on those.

        `limit` is `numTermsToReturn`. The UI never sends anything but 50 and the table is
        fixed at 50 on screen, but the server accepts up to 100 (101 -> 400), and the first
        50 rows of a 100-row response are byte-identical to the default call. So passing
        limit=100 doubles discovery breadth for the same single request and never re-ranks
        what was already there. Left at None (server default 50) so cached tables and the
        history archive stay comparable unless a caller opts in.
        """
        from .constants import PRESETS, TOP_TRENDS_LIMIT_MAX

        cfg = PRESETS[preset]
        end_date = end_date or self.latest_available_date()
        params = {"lookbackWindow": cfg["lookbackWindow"], "endDate": end_date,
                  "country": country, "trendsPreset": cfg["trendsPreset"]}
        if limit is not None:
            if not 1 <= limit <= TOP_TRENDS_LIMIT_MAX:
                raise ValueError(f"numTermsToReturn must be 1..{TOP_TRENDS_LIMIT_MAX}; "
                                 f"{limit} returns 400 (verified: 101, 120, 150, 199 all fail)")
            params["numTermsToReturn"] = limit
        if interests:
            params["l1interests"] = ",".join(interests)
        if age:
            params["ageBuckets"] = age
        if gender:
            params["gender"] = gender
        if moments:
            params["moments"] = ",".join(moments) if isinstance(moments, list) else moments
        if keywords:
            params["keywordsToInclude"] = keywords

        key = "trends_" + _slug("_".join(str(v) for v in params.values()))
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._get("/top_trends_filtered/", **params)
        return self._store(key, data) if data else None

    # -- 3. curves -----------------------------------------------------------------------
    def metrics(self, terms, days=90, country="US", end_date=None, normalize_group=False,
                predicted_days=0, age=None, gender=None, store_bypass=False):
        """Weekly series. Takes up to ~50 terms in ONE call — always batch.

        `shouldMock` is deliberately never sent: shouldMock=true returns 52 points of zeros
        with a 200 status. Omitting it behaves as false.

        With predicted_days > 0 the trailing weeks are FORECAST, and their `count` carries the
        prediction rather than 0. Use split_forecast() to separate them.
        """
        from .constants import SEARCH_METRICS_DAYS

        if days not in SEARCH_METRICS_DAYS:
            raise ValueError(f"search /metrics/ accepts days in {SEARCH_METRICS_DAYS}; "
                             f"{days} returns 400 (verified: 45 and 60 both fail)")
        if isinstance(terms, str):
            terms = [terms]
        end_date = end_date or self.latest_available_date()

        # The store holds plain observed series only. A demographic slice, a group
        # normalization or a forecast is a different number for the same term, so those
        # always go to the wire.
        # store_bypass forces the wire, so a test can obtain ground truth to check the
        # local derivations against.
        plain = not (age or gender or normalize_group or predicted_days or store_bypass)
        served = {}
        if plain and self.store:
            served, terms = self.store.split(terms, days, country, end_date)
            if served:
                print(f"  [=] {len(served)} series served locally, {len(terms)} to fetch")
            if not terms:
                self.saved_requests += 1
                return [{"term": t, "counts": [{"count": c} for c in v["counts"]],
                         "growth_rates": v["growth"] or {}, "has_prediction": False,
                         "_source": v["source"], "_precision": v["precision"]}
                        for t, v in served.items()]

        params = {"terms": ",".join(terms), "country": country, "end_date": end_date,
                  "days": days, "aggregation": 2,
                  "normalize_against_group": "true" if normalize_group else "false",
                  "predicted_days": predicted_days}
        if age:
            params["age_bucket"] = age
        if gender:
            params["gender"] = gender

        key = f"metrics_{_slug(end_date)}_{days}_{predicted_days}_{_slug('_'.join(terms))}"
        data = self._cached(key)
        if data is None:
            data = self._get("/metrics/", **params)
            if data:
                self._store(key, data)
        if data and plain and self.store and days == 365:
            # Only a full-year response is stored: it is the widest window, so every
            # shorter one slices out of it, and growth_rates ride along with it.
            self.store.harvest_metrics(data, country, end_date)
        if not data:
            return None
        return list(data) + [
            {"term": t, "counts": [{"count": c} for c in v["counts"]],
             "growth_rates": v["growth"] or {}, "has_prediction": False,
             "_source": v["source"], "_precision": v["precision"]}
            for t, v in served.items()]

    @staticmethod
    def split_forecast(series):
        """(observed, forecast) for one /metrics/ series. Forecast points are the ones
        carrying prediction bounds; their `count` is predicted, not measured."""
        pts = series.get("counts", [])
        observed = [p for p in pts if p.get("predictedUpperBoundNormalizedCount") is None]
        forecast = [p for p in pts if p.get("predictedUpperBoundNormalizedCount") is not None]
        return observed, forecast

    # -- 4. expansion --------------------------------------------------------------------
    def related_terms(self, term, country="US", end_date=None, lookback=365):
        """Co-searched terms — topically similar, need not share a word. Returns ~5 rows,
        so this refines a corpus rather than growing one."""
        end_date = end_date or self.latest_available_date()
        key = f"related_{_slug(country)}_{_slug(term)}_{_slug(end_date)}"
        data = self._cached(key)
        if data is None:
            data = self._get("/related_terms/", requestTerm=term, country=country,
                             endDate=end_date, aggregation=2, lookback=lookback)
            if data:
                self._store(key, data)
        # The 53-point counts[] here is byte-identical to /metrics/?days=365 (verified on
        # every row of a 5-term response), so harvesting it is free and exact.
        if data and self.store:
            self.store.harvest(data, "related", country, end_date)
        return data or None

    def prefix_match(self, query, country="US", end_date=None):
        """Autocomplete — terms that START with the query, each with 52 weeks of history."""
        end_date = end_date or self.latest_available_date()
        key = f"prefix_{_slug(country)}_{_slug(query)}_{_slug(end_date)}"
        data = self._cached(key)
        if data is None:
            data = self._get("/prefix_match/", query=query, country=country)
            if data:
                self._store(key, data)
        # 52 points == metrics[1:] renormalized to its own peak, so this is stored at a
        # lower provenance rank and never overwrites an exact series.
        if data and self.store:
            self.store.harvest(data, "prefix", country, end_date)
        return data or None

    def demographics(self, terms, country="US", end_date=None, days=365):
        """Age and gender split per term. No Etsy equivalent exists."""
        if isinstance(terms, str):
            terms = [terms]
        end_date = end_date or self.latest_available_date()
        key = f"demographics_{_slug(country)}_{_slug('_'.join(terms))}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._get("/demographics/", terms=",".join(terms), country=country,
                         end_date=end_date, days=days)
        return self._store(key, data) if data else None

    # -- 5. the seasonal calendar --------------------------------------------------------
    def moments_calendar(self, country="US"):
        """Takeoff/peak dates and phase per holiday, zipped from five index-parallel arrays.

        Coverage, cross-checked against the live UI on 2026-08-07: single-country codes
        (US CA BR MX IT ES FR DE CO AR) return moments WITH full takeoff/peak timestamps;
        three grouped codes (DE+AT+CH, AU+NZ, MX+AR+CO+CL) get exactly ONE moment with
        peak_ms only (takeoff_ms stays null even there); four more grouped codes (GB+IE,
        NL+BE+LU, SE+DK+FI+NO, IT+ES+PT+GR+MT) return names with every date field null;
        JP returns an empty list; AU, NL, IE, GB and ZZ all 400 — there is no standalone
        code for any of these, so there is no single-country UK view to fall back to.
        Callers that need dates must check for null rather than assume a region either
        works or 400s. See constants.MOMENTS_DATED_REGIONS / _PARTIAL_ / _UNDATED_.

        Still wider than the spotlight module. The moment vocabulary is PER REGION, and this
        is the authoritative source for which `moments=` values `/top_trends_filtered/`
        will accept there: `moments=oktoberfest&country=US` is a 400, not an empty result.

        Zipping matters: grouped regions return the arrays alphabetised while single
        regions do not, so the ordering is not stable across regions.
        """
        key = f"moments_{_slug(country)}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(f"/ads/v4/trends/moment/available/{country}",
                                  expect="get_available_moments_handler")
        if not data:
            return None
        names = data.get("moments", [])
        out = []
        for i, name in enumerate(names):
            peak = (data.get("peaks") or [{}] * len(names))[i]
            hist = (data.get("historical_peaks") or [{}] * len(names))[i]
            out.append({
                "moment": name,
                "phase": (data.get("phase_labels") or [None] * len(names))[i],
                "takeoff_ms": peak.get("takeoff_timestamp_millis"),
                "peak_ms": peak.get("peak_timestamp_millis"),
                "peak_length_days": peak.get("peak_length_in_days"),
                "last_year_takeoff_ms": hist.get("takeoff_timestamp_millis"),
                "last_year_peak_ms": hist.get("peak_timestamp_millis"),
                "next_occurrence_ms": (data.get("moment_next_occurrence_timestamps")
                                       or [None] * len(names))[i],
            })
        return self._store(key, out)

    # -- 6. shopping ---------------------------------------------------------------------
    def product_categories(self, country="US"):
        """The 383-entry id -> name dictionary. Fetch once, cache forever."""
        key = "product_categories"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource("/ads/v4/trends/shopping/product_categories",
                                  source_url=f"/shopping?country={country}",
                                  handler="trends/shopping.js",
                                  expect="get_product_categories")
        return self._store(key, data.get("categories", {})) if data else None

    def top_categories(self, country="US", event="OUTBOUND_CLICK", parents=None,
                       limit=TOP_LIMIT_MAX, offset=0, order_by="PCT_CHANGE_MOM",
                       order="DESC", age=None, gender=None, end_date=None):
        """Ranked categories. `event`, `ranking_method` and `end_date` are all required by the
        server (400 if omitted) — they are always sent.

        Defaults to the full set rather than the UI's 20: there are only 44 categories on
        OUTBOUND_CLICK (35 on ENGAGEMENT, 18 on SAVE) and the server caps `limit` at 522, so
        one call gets everything. Omitting `limit` entirely would give you 8.

        `parents` accepts the level-1 vertical ids; an empty list means all.
        """
        self._check_region(country)
        if not 1 <= limit <= TOP_LIMIT_MAX:
            raise ValueError(f"limit must be 1..{TOP_LIMIT_MAX}; {limit} returns 400")
        if order_by not in ORDER_BY:
            raise ValueError(f"order_by must be one of {ORDER_BY}")
        end_date = end_date or self.latest_available_date()
        payload = {"event": event, "ranking_method": "GROWTH", "end_date": end_date,
                   "age_bucket": age or [], "gender": gender or [],
                   "limit": limit, "order_by": order_by, "order": order}
        if parents:
            payload["parent_product_categories"] = parents
        if offset:
            payload["offset"] = offset
        key = (f"top_categories_{_slug(country)}_{_slug(event)}_{_slug(order_by)}_"
               f"{limit}_{offset}_{_slug('_'.join(parents or []))}_{_slug(end_date)}")
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(f"/ads/v4/trends/shopping/product_categories/top/{country}",
                                  payload, source_url=f"/shopping/?country={country}",
                                  handler="trends/shopping.js",
                                  expect="get_filtered_product_categories")
        return self._store(key, data.get("ordered_values", [])) if data else None

    def category_metrics(self, category_ids, country="US", event="OUTBOUND_CLICK", days=180,
                         predicted_days=0, age=None, gender=None, end_date=None):
        """Weekly curves per category. Far looser than the search /metrics/: any `days` in
        1..730 works (7->1 point, 30->5, 90->13, 365->53, 730->105).

        Unlike the UI, which always sends empty arrays, `age`/`gender` here are accepted AND
        applied — the curve genuinely changes, so shopping demand can be sliced by demographic.
        """
        self._check_region(country)
        ids = [str(i) for i in ([category_ids] if isinstance(category_ids, (str, int))
                                else category_ids)]
        self._check_not_vertical(ids)
        if not SHOPPING_DAYS_RANGE[0] <= days <= SHOPPING_DAYS_RANGE[1]:
            raise ValueError(f"days must be {SHOPPING_DAYS_RANGE[0]}..{SHOPPING_DAYS_RANGE[1]}")
        if predicted_days not in PREDICTED_DAYS:
            raise ValueError(f"predicted_days must be one of {PREDICTED_DAYS}; "
                             f"7 returns 500 and 29/92 return 400")
        end_date = end_date or self.latest_available_date()
        payload = {"product_category_ids": ids, "event": event, "end_date": end_date,
                   "days": days, "age_bucket": age or [], "gender": gender or [],
                   "predicted_days": predicted_days}
        key = (f"cat_metrics_{_slug(country)}_{_slug(event)}_{days}_{predicted_days}_"
               f"{_slug('_'.join(ids))}_{_slug('_'.join((age or []) + (gender or [])))}")
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(
            f"/ads/v4/trends/shopping/product_categories/metrics/{country}", payload,
            source_url=f"/shopping/?country={country}", handler="trends/shopping.js",
            expect="get_product_category_metrics")
        return self._store(key, data.get("values", [])) if data else None

    def category_demographics(self, category_ids, country="US", event="OUTBOUND_CLICK",
                              end_date=None):
        """Age/gender split per category. One bad or vertical id poisons the whole call."""
        self._check_region(country)
        ids = [str(i) for i in ([category_ids] if isinstance(category_ids, (str, int))
                                else category_ids)]
        self._check_not_vertical(ids)
        end_date = end_date or self.latest_available_date()
        key = f"cat_demographics_{_slug(country)}_{_slug(event)}_{_slug('_'.join(ids))}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(
            f"/ads/v4/trends/shopping/product_categories/demographics/{country}",
            {"product_category_ids": ids, "event": event, "end_date": end_date},
            source_url=f"/shopping/?country={country}", handler="trends/shopping.js",
            expect="get_product_category_demographics")
        return self._store(key, data) if data else None

    def top_products(self, category_id, country="US", event="OUTBOUND_CLICK"):
        """Pins driving clicks in a category. merchant_name is often 'Etsy', with the
        competitor's exact listing title — the bridge back into the Etsy pillar."""
        key = f"top_products_{_slug(country)}_{_slug(category_id)}_{_slug(event)}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource("/ads/v4/trends/shopping/product_categories/top_products",
                                  {"product_category_id": str(category_id), "region": country,
                                   "event": event},
                                  source_url=f"/shopping/{category_id}/?country={country}",
                                  handler="trends/shopping.js",
                                  expect="get_trends_top_products")
        return self._store(key, data.get("top_products", [])) if data else None

    def etsy_competitors(self, category_id, country="US", event="OUTBOUND_CLICK"):
        """Only the Etsy pins from a category's top products.

        Etsy's share is sparse and category-dependent — measured 7/38 in Body jewelry, 4/21 in
        Runner rugs, 0 in Area rugs, Bath mats, Candles and Cake decorating, where big-box owns
        the traffic. An empty list is itself a finding: that niche goes to mass retail.
        """
        return [p for p in (self.top_products(category_id, country, event) or [])
                if p.get("merchant_name") == "Etsy"]

    # -- 7. spotlight --------------------------------------------------------------------
    def featured_topics(self, interests=None, country="US"):
        """Editorially curated macro trends. Always 5 topics, everything inline.

        Constraints, all enforced here because the server just 400s:
          * region is US / CA / GB+IE only — unlike moments, which covers ~26 regions
          * the event path segment is hard-wired to SAVE; there is no event switch
          * `interests` takes EXACTLY ONE id, or the Fashion triple, or None for "All".
            Two ids, four ids, or any other three-id combination are all 400.
          * `limit`, `offset`, `end_date`, `age_bucket` and `gender` are accepted and ignored,
            so there is no pagination, date control or demographic filter on this module.

        The response carries name, description, pct_growth_mom, time_series, pins,
        related_search_trends and interests — the UI's expanded card fires no further
        requests, so this one call is the whole feature.
        """
        if country not in SPOTLIGHT_REGIONS:
            raise ValueError(f"spotlight region must be one of {SPOTLIGHT_REGIONS} "
                             f"(moments covers far more); {country!r} returns 400")
        if isinstance(interests, str):
            interests = [interests]
        if interests is not None:
            interests = [str(i) for i in interests]
            if len(interests) != 1 and sorted(interests) != sorted(FASHION_TRIPLE):
                raise ValueError(
                    f"`interests` takes exactly one id, or the Fashion triple "
                    f"{FASHION_TRIPLE}, or None for 'All'. Got {len(interests)} ids — "
                    f"the server returns 400 for two, four, or any other triple.")
            if len(interests) == 1 and interests[0] in FASHION_TRIPLE:
                raise ValueError(f"{interests[0]} is a Fashion id — usable only as part of "
                                 f"the triple {FASHION_TRIPLE}; alone it returns 500.")

        payload = {"publish_state": "PUBLISHED"}
        if interests is not None:
            payload["interests"] = interests
        key = (f"featured_{_slug(country)}_"
               f"{_slug('_'.join(interests)) if interests else 'all'}")
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(
            f"/ads/v4/trends/topics/featured/{country}/{SPOTLIGHT_EVENT}", payload,
            expect="get_featured_topics_handler")
        return self._store(key, data) if data else None

    def editorial_content(self, country="US"):
        """Pinterest's own written trend stories. Present in the captures since day one and
        never wired until now.

        Six stories, each with a `title`, a written `body` (real editorial copy, not a
        generated blurb), `pins` with dominant colours, `interests`, a `start_date` — and a
        `keywords` dict holding the story's search terms for **US, GB+IE and CA at once**.

        ⚠️ The region path segment is IGNORED: /US, /CA and /GB+IE return byte-identical
        titles. The per-region split lives inside `keywords`, so this is one request for all
        three markets, not three. `country` is kept only so the cache key and source_url
        mirror the UI.

        Unlike `featured_topics` this carries no time series or growth number — it is the
        narrative layer, not the metric layer. Use both: featured_topics says how fast,
        this says what to write.
        """
        key = f"editorial_{_slug(country)}"
        hit = self._cached(key)
        if hit is not None:
            return hit
        data = self._api_resource(f"/ads/v4/trends/editorial/content/{country}", {},
                                  source_url=f"/?country={country}",
                                  expect="get_trends_editorial_content_handler")
        return self._store(key, data) if data else None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
