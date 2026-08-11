# 04 — Data Model

*The stores as they exist on disk today, read directly from the SQLite files —
not from the `CREATE TABLE` statements in code. Then the temporal and guard
columns each one needs.*

Read read-only on 2026-08-11 via `PRAGMA table_info` + `COUNT(*)`.

---

## The stores

| Store | File | Size | Tables | Rows | Owner module | Status |
|---|---|---|---|---|---|---|
| Market intelligence | `market_intelligence.db` | 28 KB | 3 | **0 · 0 · 0** | `core/database.py` | **exists, empty** |
| Graph | `etsy/data/graph/graph.db` | 300 KB | 3 | 25 · 252 · 304 | `core/graph_db.py` | exists, populated |
| Pinterest series | `pinterest/data/series.db` | 128 KB | 1 | 354 | `pinterest/endpoints/series_store.py` | exists, populated |
| Pinterest history | `pinterest/data/history.db` | 132 KB | 1 | 600 | `pinterest/products/history.py` | exists, populated |
| File caches | `etsy/data/cache/`, `pinterest/data/cache/`, `seo/cache/`, `public/data/raw/` | — | — | — | 5 modules | ad hoc JSON, no schema |
| Reports | `etsy/data/reports/*.json` | — | — | — | 3 engines | terminal output, never re-read |

### The headline number

**`market_intelligence.db` is empty. All three tables, zero rows.** This is the
store the product spec treats as the fusion point of the three sources. It has been
created (the file exists, the schema applied) and never successfully written to.

That is consistent with — and independently confirms — the dead-flow analysis in
`03_data_flow.md`: `keywords` has no working writer (`private_blueprint.py` won't
parse), `trends` has no writer at all (no `upsert_trend` method exists), and
`listings` writes are wrapped in `except Exception: pass` at `grid_analytics.py:226`.

Meanwhile the Pinterest half holds 954 rows across two stores and the shared graph
holds 581. **The data exists. It just never reaches the table that matters.**

---

## `market_intelligence.db` — declared at `core/database.py:17-69`

### `keywords` — 0 rows

| Column | Type | Kind | Notes |
|---|---|---|---|
| `keyword` | TEXT **PK** | key | ⚠️ **PK is the keyword alone → one row per keyword, forever** |
| `search_volume` | INTEGER | measured | from Etsy Private `stats.searchVolume` |
| `competition` | INTEGER | measured | `stats.avgTotalListings` |
| `query_cvr` | REAL | **measured or defaulted — indistinguishable** | `private_blueprint.py:97` substitutes `0.02` when absent |
| `median_price_low` / `_high` | REAL | measured | `""` → `0.0` at `private_blueprint.py:98-99`, so "unknown" and "free" collide |
| `last_updated` | TIMESTAMP | — | overwritten on every upsert |

**Writers:** `private_blueprint.py:93` only — and it never reaches that line, because
`EtsyPrivateAPI()` at `:15` **(FIXED)**: No longer fails on missing `req_5.py`. It now pulls `ETSY_SHOP_ID` and `ETSY_CSRF_TOKEN` from `.env` populated by the Chrome extension.
**Readers:** `grid_analytics.py:34`, `master_arbitrage.py:241`.

### `listings` — 0 rows

| Column | Type | Kind | Notes |
|---|---|---|---|
| `listing_id` | TEXT **PK** | key | ⚠️ one row per listing, forever |
| `shop_name` | TEXT | measured | |
| `price` | REAL | measured | |
| `estimated_sales` | INTEGER | **derived** | Holds **two different quantities**: a lifetime ratio estimate (`grid_analytics.py:152`) or a 30-day extrapolation (`:158`). Nothing records which. |
| `estimated_views` | INTEGER | **derived from derived** | `lifetime_sales / cvr`, `cvr` defaulting to `0.02` (`:163`) |
| `velocity_score` | TEXT | **derived** | stores `"HOT 🔥"` — a display string, not a category |
| `top_flaws` | TEXT | **LLM-generated** | DeepSeek output (`core/llm_client.py:16`) in the same row as scraped facts |
| `last_updated` | TIMESTAMP | — | overwritten |
| `daily_sales`, `daily_views`, `scarcity_stock` | INTEGER | measured, **`0` is ambiguous** | `0` = "urgency badge absent", not "zero". Added by `ALTER TABLE` at `:60-65` |
| `demand_signals` | TEXT | measured | JSON array of badge strings |

**Writers:** `grid_analytics.py:214`, `single_listing_analytics.py:151`,
`sentiment_analytics.py:77`. **Readers:** `master_listing_analyzer.py:71`.

⚠️ `sentiment_analytics.py:77` calls `upsert_listing_flaws`, which inserts only
`(listing_id, top_flaws)` — `core/database.py:140-146`. On a **new** listing id this
creates a row where every metric column is `NULL`. On an existing one the
`ON CONFLICT` clause correctly updates only `top_flaws`. So the same method either
patches or creates a mostly-empty row depending on prior state.

### `trends` — 0 rows

| Column | Type | Kind |
|---|---|---|
| `trend_name` | TEXT **PK** | key |
| `dominant_color`, `demographic`, `takeoff_timestamp` | TEXT | measured (Pinterest) |
| `last_updated` | TIMESTAMP | — |

**Writers: none — and the absence is by design.** `core/database.py` defines
`get_trend` at `:167` and no setter, because
`_old_etsy_master_architecture.md:119,129` assigns the write to the **separate
Pinterest agent**: *"Pinterest's Demographics, Dominant Colors, and Takeoff
Timestamps are saved by the Pinterest Agent directly into the `trends` table."*

So this is not a forgotten method. It is **one side of a two-agent contract**, and
the writing side was never implemented — the Pinterest code writes to `series.db`
and `history.db` and never opens `market_intelligence.db`. The table is the
designated Pinterest→Etsy join point, and it is the single highest-leverage missing
piece in the repo (~30 lines). See `07_gaps_and_risks.md` §U-1.

### Schema migrations

`core/database.py:59-67` — four `ALTER TABLE` calls, each wrapped in
`try: … except: pass`. Verified against the live file: **all four columns did
apply.** But the bare `except` also swallows genuine errors (a typo'd column, a
locked database), so a migration that silently fails is indistinguishable from one
that already ran.

---

## `graph.db` — declared at `core/graph_db.py:11-54`

The best-structured store on the Etsy side, and the **only one both halves write to**
(`etsy/engines/ssr_graph_pipeline.py` and `pinterest/pipelines/pin_graph_pipeline.py`).

| Table | Rows | PK | Notes |
|---|---|---|---|
| `nodes` | 25 | `term_id` | 22 columns; 7 added by the additive migration at `:56-72` so Pinterest nodes stop writing NULLs |
| `edges` | 252 | `(src, dst, edge_type)` | Deliberately promoted out of `nodes.edges_json` because a blob *"could not be queried at all"* (`:39-40`) |
| `frontier` | 304 | `term` | BFS queue; popped shallowest-first (`:180-181`) |

**What it gets right:** `fetched_at` exists (`:26`); `source` distinguishes
`'etsy'` from `'pinterest'` (`:61`); `update_node` was added specifically so partial
writes stop nulling earlier columns (`:108-114`).

**What it still gets wrong:** `add_node` uses `INSERT OR REPLACE` (`:77`) and the PK
is `term_id` alone — so re-crawling a term **destroys its previous observation**.
`fetched_at` records when the *surviving* row was written, not a history. Same defect
as `core/database.py`, one layer more subtle.

⚠️ `nodes.edges_json` (`:29`) is still written at `:97` even though `edges` superseded
it. Dead column, dual-written.

---

## `series.db` — declared at `pinterest/endpoints/series_store.py:66-72`

| Column | Type | Notes |
|---|---|---|
| `term`, `country`, `end_date` | TEXT **composite PK** | ✅ `end_date` in the key → one row **per observation window**, not one per term |
| `source` | TEXT | ✅ `'metrics'` \| `'related'` \| `'prefix'` — **provenance, persisted** |
| `points` | TEXT | JSON array of weekly counts |
| `n` | INTEGER | length, used to refuse downgrades (`:88`) |
| `growth_json` | TEXT | stored rather than re-derived, because growth rates *"are not reliably recomputable from the rounded counts"* (`:108-110`) |

**354 rows.** This is the only Etsy-or-Pinterest table that persists a provenance
column, and the precision (`exact`/`approx`) is derived from it on every read at
`:134`. **This is invariant #1, implemented.** It is the model the other stores
should copy.

Partial on invariant #2: `end_date` in the PK gives per-window history, but two
fetches on the same `end_date` still overwrite (`INSERT OR REPLACE` at `:91`) — with
the important mitigation that `put()` refuses to overwrite with a *worse* source.

---

## `history.db` — declared at `pinterest/products/history.py`

| Column | Notes |
|---|---|
| `week`, `country`, `preset`, `interest`, `term` | **composite PK including `week`** |
| `rank`, `search_count`, `seasonality`, `mom`, `yoy`, `wow`, `mom_rank` | measured |

**600 rows.** ✅ **This is the one table in the entire repo that fully satisfies
invariant #2.** Because `week` is part of the primary key, writing week N+1 cannot
destroy week N. It is append-only by construction, which is why
`history.rank_history()` (`:88`) and `longevity()` (`:98`) can exist at all — and why
`alerts.py` can diff two weeks.

**Every other time-varying table in this repo should be shaped like this one.**

---

## Invariant scorecard

| Store | 1. Provenance tagged | 2. Append-only | 3. Source-agnostic |
|---|---|---|---|
| `market_intelligence.db` | ❌ none | ❌ 3 upserts overwrite | ❌ columns mirror Etsy's response shape |
| `graph.db` | ⚠️ `source` column, but no measured/derived flag | ❌ `INSERT OR REPLACE`, PK lacks time | ⚠️ `source` + `node_type` make it *partly* source-agnostic |
| `series.db` | ✅ `source` → `precision` on read | ⚠️ per-`end_date`, but same-date overwrites (guarded by rank) | ✅ three sources behind one shape |
| `history.db` | ❌ no provenance column | ✅ **`week` in PK** | ✅ |

---

## What's missing entirely

Tables the product requires that have no schema anywhere:

| Table | Required by | Why it cannot wait |
|---|---|---|
| **`rank_observations`** | `MIGRATION_AND_OPERATIONS.md:46-52`, D-04 | Rank on a given day is unobservable retroactively. Every day without it is permanently lost. |
| **`launches`** | D-04, D-12 | Must store the **literal feature values** used at prediction time, never foreign keys — otherwise LEARN evaluates a prediction that was never made (`DECISION_LOG.md:43-51`). Cannot be backfilled after outcomes are known. |
| **`run_state`** | `MIGRATION_AND_OPERATIONS.md:120-121` | stage · started · finished · rows written · errors. Health question #1 is unanswerable without it. |
| **Bronze raw archive** | `MIGRATION_AND_OPERATIONS.md:70-74` | Without it, fixing a bad derivation means re-fetching and re-spending quota instead of replaying. |
| **Profit / cost inputs** | D-01, `GOAL.md:104-120` | No fee, COGS, shipping, or labor field exists in any table. The central metric has nowhere to live. |

---

## Target shape for the time-varying tables

Copy `history.db`'s pattern. For `keywords`:

```sql
CREATE TABLE keyword_observations (
    keyword          TEXT    NOT NULL,
    collected_at     TEXT    NOT NULL,     -- ← in the PK. this is the whole fix.
    source           TEXT    NOT NULL,     -- 'etsy_private' | 'etsy_official' | ...
    search_volume    INTEGER,
    competition      INTEGER,
    query_cvr        REAL,
    cvr_source       TEXT    NOT NULL,     -- 'measured' | 'default'  ← D-06 guard flag
    median_price_low REAL,
    median_price_high REAL,
    capped           INTEGER DEFAULT 0,    -- sentinel clamped
    noisy            INTEGER DEFAULT 0,    -- series too sparse to trust
    PRIMARY KEY (keyword, collected_at, source)
);

CREATE VIEW keywords_latest AS
SELECT * FROM keyword_observations k
WHERE collected_at = (SELECT MAX(collected_at) FROM keyword_observations
                      WHERE keyword = k.keyword);
```

Every reader that calls `get_keyword()` today reads the view instead and does not
change. That is what makes this migration additive and low-risk — and why
`MIGRATION_AND_OPERATIONS.md:41-44` puts it before anything else.

The same treatment applies to `listings` (add `collected_at` to the PK) and to
`estimated_sales`, which must split into two columns — `sales_lifetime_est` and
`sales_30d_est` — each with its own `basis` column recording which derivation
produced it.

**Row counts are zero. There is no data to migrate. This is the cheapest this fix
will ever be.**

---

*Continue to [05_module_map.md](05_module_map.md).*
