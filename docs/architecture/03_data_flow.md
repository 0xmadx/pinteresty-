# 03 — Data Flow

*One record's full life through the real modules: entry → parse → transform →
store → derive → output. Every hop names the file that performs it, and marks
where provenance and freshness survive or die.*

---

## The three flows at a glance

```
 FLOW A — ETSY SUPPLY (works)          FLOW B — PINTEREST (works)      FLOW C — ETSY DEMAND (dead)
 ─────────────────────────────         ────────────────────────        ──────────────────────────
 keyword                               preset/term                     keyword
   │                                     │                               │
   ▼ SessionManager (chrome124)          ▼ httpx + cookie file           ▼ SessionManager
 etsy/api/public/api.py                pinterest/endpoints/api.py      etsy/api/private/api.py
   │  SERP HTML                          │  JSON                         │
   ▼ parse_search_html  (pure)           ▼ _api_resource                 ✗ __init__ raises at :34
 cards[] + total_results                series/rows                       (private/ missing)
   │                                     │                               ✗ headers={} cookies={}
   ▼ listing_api / reviews_api /         ▼ series_store.put              ✗ shop_id hardcoded :38
     shop_scraper                        │  ranks source, refuses         │
   │                                     │  downgrades                    ▼
   ▼ grid_analytics  PHASE 1-4           ▼ local_math (pure)            NOTHING REACHES STORAGE
   │  3 chained derivations              │                               │
   ▼ market_intelligence.db              ▼ series.db / history.db        ▼
     listings  (UPSERT — history         │                             keywords table:
     overwritten, provenance lost)       ▼ products/*.report()           0 writers
   │                                   stdout / .ics / .html
   ▼ seo/cache/grid_report_*.json
     stdout table
```

Flows A and B **never meet.** They were designed to meet at the `trends` table in
`market_intelligence.db` — a handoff between two separate agents
(`_old_etsy_master_architecture.md:119,129`), not an import. The Etsy side of that
contract exists (`core/database.py:167` reads it); the Pinterest side that writes it
was never built. See `07_gaps_and_risks.md` §U-1.

---

## Flow A — traced hop by hop

The record: **one Etsy listing card**, from a keyword to a stored row.

| # | Hop | File:line | What happens to the record | Provenance | Freshness |
|---|---|---|---|---|---|
| 1 | **Entry** | `grid_analytics.py:54` | `get_public_search(query, filters)` called | — | — |
| 2 | **Cache gate** | `etsy/api/public/api.py:44-48` | If `etsy/data/cache/public_search_<q>.json` exists, **return it and stop** | — | ❌ **LOST HERE.** No TTL, no timestamp, no max-age. A file written months ago is served as current, silently. |
| 3 | **Fetch** | `api.py:60` → `core/session_manager.py:46-77` | HTTP via `curl_cffi` chrome124, DataDome cookie injected, up to 3 retries | — | — |
| 4 | **Parse** | `api.py:95-165` `parse_search_html` — **pure, no I/O** | HTML → `{total_results, organic_listing_ids, cards[]}`. Per card: `listing_id, title, shop_name, is_ad, rating, review_count, price, star_seller, shop_years_on_etsy` | ✅ all **measured** — read straight off the page | — |
| 5 | **Persist raw** | `api.py:70-71` | Whole payload written to `etsy/data/cache/` | — | ❌ no `collected_at` written into the file |
| 6 | **Enrich: shop** | `core/shop_scraper.py:29-103` | Fetches shop page → `total_sales`, `total_reviews`, `active_listings` | ✅ measured (LD+JSON preferred at `:101`, regex fallback at `:66-73`) | ❌ not recorded |
| 7 | **Enrich: listing** | `etsy/api/public/listing_api.py:5-146` | Fetches listing page → `favorites`, `in_cart`, `daily_sales`, `daily_views`, `scarcity_stock`, `demand_signals[]` | ✅ measured — but scraped from *urgency badges*, which Etsy renders inconsistently. `0` means "badge absent", not "zero sales". **That ambiguity is never recorded.** | ❌ **no cache at all here** — re-fetched every run, unlike hops 2/5 |
| 8 | **Enrich: reviews** | `etsy/api/public/reviews_api.py:9-118` | POSTs `deep_dive_reviews`, scrapes review **date strings** out of returned HTML | ✅ measured | `"page": 1` only — one page, despite `docs/etsy_api_public.md:17` claiming 100 |
| 9 | **Persist stage** | `grid_analytics.py:82,131` | Phases 2 and 3 dumped to `public/data/raw/batch_*.json` | — | ❌ none |
| 10 | **DERIVE ①** | `grid_analytics.py:151-152` | `lifetime_sales = review_count × (shop_total_sales / shop_total_reviews)` | ⚠️ **DERIVED.** A shop-wide ratio applied to one listing. Assumes uniform review rate across every product in the shop. | — |
| 11 | **DERIVE ② (override)** | `grid_analytics.py:157-158` | `if daily_sales > 0: lifetime_sales = daily_sales × 30` | ⚠️ **DERIVED, and it silently replaces ①.** A magic `30`. The field is named *lifetime* but now holds a 30-day extrapolation. Two different quantities in one column, with no flag saying which. | — |
| 12 | **DERIVE ③** | `grid_analytics.py:160-163` | `estimated_views = daily_views × 30`, else `lifetime_sales / cvr` | ⚠️ **DERIVED FROM A DERIVED VALUE.** And `cvr` defaults to `0.02` (`:23`) — a guess, because `get_keyword()` at `:34` returns `None` (Flow C is dead, so the table is empty). | — |
| 13 | **DERIVE ④** | `grid_analytics.py:166-185` | `velocity_score` ← days since newest review → `"HOT 🔥"` / `"STEADY 📈"` / `"SLOW 🐢"` / `"DEAD 💀"` | ⚠️ derived; stored as a **display string with an emoji**, not a category or a number | — |
| 14 | **Store** | `grid_analytics.py:214-225` → `core/database.py:108-131` | `upsert_listing_metrics(...)` → `INSERT … ON CONFLICT(listing_id) DO UPDATE` | ❌ **PROVENANCE DIES HERE.** `estimated_sales` (derived ①/②) and `estimated_views` (derived ③) land in columns beside `price` (measured) with nothing distinguishing them. | ❌ **HISTORY DIES HERE.** `last_updated` is overwritten; the previous row is gone. `core/database.py:113-115` carries a comment saying exactly this. |
| 15 | **Swallow** | `grid_analytics.py:226-227` | `except Exception as e: pass` around every write — then `:228` prints `Saved N listings to Market Database` | ❌ **Reports success when every write failed.** | — |
| 16 | **Output** | `grid_analytics.py` | `{query, survivorship, listings[]}` → `seo/cache/grid_report_<q>.json` | ✅ **fixed 2026-08-11** — the file was a bare list of listings, so a reader had the rows without the denominator and would read "these listings average 400 sales" as a fact about the niche (B-01). The survivor bound now travels *with* the rows: verdict, reviewed share, sample size, coverage, and a plain-language line. | ❌ none |
| 17 | **Render** | `grid_analytics.py:231-239` | `print()` table to stdout, columns labelled `Views (Est)` / `Sales (Est)` | ⚠️ the *only* place derivation is disclosed — in a console header, not in the data | — |

### What Flow A costs you

By hop 14, a row in `listings` contains four numbers of three different kinds —
measured (`price`), single-derived (`estimated_views` when from `daily_views`),
double-derived (`estimated_views` when from `lifetime_sales / cvr`) — and the
schema cannot tell them apart. `GOAL.md:67` defines system failure as *"a plausible
wrong number that looks authoritative."* Hop 14 manufactures one on every run.

---

## Flow B — Pinterest, for contrast

The same trace, on the half that got it right.

| # | Hop | File:line | Provenance |
|---|---|---|---|
| 1 | Entry | `pinterest/products/keyword_research.py:60` etc. | — |
| 2 | Cache gate | `pinterest/endpoints/api.py:93-103` | keyed by a slug of the actual parameters (`_slug` at `:33`) |
| 3 | Fetch | `api.py:104-139` | — |
| 4 | **Harvest** | `pinterest/endpoints/series_store.py:98-117` | A `/related_terms/` response carries a free series for terms nobody asked about; it is absorbed instead of discarded |
| 5 | **Store, ranked** | `series_store.py:76-96` | ✅ **`put()` refuses to downgrade.** An `approx` prefix series cannot overwrite an `exact` metrics series; a shorter series cannot overwrite a longer one (`:88`) |
| 6 | **Read, qualified** | `series_store.py:120-148` | ✅ Returns `{counts, source, precision, growth}`. `precision` is `"exact"` or `"approx"` on **every single read** (`:134`) |
| 7 | **Refuse** | `series_store.py:142-143` | ✅ If a sliced window's peak is below `MIN_SLICE_PEAK` (25), returns `None` — *"source rounding already destroyed it"*. `None` means **go fetch**, never *no data* (`:121-123`) |
| 8 | Derive | `pinterest/endpoints/local_math.py` (10 fns) | ✅ pure, no I/O, no internal imports |
| 9 | Output | `products/*.report()` → stdout / `.ics` / `.html` | — |

**The difference in one line:** Flow A stores a derived number as if measured;
Flow B refuses to serve a number it cannot vouch for. Both patterns are in this
repo. Only one is correct, and it is already written.

---

## Flow C — Etsy demand, dead

`GOAL.md:29-31` calls this the source of *"what's actually searched and bought"*.
Four independent breaks, any one of which is fatal:

| Break | File:line | Failure mode |
|---|---|---|
| Auth source fixed | `etsy/api/private/api.py` | **FIXED:** Previously read missing `req_5.py`. Now correctly reads credentials populated by the Chrome extension from `.env`. |
| ~~Module won't parse~~ | `etsy/engines/private_blueprint.py:13` | ✅ **fixed mid-pass** — parses now, but still constructs `EtsyPrivateAPI()` at `:15`, so break #1 above still stops it |
| Import target missing | `etsy/engines/private_scoring_pipeline.py:10` | `from src.services.executor import …`; `src/` does not exist |
| Glob target missing | `etsy/engines/private_scoring_pipeline.py:23` | `inputs/curl_commands/private/*.py`; `inputs/` does not exist |

### The consequence chain

```
private_blueprint.py  ← the ONLY caller of upsert_keyword (:93)
        │  parses now, but EtsyPrivateAPI() at :15 fails on the
        │  missing private/endpoints/req_5.py → never reaches :93
        ▼
   keywords table  ──────────────  0 writers, permanently empty
        │
        ├──► grid_analytics.py:34   get_keyword() → None
        │        └─► self.cvr stays 0.02 (a guess)
        │             └─► estimated_views = lifetime_sales / 0.02   ← Flow A hop 12
        │
        └──► master_arbitrage.py:241  get_keyword() → None
                 └─► database_intelligence.private_api_cvr   = None
                     database_intelligence.private_api_price_low  = None
                     database_intelligence.private_api_price_high = None
```

And in parallel:

```
   trends table  ──────  0 writers, 0 rows
        │        core/database.py defines get_trend at :167 and NO setter —
        │        BY DESIGN. _old_etsy_master_architecture.md:119,129 assigns the
        │        write to the separate Pinterest agent, not to a module in etsy/.
        │        That agent-side writer was never implemented.
        ▼
   master_arbitrage.py:242  get_trend() → None
        └─► database_intelligence.pinterest_trend_color    = None
            database_intelligence.pinterest_takeoff        = None
```

**`master_arbitrage.py:239-250` is labelled `MASTER DATABASE INTELLIGENCE` and is
the only place in 59 modules where the three sources are meant to combine. All five
of its fields are structurally guaranteed to be `None`.** It runs without error and
writes a report full of nulls.

---

## Where data physically lands

Six destinations, no reconciliation between any of them.

| Destination | Written by | Read by | Format |
|---|---|---|---|
| `market_intelligence.db` → `keywords` | *(nobody — writer never reaches its DB call; see Flow C)* | `grid_analytics.py:34`, `master_arbitrage.py:241` | SQLite |
| `market_intelligence.db` → `listings` | `grid_analytics.py:214`, `single_listing_analytics.py:151`, `sentiment_analytics.py:77` | `master_listing_analyzer.py:71` | SQLite |
| `market_intelligence.db` → `trends` | *(nobody — no writer exists)* | `master_arbitrage.py:242` | SQLite |
| `etsy/data/graph/graph.db` | `ssr_graph_pipeline.py`, `pin_graph_pipeline.py` | same | SQLite — **the only store both halves touch** |
| `pinterest/data/series.db`, `history.db` | `series_store.py`, `history.py` | Pinterest products | SQLite |
| `etsy/data/cache/`, `etsy/data/reports/`, `public/data/raw/`, `seo/cache/`, `pinterest/data/cache/` | five different modules | ad hoc | JSON files |

### Cache-path incoherence

Three modules disagree about where the SERP cache lives:

- `etsy/api/public/api.py:44` **writes** to `etsy/data/cache/public_search_*.json`
- `etsy/analytics/grid_analytics.py:40` creates and writes `public/data/raw/`
- `etsy/analytics/ratio_estimator.py:27` **reads** `public/data/raw/public_search_*.json`

`ratio_estimator` is therefore looking for files that `EtsyPublicAPI` never puts
there. It only ever finds anything if `grid_analytics` happened to run first in the
same working directory — and `grid_analytics` writes `batch_shops_*.json`, not
`public_search_*.json`. **`ratio_estimator.estimate_listing_sales()` returns `None`
at `:43` in every realistic invocation.**

---

## Provenance ledger

Every number the system stores, and whether it can be trusted.

| Value | Kind | Stored where | Tagged? |
|---|---|---|---|
| `price`, `rating`, `review_count`, `shop_years_on_etsy`, `star_seller` | **measured** | `listings`, cache JSON | n/a — but indistinguishable from the derived ones beside them |
| `total_results` (supply) | **measured** | cache JSON only | not persisted to SQLite at all |
| `total_sales`, `total_reviews` | **measured** | `batch_shops_*.json` | ❌ |
| `daily_sales`, `daily_views`, `scarcity_stock` | **measured, but `0` is ambiguous** (badge absent vs genuinely zero) | `listings` | ❌ |
| `estimated_sales` | **derived** ①→②, two different quantities in one column | `listings` | ❌ |
| `estimated_views` | **derived from derived**, `/0.02` fallback | `listings` | ❌ |
| `velocity_score` | **derived**, emoji display string | `listings` | ❌ |
| `top_flaws` | **LLM-generated** (DeepSeek, `core/llm_client.py:16`) | `listings` | ❌ — an LLM summary sits in the same row as scraped facts |
| review `rating` | **fabricated** — `reviews_api.py:199` defaults to `5`, only overridden if a string matches at `:203-206` | in-memory → LLM | ❌ — unmatched reviews silently become 5-star |
| review `date` | **placeholder** — `reviews_api.py:211` hardcodes `"Recent"` | in-memory | ❌ |
| `counts`, `growth` (Pinterest) | **measured** | `series.db` | ✅ `precision` + `source` on every read |

**Nine of eleven Etsy values are untagged. Both Pinterest values are tagged.**

---

## What must change in the flow

1. **Insert a guard boundary between hop 13 and hop 14** — one `ingest/guards.py`
   that stamps `collected_at`, tags `measured|derived`, records the derivation
   inputs, and clamps sentinels. Per D-06, exactly one such boundary.
2. **Make hop 14 append-only** — `collected_at` in the primary key, a `_latest`
   view for current-state reads.
3. **Kill the silent `except: pass` at hop 15** — a failed write must fail loudly.
4. **Give the cache a TTL** (hop 2) — `REPO_STRUCTURE_AND_CONFIG.md:119-128`
   already specifies per-type TTLs; none are implemented.
5. **Stop overloading `estimated_sales`** (hops 10–11) — a lifetime estimate and a
   30-day extrapolation are different quantities and need different columns.
6. **Fix or delete Flow C** — a pipeline that runs clean and emits five guaranteed
   nulls is worse than one that errors.

---

*Continue to [04_data_model.md](04_data_model.md).*
