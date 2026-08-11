# 02 — Design Approach

*What approach this codebase actually uses, where it diverged from what was
intended, and the ordered path from here to a target that can carry a UI.*

**The one-sentence answer:** this is not one codebase with one approach — it is
**two codebases with opposite engineering cultures sharing a repository and a
`core/` folder**, joined by nothing, where the mature half (`pinterest/`) already
implements the architecture the documents describe and the immature half (`etsy/`)
is scripts-with-shared-utils wearing a package layout.

---

## 1. The patterns actually in play

Named concretely, with evidence. No labels without a file behind them.

| Pattern | Where | Evidence | Verdict |
|---|---|---|---|
| **Facade over transport** | `core/session_manager.py` | One class wraps every HTTP call, forces the TLS fingerprint, injects the cookie, retries. Every source module goes through it. | **Real and good.** The one clean seam in the repo. |
| **Repository** | `core/graph_db.py`, `pinterest/endpoints/series_store.py`, `pinterest/products/history.py` | Each owns its schema, exposes named methods (`add_node`, `put`, `neighbors`, `split`), never leaks SQL. | **Real and good** in `pinterest/`; see below for `core/database.py`. |
| **Anemic data-gateway** | `core/database.py` | Named methods, but they are 1:1 CRUD over three tables with no domain meaning: `upsert_keyword`, `get_keyword`. No invariants enforced, no guards, no provenance. | **Degenerate repository.** A table with a Python accent. |
| **Pipeline / staged transform** | `etsy/analytics/grid_analytics.py:52-228` | Explicit `PHASE 1..4` comments, each phase writing its state to disk before the next. | **Real, but** the phases are inside one 180-line method, not composable units. |
| **Pure function over plain data** | `etsy/api/public/api.py:95`, `pinterest/endpoints/local_math.py` (10 fns) | `parse_search_html` is documented "Pure function, no I/O". `local_math` is 155 LOC of I/O-free derivation. | **Real and good.** This is what `analysis/` should be made of. |
| **Composition script ("engine")** | `etsy/engines/master_*.py` (3 files) | Constructor wires 2-4 collaborators, one `run()` orchestrates, prints as it goes, dumps JSON at the end. | **Real, but** these are *pipelines*, not tools — they must not be counted as capabilities (see `05_module_map.md`). |
| **God-method** | `master_arbitrage.py:26-266` | One 240-line `run()` containing seven lettered sections A–G, each a different analysis, all inline. | **Anti-pattern.** Not one of A–G is independently callable or testable. |
| **Scripts-with-shared-utils** | all of `etsy/` | Every module ends in `if __name__ == "__main__"` with hardcoded demo arguments (`master_arbitrage.py:269` `"mom necklace"`; `reviews_api.py:218` a literal listing id). Four modules carry `sys.path.append` hacks. | **The dominant reality of the `etsy/` half.** |
| **Adapter / provider interface** | — | **Nothing.** No `contracts.py`, no `Protocol`, no base class, no normalized record. | **Missing.** This is D-05, unimplemented. |
| **Layered architecture** | — | Folder names (`api/`, `analytics/`, `engines/`) *suggest* layers. The import graph does not respect them. | **Aspirational.** Naming only. |

---

## 2. Dependency direction

79 internal import edges, extracted by AST (not by reading). The target rule is
`REPO_STRUCTURE_AND_CONFIG.md:76-91`: **dependencies point inward; the analysis
layer imports nothing.**

```
                    ┌─────────────────────────────────────────┐
                    │  core/settings.py   (leaf, 0 imports)   │
                    └────────────────┬────────────────────────┘
                                     │
                    ┌────────────────▼────────────────────────┐
                    │  core/session_manager.py                │
                    └────────────────┬────────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                                             │
    ┌─────────▼──────────┐                       ┌──────────▼─────────┐
    │ etsy/api/private   │                       │ etsy/api/public    │
    │ (+endpoints_mgr)   │                       │ api.py             │
    └─────────┬──────────┘                       └──────────┬─────────┘
              │                                             │
              │                          ┌──────────────────┼──────────────┐
              │                          │                  │              │
              │                ┌─────────▼──────┐  ┌────────▼───────┐  ┌───▼──────────┐
              │                │ listing_api.py │  │ reviews_api.py │  │core/shop_    │
              │                └─────────┬──────┘  └────────┬───────┘  │scraper.py    │
              │                          │                  │          └───┬──────────┘
              │                          └────────┬─────────┘              │
              │                                   │                        │
              │                    ┌──────────────▼────────────────────────▼──┐
              │                    │  etsy/analytics/*  (7 modules)           │
              │                    │  ⚠ ALSO imports core/database ──────────┐│
              │                    └──────────────┬───────────────────────── ││
              │                                   │                          ││
    ┌─────────▼───────────────────────────────────▼──────────┐               ││
    │  etsy/engines/*  (8 modules)                           │◄──────────────┘│
    │  ⚠ ALSO imports core/database ─────────────────────────┼────────────────┘
    └────────────────────────────────────────────────────────┘
                                                    ▼
                                          ┌──────────────────┐
                                          │ core/database.py │  ← STORAGE
                                          └──────────────────┘
```

### The violations

| # | Violation | Evidence | Why it matters |
|---|---|---|---|
| **D-1** | **Analysis depends on storage.** Every analytics and engine module imports `core.database`. | `grid_analytics.py:14`, `sentiment_analytics.py:11`, `single_listing_analytics.py:12`, `master_arbitrage.py:11`, `master_listing_analyzer.py:11`, `private_blueprint.py:6` — 6 of 6 | The rule says `analysis/` imports **nothing**. Every calculation in this repo is welded to SQLite. None can be unit-tested without a database file on disk. |
| **D-2** | **Storage read inside a constructor.** | `grid_analytics.py:34` calls `self.db.get_keyword()` in `__init__` | Constructing the object performs I/O. You cannot instantiate the pipeline to inspect it. |
| **D-3** | **Analysis depends on transport.** | `ratio_estimator.py:7`, `daily_tracker.py`, `shop_analytics.py` all construct `EtsyPublicAPI()` themselves rather than receiving it | Dependencies are created, not injected — except `ShopScraper.__init__` (`shop_scraper.py:23`), which does it right and is the counter-example proving it was possible. |
| **D-4** | **Package structure is nominal.** `etsy/` contains **no `__init__.py` at any level**. | Verified: only `pinterest/__init__.py`, `pinterest/endpoints/__init__.py`, `pinterest/products/__init__.py` exist | Imports only resolve because four modules mutate `sys.path` at runtime: `master_arbitrage.py:7`, `grid_analytics.py:8`, `ratio_estimator.py:5`, `reviews_api.py:6`, `private_scoring_pipeline.py:7`. Remove the hack and the half stops importing. |
| **D-5** | **Cross-half coupling is zero — and that part is correct.** | 0 of 79 edges connect `pinterest/*` to `etsy/*` | ✅ **Not a defect.** `_old_etsy_master_architecture.md:112-119` and `_old_project_structure.md:40-42` describe two *separate agents* communicating through the `trends` table, never through imports. The separation is intentional and right. **The defect is that the handoff itself was never written** — see `07_gaps_and_risks.md` §U-1. |

### What the graph gets right

`pinterest/` is clean: `endpoints/` (transport + math) ← `products/` (10 modules) and
`pipelines/` (4 modules). `local_math.py` is imported by four consumers and imports
**nothing** internally — a genuine pure-analysis leaf. That is exactly the target
shape, already achieved, in the same repo.

---

## 3. Boundaries: which exist, which are missing

| Boundary | Should exist per | Status |
|---|---|---|
| Transport ↔ everything | D-05 | **exists** — `SessionManager`, and it is respected |
| Provider schema ↔ business logic | D-05 | **missing** — consumers index raw JSON directly |
| Raw ↔ guarded (Bronze→Silver) | D-06 (`DECISION_LOG.md:65-73`) | **missing** — no `guards.py`, no single guard boundary. Guards that do exist are scattered: `series_store.py:142` (refuse degraded), `private_scoring_pipeline.py:110-116` (CVR and supply gates), `api.py:165` (reject empty parse). Three different places, three different styles, no shared vocabulary. |
| Compute ↔ I/O | import rule | **missing in `etsy/`, present in `pinterest/`** (`local_math.py`) |
| Ingestion ↔ serving | D-08 | **not applicable** — no serving process exists |
| Storage ↔ storage | — | **missing** — four independent stores with no reconciliation (see `04_data_model.md`) |

---

## 4. Intent versus implementation

The documents are unusually explicit about intent, which makes the divergence
measurable rather than a matter of opinion.

| Intended | Documented at | Implemented | Divergence |
|---|---|---|---|
| `src/` with 6 layers, inward imports | `REPO_STRUCTURE_AND_CONFIG.md:13-91` | `core/` + `etsy/` + `pinterest/` | **Total.** No file is where the target says. `src/` does not exist — yet `private_scoring_pipeline.py:10` imports from it, so someone was mid-migration. |
| Percentile-normalized weighted score | D-02 (`DECISION_LOG.md:20-31`) | Three different raw-ratio formulas | **Total** — see §5 |
| Profit at the centre | D-01, `GOAL.md:104-120` | No cost input in 59 modules | **Total.** Zero implementation. |
| One guard boundary | D-06 | Three scattered guard sites | Partial |
| Append-only time | D-04 | 3 upserts + 3 `INSERT OR REPLACE` | **Total** in `core/`, partial in `pinterest/` |
| Adapter per provider | D-05 | None | **Total** |
| Config in YAML | `REPO_STRUCTURE_AND_CONFIG.md:106-157` | Frozen dataclass + `.env` (`core/settings.py`) with hardcoded absolute Windows paths at `:32,34` | **Total.** No `config/` directory exists. |
| Ingestion/serving split | D-08 | No serving side | Not started |

### The scoring divergence (resolves open decision **O-1**)

`START_HERE.md:79` and `DECISION_LOG.md:148` frame this as *"`scoring.py` or
`scoring_engine.py` — which survives?"* **Neither file exists in this repo.** The
real situation is worse than a duplicate:

| Implementation | Formula | Gates | Normalization | Profit |
|---|---|---|---|---|
| `master_niche_finder.py:66` | `(volume / listings) * 1000` | none | none | none |
| `private_scoring_pipeline.py:117` | `volume / supply` | `cvr >= 2`, `supply > 0` (`:110-116`) | none | none |
| `master_arbitrage.py:85,127-129,176-179` | `count / total * 100` per dimension, 7× | hardcoded thresholds `<500` / `<5000` (`:99-104`) | none | none |

Three formulas, three magnitudes, no shared module, no percentile step, and — the
finding that matters — **no cost term in any of them.** D-01 exists precisely
because ranking by demand-over-supply is the flaw that made the original
architecture untrustworthy. All three implementations reproduce that flaw.

**O-1 resolution:** there is nothing to delete. There is something to *write*: one
`analysis/scoring.py` implementing D-02, consuming an `analysis/profit.py` that does
not yet exist.

---

## 5. Why the two halves differ — and what it tells you

This is the most useful observation in this document, because it means the target
architecture is not hypothetical: **it already exists in this repo, on one side.**

| | `pinterest/` (26 modules) | `etsy/` (20 modules) + `core/database.py` |
|---|---|---|
| Provenance | `precision: exact\|approx`, source ranking, refusal threshold — `series_store.py:32,36,134` | none — `core/database.py` has no provenance column |
| Tests | 7 test modules, incl. offline derivation tests | **zero** |
| Pure-compute layer | `local_math.py` — 10 fns, no internal imports | none |
| Caching | keyed by `(term, country, end_date)`, never downgrades a better source (`series_store.py:76-96`) | `os.path.exists(cache_file)` → return forever, no TTL, no timestamp (`etsy/api/public/api.py:45-48`, `private/api.py:45-48`) |
| Error handling | explicit refusal, returns `None` meaning "go fetch" | `except Exception: pass` — `grid_analytics.py:226`, `listing_api.py:91`, `shop_scraper.py:95`, `private_blueprint.py:102` |
| Packaging | real `__init__.py`, a CLI (`products/cli.py`) | `sys.path.append` in 5 files, no `__init__.py` |
| Credential storage | *(was)* rotating cookie in its own gitignored file, never tracked — **removed 2026-08-11**, Pinterest now also writes to `.env` | rotating cookie written into `.env` **alongside long-lived API keys, in a tracked file**. The two halves converged on the unsafe pattern rather than the safe one — see `07_gaps_and_risks.md` §S-1b |
| Comments | explain the measurement behind the choice (`series_store.py:1-23`) | explain what the line does |

The `pinterest/` half was built by someone applying the three invariants. The
`etsy/` half was built to get numbers on screen fast. **Neither is wrong for its
moment** — but only one of them can carry a UI, and the operator's two most
valuable sources are on the other side.

---

## 6. Target approach

Not a rewrite. The target is **the `pinterest/` approach, applied to `etsy/`,
with the missing analysis layer written once and shared.**

```
  ┌───────────────────────────────────────────────────────────────┐
  │  analysis/          PURE. imports nothing. no I/O.            │
  │  profit.py · scoring.py · gaps.py · platform.py               │
  │  ← local_math.py moves here nearly unchanged                  │
  └──────────────────────────▲────────────────────────────────────┘
                             │ (store and pipelines import analysis)
  ┌──────────────────────────┴────────────────────────────────────┐
  │  store/             repositories. own the schema.             │
  │  ← graph_db.py, series_store.py, history.py already fit       │
  │  ← database.py must be rebuilt append-only                    │
  └──────────────────────────▲────────────────────────────────────┘
  ┌──────────────────────────┴────────────────────────────────────┐
  │  ingest/guards.py   THE single guard boundary                 │
  │  clamp · noisy · collected_at · strip PII · tag provenance    │
  └──────────────────────────▲────────────────────────────────────┘
  ┌──────────────────────────┴────────────────────────────────────┐
  │  sources/           adapters → ONE normalized record shape    │
  │  contracts.py · pinterest/ · etsy_demand/ · etsy_supply/      │
  │  ← wraps SessionManager. Access layer unchanged, behind here. │
  └───────────────────────────────────────────────────────────────┘
```

The access layer (`SessionManager`, `settings`, cookie relay, extension) sits
**below** `sources/` and is not touched by this refactor — it is wrapped, not
rewritten. That is the boundary `PROJECT_BRIEF.md:42-65` requires.

---

## 7. Refactor path

Ordered by *what unblocks the most with the least risk*. Each step is
independently shippable and leaves the repo runnable — the strangle pattern from
`MIGRATION_AND_OPERATIONS.md:12-17`.

| # | Step | Effort | Unblocks | Risk |
|---|---|---|---|---|
| **1** | Delete one stray `"""` at `private_blueprint.py:13` | seconds | the only `keywords` writer | none |
| **2** | Add `__init__.py` to `etsy/` and its 5 subpackages; delete the 5 `sys.path.append` lines | ~20 min | real imports, so tests become possible at all | low — run each `__main__` after |
| **3** | Extract `analysis/` as pure functions: move `local_math.py` as-is; lift the three scoring formulas out of the engines into one module | ~half day | first testable unit in the `etsy/` half | low — no I/O to break |
| **4** | **Write `analysis/profit.py`.** Fees, COGS, shipping, labor, per-type margin floors — all from config | ~1 day | D-01. The product's actual centre. | none — new code |
| **5** | Rebuild `core/database.py` append-only: `collected_at` in the PK, `*_latest` views for current-state reads, `measured\|derived` + `confidence` columns | ~1 day | invariants 1 and 2. **Do before data accrues.** | medium — write the guard test first (`MIGRATION_AND_OPERATIONS.md:43`) |
| **6** | Consolidate guards into `ingest/guards.py`; route every write through it | ~1 day | D-06; one place to audit | medium |
| **7** | Define `sources/contracts.py` and wrap the three existing clients to emit it. **Wrap, don't rewrite.** | ~2 days | D-05; makes the Pinterest→Etsy join expressible | medium |
| **8** | Write the join: Pinterest momentum → Etsy candidates, through the contract | ~1 day | **the product premise** | low, once 7 lands |
| **9** | Replace `print()` with structured logging carrying guard counts | ~half day | the five health questions (`MIGRATION_AND_OPERATIONS.md:118-128`) | low |
| **10** | `api/` read-only over Gold, then 3 UI pages | — | the next phase | — |

**Steps 1–2 are the whole unlock.** Until `etsy/` is an importable package, nothing
in it can be tested, and every later step is guesswork.

Steps 4, 5 and 8 are the three that change what the system *is* rather than how it
is arranged. If time is short, do 1, 2, 5, 4 — in that order — and stop. That yields
an honest, append-only, profit-aware core, which is the minimum a UI can sit on
without shipping the failure mode `GOAL.md:67` defines.

---

*Continue to [03_data_flow.md](03_data_flow.md).*
