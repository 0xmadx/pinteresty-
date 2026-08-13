# 08 — Capability Map: every endpoint, every parameter, and how they link

The complete surface across all three sources, what each parameter *asks*, and which are
actually used. Written because the system was built endpoint-by-endpoint and uses a
fraction of what it can reach — every gap below was found by accident during other work,
which is not a method.

**Sources of truth.** Pinterest rows are verified by live test suites
(`test_shopping_endpoints.py` 50 checks / 58 requests, `test_spotlight_moments.py` 39/51)
and documented in `pinterest/endpoints/overviews.md`. Etsy private rows are read from
`etsy/api/private/api.py`. Etsy public rows marked ⚠️ are **unverified** — the client
passes any parameter straight into the URL, so the code imposes no whitelist and the real
list must be read off Etsy's own filter UI.

Status: ✅ used · ⚠️ partly used · ❌ available, never called

---

## 1. What each source uniquely knows

| Source | Knows | Blind to | Cost |
|---|---|---|---|
| **Etsy Private** | absolute search volume, real CVR, real prices paid, competitor listings | anything before people search | free (no limit observed) |
| **Etsy Public** | supply, competitor quality, tags, reviews, live badges | true volume; its sales figures are estimates | free |
| **Pinterest** | momentum, seasonality, **demographics**, purchase-intent split, launch timing | absolute numbers — everything is 0-100 relative | free |

The three are complementary, not redundant. Pinterest leads Etsy by weeks; Etsy Private
is the only absolute measure; Etsy Public is the only view of who you'd fight.

---

## 2. Etsy Private — 4 endpoints

> 🔴 **The response is snake_case.** Verified live 2026-08-12. Every consumer read
> camelCase and therefore read nothing — the root cause of the empty tables (D-24).
> Always go through `parse_results_data` / `parse_term_summaries` /
> `normalise_listing_card`; never index a raw key.

| Endpoint | Parameters | Answers | Status |
|---|---|---|---|
| `get_similar_keywords` | `keyword`, `iterations` | what sub-keywords branch off this? | ✅ (`iterations` 2→10 fixed; edges keyed `query`, not `searchTerm` — use `edge_term()`) |
| `get_chart_series` | `search_terms[]`, `days`, `include_trendline`, `include_wow_data`, `include_search_volume`, `include_avg_total_listings` | volume + supply for many terms at once | ⚠️ `include_trendline:false` — **we decline a free seasonality curve** |
| `get_results_data` | `query`, `search_term_hash`, `search_trigger` | CVR, real prices, competitor listings | ⚠️ `search_term_hash` sent empty; `search_trigger` pinned to `similar_term` |
| `get_trending_terms` | `taxonomy_id` | hot keywords in a whole category | ❌ **never called** — this is the playbook's Phase 1 |

### 2.1 What `results-data` actually returns (verified live)

One call. `parse_results_data` normalises all of it.

| Field | Contains | Used? |
|---|---|---|
| `stats.search_volume` | absolute monthly searches | ✅ |
| `stats.avg_total_listings` | real supply | ✅ |
| `stats.query_cvr` | **the real conversion rate** (`stats.cvr` is an ordinal bucket, often 0) | ✅ |
| `competitive_price_data.search_term_median_price` | `median_price_low` / `_high` as `"$17.10"` strings | ✅ |
| `competitive_research_listing_cards.listing_cards[]` | **20 competitors**: `id`, `title`, `number_of_reviews` (a STRING), `rating`, `shop_name`, `is_star_seller`, `badge_text`, nested `price` object | ✅ feeds the survivor bound |
| `wow_data` | **Etsy's own week-over-week momentum** (`value`, `trend_direction`) | ⚠️ now parsed, not yet scored |
| `similar_search_terms` | keyword expansion **in the same response** | ❌ may make the enqueue/poll crawl redundant |
| `market_gap_recommendations` | **Etsy's own gap analysis** | ❌ never read |
| `quota_data` | `{total: 15, remaining: 15}` — observed unchanged across 3 consecutive distinct calls, so this endpoint does **not** consume it (D-14) | ✅ surfaced |

`chart-series-data` returns `term_summaries[]` with `search_term`, `search_volume`,
`avg_total_listings`, `wow_data` — plus a `series[]` of `points` that nothing reads.

---

## 3. Etsy Public — one open passthrough

`get_public_search(query, filters)` does `params.update(filters)`, so **any** Etsy search
parameter works. The 13 below are those the code uses; the list is not the limit.

| Parameter | Asks | Status |
|---|---|---|
| `order=date_desc` | what did sellers *just* list? (leading signal) | ⚠️ used once, in the generator |
| `order=highest_reviews` | who are the entrenched winners? | ⚠️ used once |
| `holiday` | how crowded is Christmas/Valentine's *now*? | ⚠️ hardcoded `halloween` |
| `is_digital` | digital vs physical split | ✅ |
| `is_personalizable` | is personalisation the gap? | ✅ |
| `is_star_seller`, `best_by_etsy`, `min_rating` | how strong are incumbents? | ✅ |
| `free_shipping`, `delivery_days`, `gift_wrap` | service-level gaps | ✅ |
| `is_discounted` | is everyone discounting? (margin warning) | ✅ |
| `attr_1` | colour | ✅ |
| `locationQuery` | geographic openings | ✅ |
| **`page`** | **ranks 13+** | ❌ **parser reads `total_pages`, nothing ever requests page 2** |
| ⚠️ `min`/`max` | is my price band crowded? feeds the profit gate | ❌ unverified name |
| ⚠️ `attr_2`, `attr_3` | size / material, if colour is `attr_1` | ❌ unverified |

**Biggest single gap in the system: pagination.** Every search reads page 1 only. That
caps the survivor bound at ~12 cards, truncates competitor analysis, and makes rank
tracking record a page-2 listing as "not found".

---

## 4. Pinterest — the underused half

### 4.1 Search family (flat REST)

| Endpoint | Parameters | Answers | Status |
|---|---|---|---|
| `latest_available_date` | none | **call first** — supplies `endDate` everywhere | ✅ |
| `top_trends_filtered` | `trendsPreset`, `country`, `ageBuckets`, `gender`, `l1interests`, `moments`, `keywordsToInclude`, `rankingMethod`, `numTermsToReturn` | what's rising, for whom, in what community | ⚠️ products use it; **the Etsy funnel calls it bare** |
| `metrics` | `terms`, `days`, `end_date`, `aggregation`, `normalize_against_group`, `predicted_days`, `age_bucket`, `gender` | 52-week curve + `wow/mom/yoy_change` | ⚠️ demographics args never passed |
| `related_terms` | `requestTerm`, `country`, `endDate`, `aggregation`, `lookback`, `ageBucket`, `gender` | co-searched terms — **the main edge** | ✅ |
| `prefix_match` | `query`, `country` | autocomplete + 52 weeks history each | ✅ |
| `demographics` | `terms`, `country`, `end_date`, `days` | age + gender per keyword | ⚠️ **no Etsy equivalent exists at all** |

`trendsPreset`: Growing `3` · Seasonal `4` · Top monthly `1` · Top yearly `2`.
`lookbackWindow` is **cosmetic** — identical rows across windows.

### 4.2 Shopping family (ApiResource) — almost entirely unused

| Endpoint | Key parameters | Answers | Status |
|---|---|---|---|
| `product_categories` | `{}` | the **383-category DAG** — Pinterest's own clustering | ❌ |
| `product_categories/top` | `event`, `ranking_method`, `order_by`, `limit` (1–**522**), `offset`, `age_bucket`, `parent_product_categories` | which categories are growing | ❌ |
| `product_categories/metrics` | `product_category_ids`, `event`, `days` (**any 1–730**), `predicted_days` (0/14/28/35/56/91) | category demand curve **+ forecast** | ❌ |
| `product_categories/demographics` | `product_category_ids`, `event` | who buys this category | ❌ |
| `top_products` | `product_category_id`, `region`, `event` | **actual products** inside a category | ❌ |
| `topics/featured` | `interests[]` (exactly 1, or the Fashion triple) | editorial spotlight + `related_search_trends` | ❌ |
| `editorial/content` | `{}` | 6 trend stories with keywords, **US+GB+IE+CA in one call** | ❌ |
| `moment/available` | `{}` | **holiday calendar: takeoff, peak, phase** | ⚠️ products only |

**Three capabilities the Pinterest UI itself does not expose:**

1. **`event` splits intent from aspiration.** `OUTBOUND_CLICK` = purchase intent ·
   `SAVE` = aspiration. Saves inflate decor and fashion that never convert. **For an
   Etsy seller `OUTBOUND_CLICK` is the one that matters** — and the divergence between
   the two *is* an intent measure.
2. **Shopping metrics are demographically sliceable.** `age_bucket` / `gender` are
   accepted and applied; the UI always sends empty arrays so it looks impossible.
   Same category: unfiltered `[93,90,86,88]` vs `AGE_18_24` `[84,84,74,75]` vs
   `MALE` `[100,93,79,75]`.
3. **`limit` defaults to 8; the max is 522.** One call returns the entire ranking. The
   UI never asks for more than 20.

---

## 5. The linking model — how nodes connect

| Edge | From | Meaning |
|---|---|---|
| `term → term` | `related_terms` | co-search association — main expansion |
| `term → term` | `prefix_match` | parent → longer-tail child |
| `term → term` | Etsy `get_similar_keywords` | Etsy's own LLM expansion |
| `category → term` | `related_search_trends` | bridges the 383-DAG into keyword space |
| `topic → term` | `related_search_trends` | bridges editorial trends into keywords |
| `category → category` | `parent_product_categories` | **a DAG, not a tree** (`1108` has two parents) |
| `term → etsy_term` | normalisation | **the join**: lowercase, singularise, strip stopwords both sides |

**Communities arrive pre-computed.** The 24 L1 interests and the 383-node category DAG
are Pinterest's own clustering of the same keyword space being crawled on Etsy — no
n-gram clustering needed. Query by community, then compare a term's momentum to its
community's: **rising faster than its community is a real trend; rising with it is just
the season.** Nothing implements this.

---

## 6. The scoring model, by source

```
Opportunity = (Demand × Momentum × Intent) / (Supply × SERP Strength)
```

| Variable | Best source | Cost | In the code? |
|---|---|---|---|
| Demand (absolute) | Etsy `results-data.searchVolume` | free | ✅ |
| **Momentum** | **Pinterest `mom_change` / `yoy_change`** | free | ❌ |
| **Intent** | **Pinterest `OUTBOUND_CLICK` vs `SAVE`** | free | ❌ |
| **Audience fit** | **Pinterest `/demographics/`** | free | ❌ |
| Supply | Etsy public `organic_listings_count` | free | ✅ |
| SERP strength | Etsy SERP cards | free | ✅ |

**This is the fix for N-01.** The scorer collapses to 0.500 because it has only demand
and supply, which are rank-correlated. Momentum, intent and audience fit are three
independent dimensions, all free, all documented, none wired.

---

## 7. Routes — every way in

| # | Entry | Path | Status |
|---|---|---|---|
| 1 | a keyword | Etsy private → public verify → Pinterest check | ⚠️ partial, fixed order |
| 2 | **nothing** | `get_trending_terms` → pick a niche | ❌ built, unwired |
| 3 | **the calendar** | Pinterest `moments` → Etsy `holiday` filter → launch date | ❌ **both halves exist** |
| 4 | a Pinterest trend | momentum → does Etsy demand exist? | ❌ the leading indicator |
| 5 | a competitor link | listing → tags, reviews, price | ✅ |
| 6 | a shop name | daily sales delta | ✅ |
| 7 | keyword + `date_desc` | what sellers just bet on | ❌ |
| 8 | a community | L1 interest / category → members → Etsy | ❌ |

---

## 8. Build order

Ranked by value ÷ effort. Everything here is free of quota.

| # | Build | Why |
|---|---|---|
| 1 | **Pinterest → Etsy join** | closes N-01 with 3 free dimensions; `overviews.md` §7 names it as the one missing pipeline |
| 2 | **Etsy public pagination** | biggest data gain in the system; strengthens survivorship, competitors, rank tracking |
| 3 | **Holiday calendar loop** (route 3) | the only route that says *when*, not just *what* |
| 4 | **`OUTBOUND_CLICK` vs `SAVE`** | free purchase-intent signal, no Etsy equivalent |
| 5 | **`get_trending_terms`** (route 2) | the playbook's Phase 1, already written |
| 6 | **`include_trendline: true`** | free seasonality curve currently declined |
| 7 | **Demographics into tags** | audience language in listings; no Etsy equivalent |
| 8 | **Community-relative momentum** | separates a real trend from a seasonal tide |

---

## 9. Verified-vs-assumed

| Claim | Evidence |
|---|---|
| Pinterest parameter behaviour | ✅ live test suites, 89 checks / 109 requests |
| Etsy private endpoints and payloads | ✅ read from source |
| Etsy public 13 filters | ✅ used in code |
| Etsy public `min`/`max`, `attr_2/3`, `page` names | ⚠️ **unverified** — read them off Etsy's filter UI |
| "15 analyses per period" | ❌ **contradicted** — operator tested, no limit found |
| "Free = 1.256 × Metered" | ❌ **never built**, constant in no source file |
