# 05 — Module Map & Capability Count

*Every module by layer, and the de-duplicated capability count that resolves open
decision **O-4**. Counted from functions, never from descriptions.*

Measured by AST over the repo on 2026-08-11:

| Metric | Count |
|---|---|
| Python modules (excluding `.venv/`) | **59** |
| …that parse | **59** (was 58 — `etsy/engines/private_blueprint.py:13` was fixed mid-pass) |
| …that fail to parse | **0** |
| Classes | 25 |
| Callables (incl. private and dunder) | **235** |
| Public callables | **176** |

---

## Modules by layer

Layer assignment is by **what the module actually does**, not by which folder it
sits in. Where those disagree, the row says so.

### Layer 0 — Access (black box: studied, never modified)

| Module | LOC | Public callables | Status |
|---|---|---|---|
| `core/settings.py` | 45 | 0 (frozen dataclass) | exists — ⚠️ hardcoded absolute Windows paths at `:32,34` |
| `core/session_manager.py` | 86 | 3 (`get`, `post`, `request`) | exists — the one clean seam |
| `core/cookie_server.py` | 54 | 1 (`update_cookie`) | exists — FastAPI receiver; **merged 2026-08-11** to route both platforms via a `platform` field ⚠️ writes both credentials to the tracked `.env` (§S-1) |
| ~~`pinterest/core/cookie_server.py`~~ | — | — | ✅ **deleted 2026-08-11** — duplicate resolved |
| `pinterest/core/client.py` | 45 | 2 | exists — separate httpx path; does not use `SessionManager` |
| `pinterest/core/extract_cookie.py` | 27 | 0 | exists — script, no callables |
| `pinterest/core/scraper_test.py` | 69 | 1 | exists — ad hoc probe |
| `chrome_extension/` | — | — | exists (JS) — cookie relay |

### Layer 1 — Source clients

| Module | LOC | Public | Status |
|---|---|---|---|
| `pinterest/endpoints/api.py` | 562 | 17 | **exists, works** — 15 distinct endpoints |
| `pinterest/endpoints/constants.py` | 198 | 3 | exists |
| `etsy/api/public/api.py` | 213 | 3 | **exists, works** |
| `etsy/api/public/listing_api.py` | 146 | 1 | exists, works — ⚠️ no caching |
| `etsy/api/public/reviews_api.py` | 218 | 2 | exists, works — ⚠️ fabricates ratings (`:199`) |
| `core/shop_scraper.py` | 103 | 1 | exists, works |
| `etsy/api/private/api.py` | 188 | 4 | **exists, NON-FUNCTIONAL** — `:16` reads a missing path |
| `core/endpoints_manager.py` | 83 | 2 | exists — cURL→config parser |
| `core/llm_client.py` | 53 | 1 | exists — DeepSeek wrapper |

### Layer 2 — Guards

**Empty layer.** No `guards.py`, no single boundary. Three ad-hoc guard sites:
`series_store.py:142` (refuse degraded), `private_scoring_pipeline.py:110-116` (CVR
and supply gates), `etsy/api/public/api.py:165` (reject empty parse).

### Layer 3 — Storage

| Module | LOC | Public | Store | Rows |
|---|---|---|---|---|
| `core/database.py` | 179 | 7 | `market_intelligence.db` | **0** |
| `core/graph_db.py` | 206 | 10 | `graph.db` | 581 |
| `pinterest/endpoints/series_store.py` | 164 | 8 | `series.db` | 354 |
| `pinterest/products/history.py` | 182 | 9 | `history.db` | 600 |

### Layer 4 — Analysis (pure compute)

| Module | LOC | Public | Pure? |
|---|---|---|---|
| `pinterest/endpoints/local_math.py` | 155 | 8 | ✅ **fully pure**, imports nothing internal |
| `etsy/analytics/derivations.py` | 92 | 4 | ✅ **added 2026-08-11** — fully pure. The sales/views arithmetic lifted out of both pipelines, where it was duplicated and only reachable over the network. Tested offline. |
| `etsy/analytics/profit.py` | 196 | 6 | ✅ **added 2026-08-11** — fully pure. Fees, unit economics, margin floors, weekly capacity, three-way `compare()`. The D-01 metric, implemented. |
| `etsy/analytics/scoring.py` | 187 | 4 | ✅ **added 2026-08-11** — fully pure. Percentile normalization, weighted sum, pool guard, margin-floor gate, degeneracy detection, `explain()`. The D-02 method, implemented. |
| `etsy/analytics/gaps.py` | 143 | 3 | ✅ **added 2026-08-11** — fully pure. Per-type dimension applicability + the demand-in-bracket gate. The D-10 correction, implemented. |
| `etsy/api/public/api.py::parse_search_html` | — | 1 | ✅ pure (`:96` says so, and it is) |
| `etsy/analytics/ratio_estimator.py` | 88 | 1 | ❌ does file I/O; and reads a path nothing writes (`:27`). **Now superseded** — `derivations.sales_ratio()` is the tested version of its core maths. |

**This layer is 8 functions and one method.** Everything else that computes is
welded to I/O inside a pipeline class. There is no `profit.py`, no `scoring.py`, no
`gaps.py`, no `platform.py`, no `calibration.py`.

### Layer 5 — Analytics pipelines (Etsy)

| Module | LOC | Public | Status |
|---|---|---|---|
| `etsy/analytics/grid_analytics.py` | 257 | 2 | exists — 4 phases in one 180-line `run()` |
| `etsy/analytics/single_listing_analytics.py` | 182 | 2 | exists |
| `etsy/analytics/sentiment_analytics.py` | 98 | 1 | exists — LLM path |
| `etsy/analytics/seo_analytics.py` | 77 | 1 | exists |
| `etsy/analytics/shop_analytics.py` | 75 | 1 | exists |
| `etsy/analytics/daily_tracker.py` | 77 | 1 | exists |

### Layer 5 — Products (Pinterest)

| Module | LOC | Public | Status |
|---|---|---|---|
| `pinterest/products/market_intel.py` | 212 | 10 | exists — incl. `Taxonomy` class |
| `pinterest/products/moodboard.py` | 196 | 6 | exists |
| `pinterest/products/keyword_research.py` | 191 | 6 | exists |
| `pinterest/products/content_calendar.py` | 188 | 4 | exists |
| `pinterest/products/ad_targeting.py` | 169 | 5 | exists |
| `pinterest/products/alerts.py` | 163 | 5 | exists |
| `pinterest/products/audience.py` | 140 | 5 | exists |
| `pinterest/products/cli.py` | 74 | 1 | exists — the only real CLI |

### Layer 6 — Orchestration

| Module | LOC | Status |
|---|---|---|
| `etsy/engines/master_arbitrage.py` | 270 | exists — 240-line god-method, 7 inline sections |
| `etsy/engines/master_niche_finder.py` | 122 | exists — **depends on the dead Private tier** |
| `etsy/engines/master_listing_analyzer.py` | 95 | exists |
| `etsy/engines/ssr_graph_pipeline.py` | 123 | exists — **depends on the dead Private tier** |
| `etsy/engines/private_recursive_spider.py` | 99 | exists — **dead tier** |
| `etsy/engines/private_comparison.py` | 59 | exists — **dead tier** |
| `etsy/engines/private_scoring_pipeline.py` | 178 | **broken** — imports `src.services.executor` (missing) |
| `etsy/engines/private_blueprint.py` | 103 | parses ✅ (fixed mid-pass) — still **non-functional**: depends on the dead Private tier |
| `etsy/generators/listing_generator.py` | 246 | exists — **depends on the dead Private tier** |
| `pinterest/pipelines/pin_graph_pipeline.py` | 162 | exists |
| `pinterest/pipelines/scrape_search.py` | 60 | exists |
| `pinterest/pipelines/scrape_shopping.py` | 64 | exists |
| `pinterest/pipelines/scrape_spotlight.py` | 37 | exists |

### Layer 7 — Serving

**Empty layer.** No FastAPI app, no routes, no `api/` package. `MIGRATION_AND_OPERATIONS.md:84-88`
places this before the UI; it has not been started.

### Tests

| Module | LOC | Needs network? |
|---|---|---|
| `pinterest/tests/test_live_endpoints.py` | 364 | yes |
| `pinterest/tests/test_shopping_endpoints.py` | 242 | yes |
| `pinterest/tests/test_spotlight_moments.py` | 224 | yes |
| `pinterest/tests/test_products.py` | 272 | yes |
| `pinterest/tests/test_local_derivations.py` | 158 | **no** ✅ |
| `pinterest/tests/audit_capture_coverage.py` | 152 | no — doc/impl coverage audit |
| `pinterest/tests/backfill_series_store.py` | 46 | yes — utility, not a test |

⚠️ These are hand-rolled scripts with a `check(name, passed, detail)` helper, not
pytest. There is no `pytest.ini`, no `conftest.py`, no CI. **Coverage of `core/` and
`etsy/` — 28 of 59 modules, including every database writer — is zero.**

---

## The capability count — resolving O-4

`START_HERE.md:98` claims *"~45 → likely ~28–32 real"*, sourced to
`CAPABILITY_COUNT_DEDUP.md`. **That document does not exist in this repo**, so the
"~45" figure cannot be reconciled against its own derivation. What follows is a
bottom-up count from functions, per D-09 (`DECISION_LOG.md:95-103`).

### Counting rules

| Rule | Applied |
|---|---|
| Count functions, not descriptions | ✅ every row below names a callable |
| Compositions are **pipelines**, not tools | ✅ the 13 orchestrators are excluded from the tool count |
| Collapse shared functions | ✅ `report()` appears in 8 Pinterest modules — counted as one presentation pattern, not 8 tools |
| Exclude infrastructure | ✅ repositories, session, config, parsers, constructors, `_`-prefixed helpers |
| Exclude formatters | ✅ `to_ics`, `to_html`, `report` |
| Mark functionless claims aspirational | ✅ see below |

### The count

| Category | Count | Functional today |
|---|---|---|
| **Source capabilities** — distinct provider endpoints | **26** | **22** |
| ├ Pinterest (`endpoints/api.py`) | 15 | 15 |
| ├ Etsy Public (search, listing×2, reviews×2, shop) | 6 | 6 |
| ├ Etsy Private (results, chart, similar, trending) | 4 | **0** — tier dead |
| └ LLM (`analyze_sentiment`) | 1 | 1 |
| **Derivations** — pure compute | **~27** | ~25 |
| ├ `local_math.py` | 8 | 8 |
| ├ `series_store` module-level | 2 | 2 |
| ├ Pinterest product derivations | ~12 | 12 |
| └ Etsy parsers/estimators | ~5 | 3 (2 are duplicates; `ratio_estimator` is dead) |
| **Operator tools** — compose into an answer | **31** | **23** |
| ├ Pinterest products | 23 | 23 |
| └ Etsy analytics + generator | 8 | **0 trustworthy** (all depend on untagged derivations and/or the dead tier) |
| **Pipelines** (excluded from tool count) | 13 | 6 |

### The answer to O-4

> **~31 distinct operator-facing tools exist as functions. 23 of them work today,
> and all 23 are Pinterest.**
>
> Zero Etsy operator tools return a number the system can vouch for — not because
> the code is absent, but because the demand tier is dead and every Etsy derivation
> is stored untagged (see `03_data_flow.md` §Provenance ledger).

The "~28–32" estimate happens to bracket the structural count (31). It is
**coincidentally right about the number and wrong about the meaning**: the figure
describes tools that exist as code, not tools that produce trustworthy output.

### Aspirational — documented, no implementing function

| Claimed | Where claimed | Reality |
|---|---|---|
| Profit model (fees, COGS, shipping, labor) | `GOAL.md:104-120`, D-01 | **no function anywhere** |
| Percentile-normalized scoring | D-02 | **no function** — three raw-ratio formulas instead |
| Where-to-list decision (Etsy/Shopify/Pinterest) | `GOAL.md:46-48`, D-11 | **no function** |
| 7-dimension gap finder with the empty-bracket gate | D-10 | ⚠️ **partial** — `master_arbitrage.py:70-237` computes 7 dimensions but has **no demand-in-bracket gate**, which is precisely the trap D-10 exists to prevent |
| LEARN / calibration | D-12 | **no function**, no `launches` table |
| Rank tracking | `MIGRATION_AND_OPERATIONS.md:46-52` | **no function**, no `rank_observations` table |
| `private_blueprint` as "Broad Niche Finder… thousands of keyword ideas" | `docs/etsy_engines.md:25-30`, `_old_project_structure.md:35` | **contradicted by the code**, which deep-dives one keyword (`private_blueprint.py:11`) |
| **Free/metered supply calibration** — "Free = 1.256 × Metered", so supply can be scraped without quota | `_old_etsy_master_architecture.md:36` | **no function.** The constant appears in no source file. |
| **Lazy-load bypass** — forcing ranks 13-48 out of `Search2_ApiSpecs_LazyListingCards` | `_old_etsy_master_architecture.md:37`; referenced by `etsy/api/public/api.py:32-33` | **no code**, and the file it cites (`filter_relevant_aftersearch.py`) does not exist. ⚠️ Access-layer adjacent — documented here, **not** recommended for implementation. |
| **Pinterest→`trends` agent handoff** | `_old_etsy_master_architecture.md:119,129` | **no writer.** The contract is specified; only the Pinterest side is missing. See `07_gaps_and_risks.md` §U-1. |
| Daily-sales delta vs yesterday | `_old_etsy_master_architecture.md:61` | `etsy/analytics/tracking_data.json` **does not exist** — no yesterday to diff |

---

## Duplicate implementations (dedup findings)

| Duplicate | Locations | Difference |
|---|---|---|
| `_parse_count` | `core/shop_scraper.py:6`, `etsy/api/public/api.py:75` | shop_scraper strips commas first; api.py strips parens. Same job, two behaviours. |
| `get_listing_data` | `etsy/api/public/api.py:167` (method), `etsy/api/public/listing_api.py:5` (function) | **Same name, different returns** — one gives breadcrumb+tags, the other demand signals. A genuine collision. |
| `parse_date` | `grid_analytics.py:16`, `single_listing_analytics.py:14` | identical |
| ~~Cookie server~~ | ~~`core/cookie_server.py`, `pinterest/core/cookie_server.py`~~ | ✅ **resolved 2026-08-11** — merged into one server with a `platform` router |
| Scoring formula | `master_niche_finder.py:66`, `private_scoring_pipeline.py:117`, `master_arbitrage.py:85` | three formulas, three magnitudes — see `02_design_approach.md` §5 |
| `report()` | 8 Pinterest product modules | consistent pattern, not a defect — noted so it is not counted 8×|

---

*Continue to [06_stack_and_deps.md](06_stack_and_deps.md).*
