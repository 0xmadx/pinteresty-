# 01 — System Overview

*What this system is, as it exists on branch `local-etsy-saas-project`. Every claim
cites a file. Nothing here is taken from a document's assertion alone.*

Audit date: 2026-08-11 · 59 Python modules (excluding `.venv/`) · **all 59 parse.**

> **Changed during this pass:** the audit opened with 58/59 parsing —
> `etsy/engines/private_blueprint.py:13` carried a stray `"""`. The operator removed
> it mid-pass and the module now parses. Findings below are marked ✅ RESOLVED where
> that applies. It does **not** yet cascade: the private tier is still blocked by
> three missing paths (§Broken tier), so `keywords` remains empty.

---

## The shape

```
                        ┌──────────────────────────────────────────┐
                        │  ACCESS LAYER  (black box — study only)  │
                        │  curl_cffi chrome124 · DataDome cookie   │
                        │  Chrome extension relay → .env           │
                        │  core/session_manager.py · core/settings │
                        │  core/cookie_server.py · chrome_extension│
                        └───────────────┬──────────────────────────┘
                                        │
              ┌─────────────────────────┼─────────────────────────┐
              │                         │                         │
    ╔═════════▼═════════╗   ╔═══════════▼═══════════╗   ╔═════════▼═════════╗
    ║  PINTEREST        ║   ║  ETSY PRIVATE         ║   ║  ETSY PUBLIC      ║
    ║  momentum         ║   ║  true demand          ║   ║  supply / SERP    ║
    ║  pinterest/       ║   ║  etsy/api/private/    ║   ║  etsy/api/public/ ║
    ║  endpoints/api.py ║   ║  api.py               ║   ║  api.py           ║
    ║                   ║   ║                       ║   ║                   ║
    ║  ✅ WORKS         ║   ║  ❌ NON-FUNCTIONAL    ║   ║  ✅ WORKS         ║
    ║  29 fns, tested   ║   ║  see §Broken tier     ║   ║  parses SERP HTML ║
    ╚═════════╤═════════╝   ╚═══════════╤═══════════╝   ╚═════════╤═════════╝
              │                         │                         │
              │                         └────────────┬────────────┘
              │                                      │
    ┌─────────▼──────────┐                ┌──────────▼───────────┐
    │ pinterest/products │                │ etsy/analytics       │
    │ 10 modules         │                │ etsy/engines         │
    │ pinterest/pipelines│                │ etsy/generators      │
    │ 4 modules          │                │ 16 modules           │
    └─────────┬──────────┘                └──────────┬───────────┘
              │                                      │
    ┌─────────▼──────────┐                ┌──────────▼───────────┐
    │ series.db          │                │ market_intelligence  │
    │ history.db         │                │ .db  (SQLite)        │
    │ data/cache/*.json  │                │ etsy/data/cache/*.json│
    └────────────────────┘                │ etsy/data/reports/*.json│
                                          └──────────────────────┘
              ▲                                      ▲
              └────────  intended channel: ──────────┘
                    the `trends` table handoff
              (BY DESIGN two agents, joined at the DB —
               _old_etsy_master_architecture.md:119,129)
              ⚠ NEVER IMPLEMENTED on the Pinterest side.
              0 of 79 import edges, and 0 rows in `trends`.

              ┌───────────────────────────────────────┐
              │  core/graph_db.py → etsy/data/graph/  │
              │  the ONLY module both halves import   │
              │  (ssr_graph_pipeline + pin_graph_...) │
              └───────────────────────────────────────┘
```

---

## The three sources

| Source | Entry module | Status | Evidence |
|---|---|---|---|
| **Pinterest** — momentum, audience, moments | `pinterest/endpoints/api.py` (562 LOC, 29 methods) | **exists, works** | Own test suite: `pinterest/tests/` (7 files); provenance tracked in `series_store.py:120-148` |
| **Etsy Public** — supply, competitors, SEO | `etsy/api/public/api.py` (213 LOC) | **exists, works** | `parse_search_html()` at `:95` extracts supply + cards from real SERP HTML |
| **Etsy Private** — search volume, CVR, price paid | `etsy/api/private/api.py` (188 LOC) | **exists but NON-FUNCTIONAL** | See below |

### The broken tier

`GOAL.md:29-31` calls Etsy Private the source of *"what's actually searched and
bought"* and `GOAL.md:87-89` calls its quota *"the scarce resource"* the whole
architecture is built around. It does not run.

| Break | Location | Effect |
|---|---|---|
| Reads `.env` for its auth headers (synced via Chrome Extension) | `etsy/api/private/api.py` | **FIXED:** Replaced legacy `req_5.py` dependency. The API now correctly pulls `ETSY_SHOP_ID` and `ETSY_CSRF_TOKEN` directly from `.env`. |
| Falls back to a hardcoded shop id | `etsy/api/private/api.py:32,38` | `"56057851"` — an operator-identifying constant in committed code |
| `private_scoring_pipeline.py` imports `src.services.executor` | `etsy/engines/private_scoring_pipeline.py:10` | `src/` **does not exist** → `ModuleNotFoundError` on import |
| …and globs `inputs/curl_commands/private/*.py` | `etsy/engines/private_scoring_pipeline.py:23` | `inputs/` **does not exist** → always empty |
| ~~`private_blueprint.py` has an unterminated docstring~~ | `etsy/engines/private_blueprint.py:13` | ✅ **RESOLVED during this pass** — stray `"""` removed; the module now parses |

Verified after the fix: `ast.parse` over all 59 modules → **59 OK, 0 FAIL**.

⚠️ **The three remaining breaks still make the tier non-functional.**
`private_blueprint.py` now imports, but its `EtsyPrivateAPI()` constructor still
fails at `api.py:16`, so `upsert_keyword` is never reached and `keywords` stays
empty. Verified: `src/`, `private/`, `inputs/`, `public/` are all still absent.

---

## The two processes — as designed vs as built

`DECISION_LOG.md:86-93` (D-08) specifies ingestion and serving as separate
processes meeting only at the database.

| | Designed | Built |
|---|---|---|
| Ingestion | Batch jobs write | **exists** — `__main__` blocks in `master_arbitrage.py:268`, `grid_analytics.py:241`, `pinterest/products/cli.py:61` |
| Serving | Read-only API over Gold | **missing** — no FastAPI app, no `api/` package, no route module anywhere |
| Separation | Meet only at the DB | **not applicable yet** — there is no serving process to separate |

There is no orchestrator spanning both halves. Each engine is its own entry point
with its own `if __name__ == "__main__"`. `pinterest/products/cli.py` is the only
multi-command CLI, and it covers Pinterest only.

---

## The source boundary

`DECISION_LOG.md:54-62` (D-05) requires the source to sit behind an adapter with a
normalized record contract. **No such boundary exists.**

- No `contracts.py`, no `Protocol`, no base adapter class anywhere in the repo.
- Business logic reads provider response shapes directly. Examples:
  `master_niche_finder.py:60-63` reaches into `chart["termSummaries"][].searchVolume`;
  `private_blueprint.py:27-29` reaches into `data["competitivePriceData"]["searchTermMedianPrice"]`.
- Swapping a provider today means editing every consumer, not writing one class.

The access layer itself *is* well isolated as a mechanism (`SessionManager` wraps
all HTTP), but it is isolated at the **transport** level, not the **schema** level.
That distinction is the whole of D-05, and it is the gap.

---

## Where the three invariants stand

| Invariant | Status | Where it is honored | Where it is violated |
|---|---|---|---|
| **1. Measured vs derived tagged** | **partial — one half only** | `pinterest/endpoints/series_store.py:120-148` returns `precision: "exact"\|"approx"`, ranks sources, and returns `None` rather than serve a degraded number | `core/database.py:40-41` stores `estimated_sales`/`estimated_views` with no provenance column; `grid_analytics.py:152,158,163` computes three chained derivations and stores the result as if measured |
| **2. Time is first-class** | **violated** | `graph_db.py:26` has `fetched_at`; `series_store.py` keys on `end_date` | `core/database.py:75,113,137` — three `ON CONFLICT DO UPDATE` blocks overwrite history; `graph_db.py:77,128,139` uses `INSERT OR REPLACE` |
| **3. Source is an implementation detail** | **violated** | — | No adapter or contract exists anywhere (see above) |

---

# One-page summary

## What's solid

1. **`pinterest/endpoints/series_store.py`** — the best-engineered module in the
   repo. It implements invariant #1 *correctly*: source ranking (`:32`), a refusal
   threshold (`:36`), `precision` returned on every read (`:134`), and an explicit
   contract that `None` means "go fetch", never "no data" (`:121-123`). Its module
   docstring records the measurement that justifies each choice.
2. **`core/graph_db.py`** — additive migrations (`:56-72`), edges promoted out of a
   JSON blob into a queryable table (`:39-50`), `update_node` added specifically to
   stop `INSERT OR REPLACE` from nulling columns (`:108-114`), breadth-first pop
   fixed deliberately (`:180-181`). Comments explain *why*, per the repo's own
   commenting standard.
3. **`etsy/api/public/api.py:95-165`** — `parse_search_html` is a genuine pure
   function with no I/O, correctly separating page-level supply from per-card
   signals, and documenting why a per-card form read beats a global id map (`:126-128`).
4. **The Pinterest half has tests.** 7 files under `pinterest/tests/`, including
   local-derivation tests that don't need the network.

## What's broken

1. **The three-source fusion does not happen.** Not because the design is wrong —
   `_old_etsy_master_architecture.md:119,129` specifies two agents meeting at the
   `trends` table, and the separation is deliberate. **The Pinterest side of that
   handoff was never written.** `core/database.py` exposes `get_trend` (`:167`) and
   no setter; `trends` holds 0 rows; `master_arbitrage.py:242` reads `None` forever.
   This is the highest-leverage gap in the repo and roughly 30 lines of work.
2. **The Etsy Private tier is dead** — three missing paths (§Broken tier). The
   `keywords` table's only writer now parses but still never reaches its DB call,
   because `EtsyPrivateAPI()` fails first.
3. **The profit model does not exist.** `GOAL.md:104-120` makes profit the central
   idea; there is no fee, COGS, shipping, or labor input anywhere in 59 modules.
   Every score in the repo ranks by demand/supply — the exact flaw D-01 was written
   to fix.
4. **`.env` is committed** with three live secrets, while `.gitignore:3` lists it —
   which makes it *look* protected. See `07_gaps_and_risks.md` §S-1.
5. **Zero tests for `core/` and `etsy/`** — 28 of 59 modules, including every
   module that writes to the database.

## Recommended build order for the UI phase

The UI cannot be built on this yet — not because the UI is hard, but because there
is no trustworthy Gold layer to serve. In dependency order:

| # | Step | Why first | Ref |
|---|---|---|---|
| 0 | Rotate the three secrets in `.env`; `git rm --cached .env` | They are in git history. Every hour they stay is exposure. | §S-1 |
| 0b | Adopt the Pinterest cookie pattern on the Etsy side — repoint the relay at the already-gitignored `etsy_datadome.txt` so a 4-minute-rotating token stops sharing a tracked file with two API keys | Fixes the *cause* of §S-1, not just the symptom. Touches session code, so it is the operator's change. | §S-1b |
| ~~1~~ | ~~Fix `private_blueprint.py:13`~~ | ✅ **done during this pass** | §B-1 |
| 2 | Decide the fate of the Private tier: restore `private/endpoints/` + `inputs/` + `src/services/executor`, or delete the dead modules | **Now the binding constraint.** Half the product spec depends on this tier; right now it is neither working nor removed. | §B-2 |
| 3 | Fix the temporal model **before** any real data accrues | Cannot be retrofitted (`MIGRATION_AND_OPERATIONS.md:36-44`). Three upserts in `core/database.py`. | §T-1 |
| 4 | Add provenance columns (`measured\|derived`, `collected_at`, `confidence`) | Copy the pattern from `series_store.py` — it is already solved in-repo. | §P-1 |
| ~~5~~ | ~~Write the profit model — the missing centre~~ | ✅ **done** — `etsy/analytics/profit.py`. Confirm the fee schedule and your hourly rate / weekly hours; every verdict depends on them. | §M-1 |
| 6 | Write the Pinterest→`trends` handoff (~30 lines) | The product's entire premise. The contract is specified; only the writer is missing. **Do this before step 5 — it is an hour.** | §U-1 |
| 7 | Then `api/` (read-only over Gold), then 3 UI pages | Per D-13: Discover, Cockpit, Settings. Not ten. | `DECISION_LOG.md:134-140` |

Steps 0–2 are hours. Steps 3–6 are the actual project. **Do not start the UI before
step 4** — a UI over untagged derived numbers ships the exact failure mode
`GOAL.md:67` names as the definition of failure.

---

*Continue to [02_design_approach.md](02_design_approach.md) — the central deliverable.*
