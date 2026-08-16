# 11 — Endpoint Reference (ground truth, by platform)

**The one place that says what every endpoint IS, what it returns, and whether that was
verified on the wire or assumed.** Built 2026-08-16 to end the "discovering endpoints by
accident" problem. When code and this doc disagree, probe the wire and fix this doc.

Legend: ✅ verified live (date) · ⚠️ wired but returned empty/None when probed · ❓ never
probed · ❌ confirmed dead.

**The one rule that governs all of it (D-29):** `etsy_private` authenticates as the
operator's OWN seller account — the scarce, unreplaceable asset. Use it ONLY for what
no public call can answer. Everything about competitors, listings and SERPs is public.

---

## THE THREE PLATFORMS AT A GLANCE

| | Etsy Private | Etsy Public | Pinterest |
|---|---|---|---|
| **Auth** | operator's seller session | any buyer session | pinterest session |
| **Risk if banned** | 🔴 the business | 🟢 a re-login | 🟢 a re-login |
| **Unique signal** | real search volume, CVR, seasonal cycle, keyword tree | competitor listings, tags, SERP, product type | demographics, click-vs-save intent, its own audience |
| **Answers** | *is there demand? can I rank? when does it peak?* | *who am I competing with? what do they tag?* | *who wants it? are they buyers? is it rising?* |

The mental model: **Private = demand truth. Public = competition truth. Pinterest =
audience truth.** Each owns a question the other two cannot answer.

---

## 1. ETSY PRIVATE — `etsy/api/private/api.py`

The seller tool's own data. Marketplace Insights. No quota has ever been observed
(D-14). Every response is **snake_case** — read through the parsers, never raw keys.

### 1.1 `get_results_data(query)` — the master demand call ✅ 2026-08-16
The most valuable single call. One keyword in, everything about its demand out.

| Field (via `parse_results_data`) | Meaning | Verified |
|---|---|---|
| `volume` | monthly search volume | ✅ 2727 for "felt garland" |
| `supply` | avg total listings competing | ✅ 29,017 |
| `cvr` | `query_cvr` — the real conversion RATE | ✅ 0.00028 |
| `cvr_bucket` | `cvr` — an ordinal bucket, often 0, NOT the rate | ✅ |
| `price_low/high` | median price band, coerced from "$15.30" to float | ✅ |
| `price_bar_low/high` | a DIFFERENT, wider band — kept separate | ✅ |
| `wow_change` | Etsy's own week-over-week % | ✅ -3.6 |
| `listings` | **20 competitor cards** free (title, reviews, shop, price, star-seller) | ✅ |
| `quota_total/remaining` | reported 15/15, never moves — endpoint is not metered | ✅ D-14 |
| `similar_terms` | `similar_search_terms` — **EMPTY, total_results_count 0** | ❌ verified empty |
| `market_gap` | `market_gap_recommendations` — **null** | ❌ verified null |

⚠️ 401/403 here → `SessionDown` (browser/extension off), not a broken endpoint.

### 1.2 `get_chart_series(terms, days=365)` — the SEASONAL CYCLE + compare ✅ 2026-08-16
**Underused.** Pass a LIST of terms, get a 12-month time series for each — the "cycle
diagram" from the seller UI, and multi-keyword comparison in one call.

- `series[].points[]` = `{timestamp, label "Sep 2025", value}` — 12 monthly points
- `term_summaries[]` = per-term `{search_volume, avg_total_listings}`
- Verified: "mom necklace" peaks Nov–Dec (Christmas) + April (pre-Mother's Day),
  troughs Feb/June. **This is the calendar's engine, from Etsy alone — no Pinterest
  needed for seasonality.**
- `parse_term_summaries` reads the summaries; the **points series is not parsed yet**
  (the peak→list-by feature would read it).

### 1.3 `get_similar_keywords(keyword)` — the RECURSIVE keyword tree ✅ 2026-08-16
The LLM expansion. One keyword → ~120–165 related terms, each with its own
`search_volume` and `avg_total_listings` inline. This is RK-2, fixed after being blocked
by the snake_case bug at three layers (enqueue `run_id`, poll 202/400, `edge_term`
`search_term`).

- **Async**: enqueue returns `{run_id, thread_id, cached_data}`. Once Etsy has computed a
  keyword, `cached_data` is populated instantly on enqueue; a cold keyword returns null
  and must be polled (202 while cooking → 200 with results).
- The tree has **cycles** ("felt banner" lists "felt garland" back) — a crawl must
  dedupe. `keyword_crawl.py` does.
- Powers `discover.expand_seed` and `hunt --seed`.

### 1.4 `get_trending_terms(taxonomy_id=199)` — the curated front door ✅ 2026-08-16
Rising terms per category, with volumes, no quota cost. **⚠️ Only 7 of 15 probed
taxonomy ids are populated:** 1, 66, 199, 323, 891, 1429, 1633. 28 terms total.

⚠️ **These are Etsy's PICKS, not the top of the market** — `basis="etsy_curated"`. B-01
applied to candidate generation. The seed crawl (1.3) is the stronger discovery path.

---

## 2. ETSY PUBLIC — `etsy/api/public/api.py`

Buyer session. Everything about competitors, unlimited, no seller-account risk. This is
where all competitor/listing/SERP work MUST happen (D-29).

### 2.1 `get_public_search(query, filters=None)` — the SERP ✅ 2026-08-16
| Field | Meaning | Verified |
|---|---|---|
| `total_results` | total competing listings | ✅ |
| `cards` | ~12 listing cards (server-rendered; the rest hydrate client-side) | ✅ 12 |
| per card | title, price, review_count, shop, is_ad, star_seller | ✅ |

⚠️ **PS-1**: `results_per_page` says 48 but ~12 render — do not divide by "the page".
⚠️ **PS-2**: `organic_listing_ids` is always empty — no authoritative rank order.
⚠️ `filters` param exists; the real Etsy filter names (`page`, `min`/`max`, attributes)
are unverified — **O-6**, read them off Etsy's filter UI before trusting.

### 2.2 `get_listing_data(listing_id)` — one listing's guts ✅ 2026-08-16
The cheapest reusable thing (30-day cache). From ONE fetch of the page HTML:
- `tags` — the listing's **13 tags** (the SEO gold — page-one tags)
- `breadcrumb` — its **taxonomy path** (`Paper & Party Supplies > Party Decor > ...`)
- `product_type` — digital / physical / personalized, from the same HTML (D-22)

All three come from one fetch. Feeds `blueprint`, `taxonomy`, `product_type`.

---

## 3. PINTEREST — `pinterest/endpoints/api.py`

Its own session. The audience layer. Reads from a Redis vault now (fixed 2026-08-15 —
it used to read `PINTEREST_COOKIES` from `.env`, which nothing writes). Weekly data —
sampling faster re-reads the same numbers.

### 3.1 `moments_calendar(country)` — seasonal takeoff/peak dates ✅ 2026-08-16
13 moments with `takeoff_ms`, `peak_ms`, `phase` (as STRING epochs). Powers the
calendar's "list by" deadlines. Holiday-centric — no back-to-school/autumn moment.

### 3.2 `related_terms(term)` — Pinterest's recursive tree ✅ 2026-08-16
~5 related terms, each with a `counts` momentum series. Pinterest's equivalent of 1.3,
but scored on MOMENTUM not competition. Verified: "mom necklace" → silver necklace,
charm necklace, cross necklace. Powers `pin_graph_pipeline`.

### 3.3 `prefix_match(query)` — autocomplete expansion ✅ 2026-08-16
~10 prefix completions. Verified: "mom neck" → neck tattoo, mom outfits (prefix, so
noisy — string match, not semantic).

### 3.4 `top_trends(preset, ...)` — "Search trends" / trending keywords ✅ 2026-08-16
`/top_trends_filtered/`. The wide discovery net — up to 100 rising keywords per call.
**Fully analysed on the wire 2026-08-16.**

**THE PRESET IS THE MASTER SWITCH.** `trendsPreset` (1–4) changes the ranking logic
entirely — same page, four different answers:

| preset | trendsPreset | ranks by | live top rows | use for |
|---|---|---|---|---|
| `top_monthly` | 1 | volume this month | nails, nail ideas, hairstyles | the biggest terms right now |
| `top_yearly` | 2 | volume this year | nails, hairstyles, wallpaper | evergreen giants |
| `growing` | 3 | velocity (rising) | isopod wants, sterling point tv show | breakout/novelty (often niche/noise) |
| **`seasonal`** | 4 | seasonal spike NOW | **first day of school prayer, august pedicure colors, senior sunrise captions** | **timing — what is spiking this week** |

`seasonal` is the timing goldmine: it surfaces terms peaking *right now*. `growing`
catches breakouts but is noisy (fandom/meme terms). `top_monthly` is the reliable
big-volume list.

**Row structure (9 fields):** `term`, `mom_change`/`yoy_change`/`wow_change` (momentum at
three timescales, each `{index, value}`), `seasonality_score` (0–1), `searchCount` +
`normalizedCount` (volume), `affinity` (interest affinity, null unless filtered),
`reverseRank`.

**Parameters — what works and what doesn't (verified):**

| param | effect | verified |
|---|---|---|
| `trendsPreset` | the ranking logic (above) | ✅ the one that matters |
| `numTermsToReturn` | 1–100. UI sends 50; **100 works and the first 50 are identical** — free 2× breadth for one call. 101 → 400. | ✅ |
| `lookbackWindow` | **cosmetic** — 1/2/3/5 return byte-identical rows. Do not bother tuning. | ✅ code-verified |
| `l1interests` | **Interest** filter — one category (Beauty → nail/hair trends) | ✅ |
| `gender` | **Gender** filter — works, but wants NUMERIC (0/1/2), NOT "female". Our code now maps the label. `female → nails/hairstyles`, `male → wallpaper/spiderman/anime` — dramatically different. | ✅ |
| `ageBuckets` | **Age** filter — NUMERIC bucket index (18-24 = [2,3]). Label now mapped. | ✅ |
| `moments` | **Moments** filter — tie a term set to a seasonal moment | ❓ not probed |
| `keywordsToInclude` | **Include keyword** filter | ❓ not probed |

The UI's five filters — Interest, Moments, Age, Gender, Include keyword — are ALL real.
⚠️ **The trap:** gender/age want numeric indices; the string "female" returns 500. That
500 briefly looked like "the filter doesn't work" — it does, our code was sending the
wrong format (fixed 2026-08-16, `top_trends` now maps labels via `GENDER`/`AGE`).
The demographic split IS available right here — you do NOT need the separate
`demographics()` endpoint for search trends.

Powers `scrape_search.py` and `pin_graph_pipeline` seeding.

### The three Pinterest Trends TABS (the operator's "search trends / shopping / spotlight")
These are Pinterest's own product surfaces, each with a pipeline already:

| Operator's name | Pipeline | Endpoint |
|---|---|---|
| **Search trends** | `scrape_search.py` | `top_trends(preset)` (3.4) |
| **Shopping trending** | `scrape_shopping.py` | `top_categories` (3.6) + `etsy_competitors` + `top_products` |
| **Trends in the spotlight** | `scrape_spotlight.py` | `top_trends` over `SPOTLIGHT_INTERESTS` |

### 3.5 `demographics(terms)` — age/gender ⚠️ 2026-08-16
Returns `{term_distributions: {}}` — **empty for "mom necklace"**. Wired, but needs a
term Pinterest actually has demographic data for. **The unique signal Etsy has none of**
— but unverified that it returns anything useful. Probe before building on it.

### 3.6 `top_categories(event="OUTBOUND_CLICK")` — the INTENT signal ✅ 2026-08-16
**Verified real and it separates.** `OUTBOUND_CLICK` (people who clicked THROUGH to buy)
returned **37 categories**; `SAVE` (people who just bookmarked) returned **20** — different
sets, different sizes. That gap IS the buy-signal-vs-daydream distinction, and Etsy has
no equivalent at any price. Verified structure per category:
- `summary` = `saves` / `engagement` / `outbound` each with `percent_growth` (momentum!)
- `related_search_trends` = **25 related terms per category** (a discovery source)
- `product_category`, `parent_product_categories`

This is Pinterest's strongest unique claim and it holds up. Worth building on.

### 3.7 `metrics(terms, days)` — momentum series ⚠️ 2026-08-16
Returned `None` for "mom necklace" this probe. Wired, inconsistent — needs a term in
Pinterest's index. Do not assume it populates.

### 3.8 `featured_topics(interests, country)` — "Trends in the Spotlight" ✅ 2026-08-16
The Spotlight tab. **Verified exact match** to the operator's UM screen: 5 curated topics
(`SPOTLIGHT_TOPIC_COUNT = 5`), ranked on Pin **SAVE** (`SPOTLIGHT_EVENT = "SAVE"`).
Reproduced Back to School Nail Designs, Senior Spirit Jeans, Starbucks Drink Orders,
Senior Picture Ideas, Pottery Painting Ideas — same order.

Richer than the screen shows — each topic carries:
- `name` + `description` (editorial blurb)
- `pct_growth_mom` — ⚠️ the UI multiplies this by 100: raw `3` shows as "300% MoM".
  Report the raw value ×100 or it reads 100× too small.
- `related_search_trends` — **4+ keyword seeds per topic** (`teen nails`, `first day of
  school nails`) — feed straight into the seed crawl (1.3)
- `interests` — the "Popular in Beauty and Event Planning" tags
- `time_series` — the momentum curve
- `pins` — the actual pins

Powers `scrape_spotlight.py` (sweeps all 15 interest dropdowns). A real discovery source:
5 topics × their keyword seeds × momentum, and it is SAVE-ranked (aspiration, not
purchase intent — pair with 3.6's OUTBOUND_CLICK to tell dreaming from buying).

### 3.9 Still UNPROBED Pinterest surface ❓
`category_metrics`, `category_demographics`, `top_products`, `etsy_competitors`
(Pinterest's view of Etsy competitors per category), `editorial_content`,
`product_categories`, `split_forecast`, `predicted_days`. Wired, not re-probed this
session. **Assume nothing until probed.**

---

## HOW THEY FEED THE DECISION (the loop)

```
DISCOVER   1.3 seed crawl (private)  ·  1.4 trending (private)  ·  3.2 related (pinterest)
MEASURE    1.1 results-data (private)  +  2.1 SERP (public)
JUDGE      winnability = 1.1 volume/supply  ·  profit gate = 1.1 price band
TIME       1.2 chart-series cycle (private)  +  3.1 moments (pinterest)   ← BOTH have timing
GENERATE   2.2 tags/breadcrumb/type (public)  →  blueprint
TRACK      2.1 + shop scraper (public), over time
LEARN      launches vs outcomes (local)
```

**The correction that prompted this doc:** TIME was thought to be Pinterest-only. It is
not — Etsy's `chart-series` (1.2) gives a per-keyword seasonal cycle by itself.
Pinterest's *unique* contribution narrows to demographics (3.5) and click-vs-save intent
(3.6) — both of which are still **unverified** and must be probed before they are built
on.

---

## WHAT IS ACTUALLY VERIFIED vs ASSUMED — the honest scoreboard

| Verified working ✅ | Verified dead ❌ | Wired but empty/None ⚠️ | Never probed ❓ |
|---|---|---|---|
| results-data (full) | similar_search_terms | pinterest demographics | category_metrics |
| chart-series (cycle+compare) | market_gap_recommendations | pinterest metrics | etsy_competitors |
| similar_keywords (tree) | | | top_products |
| trending (7 taxonomies) | | | featured_topics |
| public SERP + cards | | | predicted_days forecast |
| listing tags/breadcrumb/type | | | |
| moments calendar | | | |
| related_terms / prefix_match | | | |
| **top_categories (intent!)** | | | |

**Where Pinterest's unique value now stands, proven:** the click-vs-save intent split
(3.6) is real and queryable — Pinterest's strongest claim and it holds. Demographics
(3.5) returned empty and stays unproven; probe on a populated term before building on it.
Everything else about a keyword — demand, competition, seasonality — Etsy already
answers on its own.
