# Pinterest Trends — endpoint teardown, graph model, and build plan

Third pillar alongside [`private/endpoints/overviews.md`](../../private/endpoints/overviews.md) (metered Etsy
demand) and [`public/endpoints/public_endpoints.md`](../../public/endpoints/public_endpoints.md) (free Etsy
supply). Everything below is extracted from the 8 DevTools captures in this folder — 257 Pinterest request
URLs, all on a single host — cross-checked against the three pipeline outputs in `pinterest/data/`.

**The one-line summary:** Pinterest gives *momentum and seasonality with no quota*; Etsy gives *absolute
volume, supply and conversion with 15 analyses per period*. Pinterest is the funnel that decides where those
15 get spent.

---

## 1. Transport and auth

| Layer | Where | Notes |
|---|---|---|
| Host | `trends.pinterest.com` | The only host in every capture. No `www.pinterest.com` calls. |
| Auth | session cookies + `x-csrftoken` | Chrome extension → `pinterest/core/cookie_server.py` → `pinterest_cookies.json` → read directly by [`endpoints/api.py`](api.py). |
| Client | `httpx.AsyncClient`, 20 s timeout | Pinterest TTFB is slow; the timeout is deliberate. |
| Flat REST headers | **none beyond cookies** | Verified — the whole test suite omits every `x-pinterest-*` header and passes. |
| **ApiResource headers** | **`x-pinterest-pws-handler` is mandatory, and is the only one that is** | Without it: `403 Invalid Resource Request`. With it alone: 200. **The value is not validated** — `trends/bogus-does-not-exist.js` works. Verified on both `trends/index.js` and `trends/shopping.js` paths. `x-pinterest-source-url`, `x-pinterest-appstate`, `screen-dpr` and **`X-APP-VERSION` are all unnecessary** — sending `X-APP-VERSION` *without* `pws-handler` still 403s. |
| POST headers | `x-new-site: true`, `x-csrftoken: <csrftoken cookie>`, `Content-Type: application/json` | Required for `POST /term_images/`. |
| Account scoping | advertiser `549770663874`, business `1103382114864552469` | These ids are baked into `/ads/v4/...` payloads. The trends data is account-scoped, so a dead session gives 403, not empty data. |
| Quota | **none observed** | No `quota_data` equivalent anywhere in the captures. This is the structural advantage over Etsy Insights. |

**Anti-bot posture is much softer than Etsy's.** No DataDome, no TLS impersonation needed — plain `httpx`
works where Etsy needs `curl_cffi` + a live `datadome` cookie.

---

## 2. Two request families

**a. Flat REST** — `GET https://trends.pinterest.com/<endpoint>/?<params>`. Simple query strings, JSON back.

**b. The ApiResource envelope** — `GET /resource/ApiResource/get/?source_url=<path>&data=<url-encoded JSON>`,
where the JSON is `{"options": {"url": "<inner /ads/v4 path>", "data": {…}}, "context": {}}`. 82 of the 257
captured URLs use this. The real endpoint is `options.url`; the real payload is `options.data`. Response is
always wrapped: `resource_response.data` is the part you want, and `client_context` is ~63 keys of account
noise you should strip on ingest.

Both families are wrapped in one class, [`endpoints/api.py`](api.py) (`PinterestTrendsAPI`) — cache-first,
mirroring `EtsyPrivateAPI`/`EtsyPublicAPI`. The older loose async functions (`core/trends.py`,
`core/api_resource.py`) are gone; the latter never sent the mandatory `x-pinterest-pws-handler` and 403'd.

---

## 3. Endpoint catalog

### 3.1 Flat REST

| Endpoint | Params | Returns |
|---|---|---|
| `/latest_available_date/` | none | `{"date": "2026-07-27"}`. **Call this first** — it supplies `endDate`/`end_date` for every other endpoint. |
| `/top_trends_filtered/` | `lookbackWindow`, `endDate`, `country`, `trendsPreset`, + optional `ageBuckets`, `gender`, `l1interests`, `moments`, `keywordsToInclude`, `rankingMethod`, `numTermsToReturn` | **The discovery endpoint.** `{"values": [ …50 items… ]}` — see the node schema below. |
| `POST /term_images/` | body `{terms[], country, cacheTtlInSeconds, limit, batchSize, requestImageSize}` | Thumbnails per term. The only POST in the flat family — needs `x-new-site: true`, `x-csrftoken` and `Content-Type: application/json`. |
| `/metrics/` | `terms` (comma-separated), `country`, `end_date`, `days` (90\|365), `aggregation=2`, `normalize_against_group`, `predicted_days`, + optional `age_bucket`, `gender` | 52–53 weekly points per term: `{count, date, normalizedCount, predictedUpper/LowerBoundNormalizedCount}` plus `growth_rates{wow_change, mom_change, yoy_change}`. |
| `/related_terms/` | `requestTerm`, `country`, `endDate`, `aggregation`, `lookback`, + optional `ageBucket`, `gender` | Co-searched terms — `{term, counts[], hasPrediction}`. **Primary edge source.** |
| `/prefix_match/` | `query`, `country` | Autocomplete, `{term, counts[52]}`. Pinterest's A-Z equivalent, and it returns history with each suggestion. |
| `/demographics/` | `terms`, `country`, `end_date`, `days` | `age_distribution` (7 buckets) + `gender_distribution`. |
| `/detail/`, `/search`, `/shopping/<catId>/`, `/` | page routes | Virtual paths only — used as `source_url` and `referer` values. Not data endpoints. |

The four dashboard tabs differ only by `trendsPreset`: **Growing** `3` · **Seasonal** `4` ·
**Top monthly** `1` · **Top yearly** `2`. **`lookbackWindow` is cosmetic** — the same preset across windows
1/2/3/5 returns byte-identical rows; it only changes UI copy. `country` accepts grouped regions
(`GB+IE`, `DE+AT+CH`, `MX+AR+CO+CL`).
Full enum tables — including the numeric age/gender encodings and all 24 interest ids — in
[`../README.md` §3](../README.md).

### 3.2 ApiResource inner paths

| `options.url` | Payload | Returns |
|---|---|---|
| `/ads/v4/trends/shopping/product_categories` | `{}` | The ID→name dictionary. **383 categories.** Fetch once, cache forever. |
| `/ads/v4/trends/shopping/product_categories/top/US` | `event`, `ranking_method`, `end_date`, `age_bucket[]`, `gender[]`, `parent_product_categories[]`, `limit`, `order_by`, `order` | `ordered_values[]` — see node schema. |
| `/ads/v4/trends/shopping/product_categories/metrics/US` | `product_category_ids[]`, `event`, `end_date`, `days`, `predicted_days` | `values[] = {term: "<catId>", daily_values[]}`. |
| `/ads/v4/trends/shopping/product_categories/demographics/US` | `product_category_ids[]`, `event`, `end_date` | Age/gender per category. |
| `/ads/v4/trends/shopping/product_categories/top_products` | `product_category_id`, `region`, `event` | Actual products inside a category. Wired as `api.top_products()` / `api.etsy_competitors()`. |
| `/ads/v4/trends/topics/featured/<CC>/<EVENT>` | `interests[]`, `publish_state` | Editorial spotlight topics — see node schema and §3.2c. Wired as `api.featured_topics()`. |
| `/ads/v4/trends/editorial/content/US` | `{}` | Editorial trend stories. **Wired** — `api.editorial_content()`. 6 stories with `title`, written `body`, `pins`, `interests`, `start_date`, and a `keywords` dict covering **US + GB+IE + CA in one response**. The region path segment is ignored (all three return identical titles). No series, no growth number — narrative layer only. |
| `/ads/v4/trends/moment/available/US` | `{}` | The `moments` vocabulary that feeds `top_trends_filtered`. Wired as `api.moments_calendar()`. |
| `/v3/trends/partner/<userId>/available_interests/` | `available_term_count_threshold`, `lookback_window`, `trend_type` | The L1 interest taxonomy. Returns **200 with `{"results": null, "insufficientDataResponse": …}`** on this account — reachable, but empty because the advertiser has no data. Hardcode the 24 ids from [`../README.md` §3](../README.md). |

`event` ∈ `OUTBOUND_CLICK` \| `SAVE` \| `ENGAGEMENT`. Three separate demand curves per category, and they
disagree: outbound clicks are purchase intent, saves are aspiration. **For an Etsy seller, `OUTBOUND_CLICK`
is the one that matters** — saves inflate decor and fashion categories that never convert.

### 3.2b The Shopping stack in detail

Shopping shares **nothing** with `/top_trends_filtered/` — different endpoints, different enums,
different region list. All of it verified by
[`../tests/test_shopping_endpoints.py`](../tests/test_shopping_endpoints.py) (50 checks, 58 requests).

**Regions: `US`, `CA`, `GB+IE` only.** `DE+AT+CH` and `MX+AR+CO+CL` work on the search endpoints and
**400 here** — the two families do not share a region list.

**Taxonomy** — `product_categories`, payload `{}`. 383 categories at levels 2/3/4. `region` is accepted
but ignored (same 383 for US and CA); there is no `/product_categories/US` path variant. The **14 level-1
verticals are not in the map** (`1181 1161 1042 1250 1148 1194 1315 1500 1481 1016 1436 1007 1241 1489`),
and they are valid **only** in `parent_product_categories` — passing one as a `product_category_id` is a
400, and one bad id fails the whole call. `PinterestTrendsAPI` raises before the request rather than
letting the server 400.

**`/top/{REGION}`** — `event`, `ranking_method` and `end_date` are all **required** (400 if omitted).

| param | values |
|---|---|
| `event` | `OUTBOUND_CLICK` → **44** categories · `ENGAGEMENT` → **35** · `SAVE` → **18** · `IMPRESSION` → 200, same 35 as ENGAGEMENT (aliased) · `CLOSEUP` → 400 |
| `ranking_method` | `GROWTH` only |
| `order_by` | `PCT_CHANGE_MOM` · `RELATIVE_VOLUME` (anything else 400) |
| `limit` | 1–**522**; 0/negative/523+ → 400. **Omitting it gives you 8**, not everything |
| `offset` | works — genuine server-side pagination, unlike the UI |
| `age_bucket` | `AGE_ALL` plus the seven `AGE_*` bands; multi OK |
| `parent_product_categories` | `[]` = all; the 14 vertical ids; unknown id → 0 rows |

Since there are only 44 categories total, **one call with `limit=522` gets the entire ranking** — which is
what `top_categories()` now defaults to. The UI never asks for more than 20.

**`/metrics/{REGION}`** — `product_category_ids`, `event`, `end_date`, `days` required.

- `days`: **any integer 1–730** (7→1 weekly point, 30→5, 90→13, 365→53, 730→105). Far looser than the
  search `/metrics/`, which accepts only 30/90/180/365/730 and 400s on anything else including 45 and 60.
- `predicted_days`: `0 14 28 35 56 91` — **`7` returns 500**, `29`/`92` return 400.
- ⚠️ **`age_bucket` and `gender` are accepted AND applied here.** The UI always sends empty arrays, which
  makes it look like the sparklines can't be sliced, but they can: unfiltered `[93,90,86,88]` vs
  `AGE_18_24` `[84,84,74,75]` vs `MALE` `[100,93,79,75]` on the same category. **Shopping demand is
  demographically sliceable** — that is a capability the UI simply doesn't expose.

**`/demographics/{REGION}`** — `product_category_ids`, `event`, `end_date` required; `days` optional.
`event` is validated loosely here (even `CLICK` returns 200).

**`top_products`** — note the shape change: **singular `product_category_id`, and `region` lives in the
body, not the path.** Omitting `event` returns 500. `limit`/`offset` are ignored — you get whatever the
backend holds (US/1010 → 23, CA → 50, GB+IE → 49). **Only `OUTBOUND_CLICK` returns rows**; `SAVE` and
`ENGAGEMENT` return 200 with zero results. Images come in 75x75, 236x, 345x, 474x, 564x, 736x, 1200x.

**Front-end → API mapping.** `page` is **purely client-side**: the UI fetches `limit:20` once and slices
10 per page in the browser, firing zero requests on next/prev. Server-side `offset` exists anyway, so we
can page far past what the UI ever shows. On the detail page the two event selectors are **named
backwards** — `event` drives the chart, `graphEvent` drives the demographics donut. `dateRange` maps
`90D|180D|365D|730D` → `days` (no 30D; default 180D). The page also fires
`/product_categories/top_products//1010` with a double slash, which 404s on every load — Pinterest's own
bug, ignore it.

### 3.2c Spotlight and Moments

Verified by [`../tests/test_spotlight_moments.py`](../tests/test_spotlight_moments.py) (39 checks,
51 requests).

**`topics/featured/{REGION}/{EVENT}`** — the most locked-down endpoint in the whole stack:

- **`{REGION}`: `US`, `CA`, `GB+IE` only** (case-insensitive). `DE`, `JP`, plain `GB` → 400. This is why
  switching the page to Germany makes the module disappear — the front end doesn't even try.
- **`{EVENT}`: `SAVE` only.** `OUTBOUND_CLICK`, `ENGAGEMENT`, `IMPRESSION` all 400. There is no event
  switch here; spotlight is hard-wired to Pin saves. (Contrast Shopping, where the event choice is the
  whole point.)
- **`publish_state`: `PUBLISHED` or omit.** Anything else 400.
- **`interests` cardinality is the odd one.** Exactly **one** id, **or** the Fashion triple
  `["903733943146","924581335376","948967005229"]` (order irrelevant), **or** omit the key for "All".
  Two ids → 400. Four → 400. Any *other* three-id combination, including `["1","2","3"]` → 400.
  A bare string is tolerated as a one-element array.
- Ids present on `/search/` but absent from the dropdown split two ways: **Sport, Finance, Vehicles and
  Design return 200 with an empty list**, while **the three Fashion ids individually — and any unknown id —
  return 500**. So the Fashion ids are usable only as the triple.
- `limit`, `offset`, `end_date`, `age_bucket`, `gender` and junk keys are all accepted and **ignored**.
  Always 5 topics, no pagination, no date control, no demographic filter.

The expanded card fires **zero requests** — `name`, `description`, `pct_growth_mom`, `time_series`, `pins`,
`related_search_trends` all ship in that one response, and the URL doesn't change, so there is no
deep link to an individual spotlight trend. The related-search chips link to
`/detail/?...&dateRange=30D` — the only place in the UI that produces a 30-day detail page, since the
dropdown offers only 90D/180D/365D/730D.

**`moment/available/{REGION}`** — payload is `{}` and stays `{}` (`end_date`, `limit`, `phase` and junk
keys are all ignored). Dropping or doubling the region path segment → 404. Coverage is wider than
spotlight's three but **not the ~26 regions claimed in the first pass** — re-measured 2026-07-27:
single-country codes (`US` `CA` `BR` `MX` `IT` `ES` `FR` `DE`) return moments *with* takeoff/peak
timestamps; grouped codes (`GB+IE` `DE+AT+CH` `MX+AR+CO+CL`) return the names with **every `takeoff_ms`
null**; `JP` returns an empty list; and `AU` `NL` `IE` `GB` `ZZ` all **400**.

This is the **authoritative per-region moment enum**, and it governs `/top_trends_filtered/`:
`moments=oktoberfest&country=US` → **400**, while `moments=canada day&country=CA` → **200 with 0 rows**.
`phase_labels` uses exactly `approaching` · `cooldown` · `ended` (the UI renders `ended` as "Frozen").

The cards link to `/moments/{slug}?country=<REGION>` with the raw moment string URL-encoded
(`/moments/new%20years%20eve?country=US`). The "View moments" button is a plain `<button>` — it re-renders
the same payload in a sheet, firing nothing.

### 3.3 `endpoint_name` — the server-side identity of each call

Every `ApiResource` response carries `resource_response.endpoint_name`. It is the handler that served the
request, it does not change when the URL does, and it is the cheapest possible assertion that a parser is
looking at the payload it thinks it is. Assert on it rather than on the URL you sent.

| `endpoint_name` | Call |
|---|---|
| `get_available_moments_handler` | `moment/available` — the seasonal calendar |
| `get_product_categories` | the 383-category dictionary |
| `get_filtered_product_categories` | `product_categories/top` — ranked categories |
| `get_product_category_metrics` | `product_categories/metrics` |
| `get_product_category_demographics` | `product_categories/demographics` |
| `get_trends_top_products` | `top_products` — the Etsy-merchant bridge |
| `get_featured_topics_handler` | `topics/featured` — spotlight |
| `get_trends_editorial_content_handler` | `editorial/content` |
| `get_preference` · `get_business_assets_by_ids_handler` | ads-account boilerplate, see §3.4 |
| `v3_event_logger` | telemetry, see §3.4 |

### 3.4 Endpoints to ignore

Present in the captures, carrying no trend data. Listed so nobody re-derives them later:

- **`POST /resource/ApiCResource/create/`** (`v3_event_logger`) — analytics beacon, Pinterest's equivalent
  of Etsy's `/bcn/beacon`. Fires on every interaction. Never replay it.
- **`/ads/v4/preferences/<advertiserId>`** — UI preferences (`level`, `key`). Returned empty arrays.
- **`/ads/v4/business_access/businesses/<businessId>/assets_by_ids`** — ad-account lookup
  (`asset_ids`, `resource_type`, `page_size`, `sort_by`, `sort_ascending`, `search_value`, `start_index`).
  Account plumbing, not trends.

---

## 4. Node schemas (what the graph stores)

**Term node** — `/top_trends_filtered/` `values[]`:
```json
{"term": "nails", "searchCount": 100, "normalizedCount": 100, "reverseRank": 50,
 "seasonality_score": 0.9194547, "affinity": null,
 "wow_change": {"index": 27, "value": 0}, "mom_change": {"index": 33, "value": 0.1},
 "yoy_change": {"index": 14, "value": 0.04}}
```
`seasonality_score` (0–1) is the single most valuable field in the whole stack — it is the launch-timing
signal the Etsy playbook currently derives by eyeballing a 365-day chart.

Each `*_change` carries a `value` and an `index`. **`value` is the fractional change** (0.1 = +10%), and
**`100.01` is a sentinel for the UI's "10,000%+" cap**, not a real 10,001× move — clamp or flag it, never
average it. **`index` is the 1–50 rank** within the returned set, which is what the UI draws the bars from.

**Critical caveat: counts are normalized, not absolute.** `normalize_against_group=true` and `searchCount`
max out at 100 across the returned group. Pinterest tells you *shape* — momentum, seasonality, relative
rank — never magnitude. Absolute volume only ever comes from Etsy `results-data`. Any scoring formula that
multiplies a Pinterest count by an Etsy count is comparing an index to a number.

**Category node** — shopping `ordered_values[]`:
```json
{"product_category": "1108", "parent_product_categories": ["1104", "1350"],
 "related_search_trends": ["winter fashion", "leather jacket", …],
 "summary": {"outbound_clicks": {"percent_growth": 0.18, "percent_relative_volume": 1, "lookback": 2, "total": 0},
             "saves": {…}, "engagement": {…}}}
```
Note `total` is always `0` — Pinterest withholds absolutes here too. Use `percent_relative_volume`.

**Topic node** — featured topics `data[]`:
```json
{"id": "4496417215295727047", "name": "Checkout Counters", "pct_growth_mom": 0.7,
 "description": "…", "interests": ["918105274631", …], "is_published": true,
 "related_search_trends": [ …up to ~15 terms… ],
 "time_series": [{"date": "2026-05-04", "count": 39, "normalized_count": null, …}],
 "pins": [{"id": "…", "src": "https://i.pinimg.com/236x/…", "width": 236, "height": 419, "color": "#c5ada8"}]}
```
`pins[]` is a free source of competitor creative — image URLs and dominant colour per trend, which nothing
on the Etsy side provides.

---

## 5. The graph: nodes, edges, communities

```
interest (L1 taxonomy)  ──contains──►  topic (spotlight)  ──related_search_trends──►  term
        │                                                                              ▲ ▲
        └──────────────────────────────────────────────────────────────────────────────┘ │
                                                                                          │
category (383, tree) ──parent_product_categories──► category                              │
        └──related_search_trends──────────────────────────────────────────────────────────┘

term ──related_terms──► term        (co-search, weighted, bidirectional-ish)
term ──prefix_match───► term        (autocomplete descendants, hierarchical)
term ──normalized string match──► etsy_term    ← the cross-platform bridge
```

**Node types:** `term`, `product_category` (383), `topic` (editorial), `interest` (L1 taxonomy root).

**Edge types and where they come from:**

| Edge | Source | Character |
|---|---|---|
| `term → term` | `/related_terms/` | Co-search association. The main expansion edge, equivalent to Etsy's LLM `similar_keywords`. |
| `term → term` | `/prefix_match/` | Hierarchical (parent → longer-tail child). Cheaper and more literal than related terms. |
| `category → term` | `related_search_trends` | Bridges the shopping taxonomy into keyword space. |
| `topic → term` | `related_search_trends` | Bridges editorial trends into keyword space. |
| `topic → interest` | `interests[]` | Assigns a topic to communities. |
| `category → category` | `parent_product_categories[]` | Explicit tree; note it is a **DAG, not a tree** — `1108` has two parents. |
| `term → etsy_term` | normalization | The join. Lowercase, singularize, strip stopwords on both sides. |

**Communities are handed to you pre-computed** — this is the part worth exploiting. The L1 interest ids and
the 383-node category DAG are Pinterest's own clustering of the same keyword space you're crawling on Etsy.
No n-gram clustering needed: `l1interests` on `top_trends_filtered` and `parent_product_categories` on the
shopping endpoint let you *query by community* directly, then measure how a community's momentum compares
to its members'. A term rising faster than its community is a real trend; a term rising with its community
is just the season.

---

## 6. What this adds to the Etsy scoring model

The master formula in `claude/claude.md` is
`Opportunity = (Demand × Momentum × Intent) / (Supply × SERP Strength)`. Before Pinterest, every variable
came from Etsy and three of them cost quota. Now:

| Variable | Best source | Cost |
|---|---|---|
| Demand (absolute) | Etsy `results-data.searchVolume` | metered |
| **Momentum** | **Pinterest `mom_change` / `yoy_change` / `seasonality_score`** | **free** |
| **Intent** | **Pinterest `OUTBOUND_CLICK` vs `SAVE` divergence** | **free** |
| **Audience fit** | **Pinterest `/demographics/`** | **free** — no Etsy equivalent exists |
| Supply | Etsy public SERP `organic_listings_count` | free |
| SERP strength | Etsy SERP cards | free |

Two things Pinterest gives that Etsy has no counterpart for at all: **demographics per keyword**, and a
**leading indicator**. Pinterest search precedes purchase by weeks — its `mom_change` spiking before Etsy
volume moves is the earliest signal in the stack, earlier even than the autocomplete-diffing trick.

---

## 7. Build status

The four divergences from the Etsy pillars this section used to describe are now closed:

1. **`pinterest/endpoints/api.py`** — `PinterestTrendsAPI`, cache-first (`pinterest/data/cache/`), one
   method per endpoint, mirroring `EtsyPrivateAPI`/`EtsyPublicAPI`. Replaces the old loose async
   `core/trends.py` / `core/api_resource.py` (deleted — nothing imported them once the pipelines were
   ported).
2. **`core/graph_db.py`** extended for a multi-source graph: a real `edges` table
   (`src, dst, edge_type, source, weight`) instead of the old `nodes.edges_json` blob; `source` /
   `node_type` / `seasonality_score` / `mom_change` / `yoy_change` / `search_count` /
   `demographics_json` columns added via additive migration; `update_node()` added so batched writes
   (e.g. curve backfill) patch fields instead of `INSERT OR REPLACE`-blanking the rest of the row; `get_node`'s
   inverted `dict(cursor.fetchone()) if cursor.fetchone() else None` bug fixed. Migration preserved the
   pre-existing Etsy nodes and frontier rows and backfilled them `source='etsy'`.
3. **`pinterest/pipelines/pin_graph_pipeline.py`** — BFS on the same `push_frontier`/`pop_frontier`
   contract as [`ssr_graph_pipeline.py`](../../private/pipelines/ssr_graph_pipeline.py): seed from
   `top_trends()`, expand via `related_terms` + `prefix_match`, batch `/metrics/` at 50 terms/call rather
   than per-term. Because there's no quota the crawl runs far wider than Etsy's — depth 2+ against Etsy's
   depth 1. Verified live: 17 nodes, 153 edges (99 prefix / 54 related), 241 frontier queued.
4. **`scrape_search.py` / `scrape_shopping.py` / `scrape_spotlight.py`** all ported onto
   `PinterestTrendsAPI` — dates come from `latest_available_date()`, shopping sweeps all 44 categories,
   spotlight sweeps all 15 dropdown options.

**Still open:**

- **Raw dumps with explanations.** Extend [`dump_raw_data.py`](../../dump_raw_data.py) to write
  `pinterest/data/raw/<endpoint>_<term>.json` + `_explanation.md`, matching the Etsy side. The current
  `pinterest/data/*_pipeline_output.json` files bundle several endpoints into one blob and keep all 63
  keys of `client_context` — strip to `resource_response.data` on write.
- **The join pipeline** — crawl Pinterest wide and free, rank the corpus by momentum × seasonality ×
  outbound-click intent, spend Etsy's metered `results-data` only on the top ~15 survivors. Nothing wires
  `pin_graph_pipeline.py`'s output into the Etsy scoring/listing pipeline yet.

---

## 8. Open questions

- **Is `related_terms` weighted?** The response carries `counts[]` per related term but no explicit edge
  weight — `pin_graph_pipeline.py` currently uses the child's own latest count. Correlating the two terms'
  52-week series would be more meaningful and is computable from data already fetched.
- **How stale is `end_date`?** §5.3 of [`../README.md`](../README.md) confirms `endDate` snaps backward to
  the nearest data week and can backfill history; not yet checked how many days behind "now" the *latest*
  week typically sits.
- **Shopping pagination** — `page=1` appears in the navigation state but `offset` (genuine server-side
  paging) has never been exercised past what `limit=522` already returns in one call.
