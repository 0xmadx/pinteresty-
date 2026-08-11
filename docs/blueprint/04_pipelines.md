# 04 — Pipelines

Five pipelines, each a stage in the loop. Each reads from a defined layer and
writes to the next — never skipping, never writing upward. All are batch jobs run
by `run.py` (or a DAG later); none run inside a user request.

```
DISCOVER → VALIDATE → SCORE → SERVE → LEARN
  (free)    (metered)  (local)  (read)  (loop)
```

---

## Pipeline 1 — DISCOVER (free, wide)

**Goal:** produce a ranked shortlist of candidate terms, spending zero metered
quota. This is where breadth comes from.

```
seed          → trends adapter: top_trends per preset × interest (limit=100)
expand        → related + prefix, depth 3 (series ride along free — L4)
harvest       → every response's attached series into the series store
graph         → write typed weighted edges to the graph; BFS frontier
rank          → local scoring on momentum × seasonality × intent (no Etsy yet)
              → filter: drop noisy, apply seasonality floor for seasonal terms
OUTPUT        → Silver trends (append-only, guards applied) + a ranked shortlist
```

Key disciplines: batch metrics 50 terms/call; dedup at enqueue; cap concurrency
~5; harvest-before-refetch (L4). Nothing here costs metered quota — Pinterest is
free, so crawl deep.

---

## Pipeline 2 — VALIDATE (metered, narrow)

**Goal:** spend the scarce Etsy quota only on the top of the shortlist.

```
budget        → token bucket: N units today
prioritize    → priority queue ordered by Pipeline 1's rank
for each top-N (until budget exhausted):
   demand     → demand adapter: search_volume, cvr, price_paid → Silver keywords
   supply     → supply adapter: SERP count, competitor strength → Silver listings
   filters    → SERP filter-stack profile ONLY for survivors (C.1) — hundreds of
                 queries, so gated behind scoring, never run on the corpus
degrade       → if a signal is None (official API), flag and continue
OUTPUT        → Silver keywords + listings, validated subset only
```

This is the pipeline that respects the metered constraint. Everything upstream
exists to make this pipeline spend well.

---

## Pipeline 3 — SCORE (local, no network)

**Goal:** assemble candidates and rank them. Pure computation from Silver.

```
assemble      → join trends × keywords × listings × margin(profit_calc)
              → carry noisy, cvr_source; compute freshness_floor
              → skip terms missing Etsy validation (don't guess)
gate          → SOURCE VALIDATION (bias B-05) — before any blend:
                • grade pinterest_signal + pinterest_confidence
                • grade etsy_demand_signal + etsy_confidence
                • set sources_agree; write verdict_reason
                • one strong + one weak/absent → combined_score flagged low-trust
score         → percentile-normalize the pool (pandas .rank(pct=True))
              → weighted sum per product-type profile
              → confidence gate: noisy→neutralize momentum; default→flag
              → store pool_id + pool_size with every score
gap           → 7-dimension filter search, dimension set selected by type,
                 empty-bracket trap check (demand must hold inside the bracket)
where         → platform recommendation (Etsy/Shopify/Pinterest) + CAC range
plan          → launch plan: timing (type-aware lead time), SEO, flaws
OUTPUT        → Gold candidates, scores, launch_plans (all rebuildable)
```

Runs on every input change — Gold is disposable, so re-scoring under new weights
is just re-running this.

---

## Pipeline 4 — SERVE (read-only)

Not a batch job — the always-up read API. Reads Gold, returns JSON, triggers
nothing. Detailed in `06_ui_structure.md`. Its only rule: **never fetch, never
write.** A user click cannot cause a 500ms Etsy call that might fail.

---

## Pipeline 5 — LEARN (the loop)

**Goal:** find out if the machine was right, and tune it.

```
on launch     → snapshot the FULL feature vector into launches (frozen, literal)
observe       → rank_observations 3×/week (rolling median; organic + absolute)
               → own-CVR vs niche-CVR; traffic-source attribution
mature (90d)  → fill actual sales/profit/rank; classify outcome + failure_mode
calibrate     → estimate_error_ratio = actual ÷ predicted (median = your bias)
               → per-variable correlation with outcome
               → timing validation (was 6 weeks right?)
tune          → adjust weights → weights_version++ → feeds Pipeline 3
               → but NOT under ~10 launches (don't fit 6 weights to 5 outcomes)
OUTPUT        → tuned weights, calibration report
```

This is the pipeline that makes the system compound instead of just recommend.

---

## Scheduling

| Pipeline | Cadence | Trigger |
|---|---|---|
| DISCOVER | weekly | Pinterest's weekly buckets |
| VALIDATE | weekly / on-demand | budget-gated |
| SCORE | after any input change | Gold is cheap to rebuild |
| SERVE | always up | — |
| rank observations | 3×/week | rolling median |
| LEARN calibrate | after outcomes mature | ≥10 launches |
| alerts diff | weekly | needs 2 archived weeks |

---

## Failure & recovery

- **Idempotent everywhere.** Re-running any pipeline is safe and (thanks to
  caching + Bronze) cheap. A crashed run is re-run, not repaired.
- **Circuit breaker per source.** A down provider degrades that signal to "stale,
  flagged"; the rest of the pipeline runs on what it has.
- **Partial materialization.** Because layers are explicit, only the stale parts
  rebuild — a Silver fix doesn't re-fetch Bronze; a weight change only re-runs
  SCORE.
- **The Bronze safety net.** Any analysis bug is fixed by replaying Bronze, zero
  quota spent.

---

## The orchestrator question

Start with a single `run.py`: explicit stage ordering, a small `run_state` table
recording what ran when and with what result. Only adopt **Dagster** (asset-based,
models data dependencies and freshness) when running stages by hand actually
hurts. Never adopt Airflow-style task scheduling — your world is *assets* with
dependencies, not *tasks* on a clock.
