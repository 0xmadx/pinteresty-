# What's Actually There — Pipelines & Endpoints

*Originally extracted from the uploaded docs as an inventory to be verified.*

> ✅ **VERIFIED AGAINST THE CODE 2026-08-11.** The seven open questions at the
> bottom are now answered with file:line evidence, and the claims this document
> got wrong have been corrected in place. Corrections are marked **[was wrong]**.
> The verified bias picture lives in `architecture/bias_audit.md`.

---

## Pipelines (from etsy_master_architecture.md + etsy_analytics.md + etsy_engines.md)

### Analytics pipelines (`etsy/analytics/`)

| Pipeline | Does | Bias risk |
|---|---|---|
| `grid_analytics.py` (W1) | top listings for a keyword → est sales, est views (injects CVR), in-cart | **B-01 survivorship** — top listings only; **B-03 badge** |
| `single_listing_analytics.py` (W2) | one listing → ld+json reviewCount, "20+ in cart" regex, est views = sales ÷ CVR | **B-03, B-06, cvr default 0.02** |
| `shop_analytics.py` (W3) | shop total sales, reviews, age | baseline for ratio estimator |
| `daily_tracker.py` (W3.5) | today − yesterday sales = **Daily Delta** | 🔴 **[was wrong]** — described as "✅ the one measured number". It has **never produced a number**: it diffs against `etsy/analytics/tracking_data.json`, which does not exist, and **nothing calls `run_daily_tracker`**. B-03's mitigation ("calibrate against the Daily Delta") is currently uncomputable. |
| `ratio_estimator.py` (W3.6) | shop sales/reviews × listing reviews | **B-06 uniform review propensity** |
| `sentiment_analytics.py` (W4) | negative reviews → DeepSeek → top 3 flaws | ⚠️ star filter contradiction (1-3 vs 1-4) |
| `seo_analytics.py` (W5) | rip 13 tags + materials | **B-02 rank causality**; writes to JSON not DB (6th silo) |

### Engine pipelines (`etsy/engines/`)

| Pipeline | Does | Bias risk |
|---|---|---|
| `master_arbitrage.py` | private demand vs public supply, 7-dim matrix | ✅ empty-bracket trap **fixed** (`find_gaps`, D-10). Hybrid: 14 direct API calls + 1 sub-pipeline. **B-01 stands.** |
| `master_listing_analyzer.py` | URL → single + sentiment + SEO in sequence | ✅ genuinely composition — 0 direct API calls, 3 sub-pipelines. The only true composer. 3× page fetch confirmed. |
| `private_blueprint.py` | **single-keyword deep dive** — settled | **[was wrong]** the "1000-keyword crawler" description is false; docstring and single-row write both confirm one keyword. ⚠️ **P-3 live**: `:96` defaults CVR to 0.02 without setting `cvr_source`. |
| `master_niche_finder.py` (W9) | crawl → score → deep dive → profit gate | **[was wrong]** — labelled "composition". It is **not**: 3 direct API calls, **zero** sub-pipeline instantiations, and it owns the BFS crawl, the scoring call and the D-01 profit gate. ⚠️ **N-01**: scores on demand+supply only, which cannot discriminate. |
| `private_recursive_spider.py` (W7) | related-searches graph + LLM edges | LLM hallucination (docs' own note) |
| `private_comparison.py` (W6) | bulk keyword demand/supply compare | — |
| `ssr_graph_pipeline.py` (W6.5) | backend niche scoring | — |

### Generator (`etsy/generators/`)

| Pipeline | Does | Bias risk |
|---|---|---|
| `listing_generator.py` (W10) | triple-pass tag blend → title/desc/tags | **B-02** — copies top-listing tags = copies symptoms |

---

## Endpoints (from etsy_api_private.md + etsy_api_public.md + core_architecture.md)

### Private API (`etsy/api/private/api.py` — `EtsyPrivateAPI`)

| Endpoint | Returns | Notes |
|---|---|---|
| Search Autosuggest | keyword derivatives | seeds discovery |
| Search Volume & Analytics | `search_volume`, `query_cvr` | **metered** — the scarce resource |
| `get_trending_terms` (W6.8) | trending terms per category | no quota per docs |

Auth: `x-api-key` (app client id). `registry.json` caches endpoint/GraphQL schemas.

### Public API (`etsy/api/public/`)

| Module | Endpoint | Returns |
|---|---|---|
| `api.py` (`EtsyPublicAPI`) | search grids, shop pages (HTML) | `organic_listings_count`, SERP |
| `listing_api.py` | `/listing/{id}` | shop_name, favorites, in_cart, ld+json reviewCount, badges |
| `reviews_api.py` | `/api/v3/ajax/shop/{id}/reviews` | up to 100 reviews; needs csrf_token |

⚠️ **Reviews endpoint named 3 ways** across docs: `deep_dive_reviews` (GraphQL) /
`/api/v3/ajax/shop/{id}/reviews` (REST) / `AsyncApiSpec` (internal). One is current.

### Core (`core/`)

| Module | Role |
|---|---|
| `database.py` | `market_intelligence.db` — keywords, listings, trends tables |
| `llm_client.py` | DeepSeek wrapper (flaw synthesis) |
| `shop_scraper.py` | shop total_sales, total_reviews |
| `graph_db.py` | semantic keyword graph — **the real Pinterest↔Etsy join** |
| `session_manager.py`, `endpoints_manager.py` | HTTP/session config |

---

## The calibration mechanisms (clever, but check the bias)

| Mechanism | Claim | Verified status |
|---|---|---|
| Free/Metered ratio (Free = 1.256 × Metered) | scrape supply free | 🔴 **NOT BUILT.** **[was wrong]** — listed here as a working mechanism. The constant `1.256` **appears in no source file in the repo**, and no calibration code exists. This is a design idea that was never implemented, not a mechanism with a drifting ratio. Tracked as **M-6**. |
| CVR injection | est views = sales ÷ CVR | ⚠️ **confirmed** — defaults to `0.02` in 4 places. `cvr_source` now exists as a column and both analytics pipelines set it; **`private_blueprint.py:96` does not** (P-3). |
| Ratio estimator | listing sales from shop ratio | ⚠️ **B-06 confirmed** — `derivations.sales_ratio`. Mitigation the doc asks for **is present**: basis flagged, badge preferred. |
| Badge override | exact math replaces guess | 🔴 **B-03 confirmed and WORSE** — `derivations.py:56` returns the badge as the *chosen* estimate, ranked above the ratio. It is a point estimate, not the upper bound the mitigation requires. |
| Daily delta | measured 24h sales | 🔴 **NEVER RUN.** No `tracking_data.json`, no caller. See the pipeline table above. |

---

## The `trends` table — resolved

**The doc was right about the diagnosis, and is now out of date on the fix.**

At audit time the `trends` table had **zero writers and zero rows** while
`master_arbitrage.py` read from it — the read path was dead. `etsy_master_architecture.md`
§5-6 calling it "solved" was false.

Since then:

| Then | Now |
|---|---|
| `trends` — no writer, 0 rows | superseded by **`trend_observations`** (append-only, `collected_at` in the PK) + a `trends_latest` view. The legacy `trends` table is kept so old databases still open, and deliberately still has no writer. |
| "Pinterest imports nothing from `core/`" | **two real joins exist**: `pin_graph_pipeline.py:17` → `core.graph_db`, and `trends_bridge.py:44` → `core.database`. |

⚠️ The narrower claim **remains true**: `pinterest/products/` imports nothing from
`core/`. The joins are in `pinterest/pipelines/`, which is the correct place for them —
products are leaf tools, pipelines cross the boundary.

---

## The seven doc-vs-code gaps — ANSWERED 2026-08-11

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | `private_blueprint.py` — one tool or two? | **One.** Single-keyword deep dive. The crawler description is false. | its own docstring; writes a single row |
| 2 | Which reviews endpoint is live? | **`deep_dive_reviews` `AsyncApiSpec`** — a JSON POST spec. **Not** GraphQL, **not** `/api/v3/ajax/shop/{id}/reviews`. | `reviews_api.py:36` |
| 3 | Star filter 1-3 or 1-4? | **1-3.** The old master doc is right; `_old_etsy_analytics.md` is wrong. | `sentiment_analytics.py` filters `rating <= 3` |
| 4 | `trends` table — written or aspirational? | **Was aspirational** (0 writers, 0 rows). **Now written** via `trend_observations`. | see the section above |
| 5 | CVR default 0.02 — where, and does `cvr_source` exist? | Fires in **4 places**. The column **exists** and both analytics pipelines set it. **`private_blueprint.py:96` does not** → lands as `unspecified`. **Open: P-3.** | `derivations.py:62`, `database.py:122` |
| 6 | Free/metered 1.256 — hardcoded or re-measured? | **Neither — it does not exist.** The constant appears in no source file; no calibration code was ever written. | repo-wide grep: 0 hits |
| 7 | `master_` scripts — composition or unique logic? | **Mixed, and the labels above were wrong.** Only `master_listing_analyzer` is true composition (0 API calls, 3 sub-pipelines). `master_niche_finder` is **not** composition (3 API calls, 0 sub-pipelines). `master_arbitrage` is a hybrid (14 + 1). | call-site counts |

**Bonus correction — the reviews endpoint sends `"page": 1` only.** The claim "up to 100
reviews" is wrong: it fetches **one page**.

---

## What is still open after this verification

| # | Item | Why it matters |
|---|---|---|
| **N-01** | Demand+supply scoring collapses to 0.500 for every candidate | A ranking that looks meaningful and is not — the exact failure this project names as its reason to exist. Needs *dimensions*, not guards. |
| **P-3** | `private_blueprint.py:96` stores a defaulted CVR untagged | A derived value indistinguishable from a measured one — invariant 1. |
| **B-01** | No survivor ratio | The denominator is unnamed. Data is already fetched (`api.py:114,162`) and discarded. |
| **B-03** | Badge is a point estimate, not a bound | Cannot be fixed until the daily delta actually produces a number. |
| **W3.5** | Daily delta never runs | Blocks B-03. No `tracking_data.json`, no caller. |
| **M-6** | The 1.256 calibration | Described for years, never built. Decide: build it or delete the claim. |
