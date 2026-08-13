# MIGRATION PLAN & OPERATIONS

*The blueprint describes a target. The code is somewhere else. This is the route
between them — and how to run the thing once it's there.*

---

# Part 1 — Migration

## The principle: strangle, don't rewrite

Never stop the working system to rebuild it. Add the new structure alongside, move
one piece at a time, keep it runnable at every step. Each phase below is
independently shippable and independently valuable.

**Order is driven by one question: what loses data or gets harder if delayed?**

---

## Phase 0 — Ten-minute hygiene (do today)

| Task | Why now |
|---|---|
| Strip `client_context` PII from committed dumps; gitignore `data/` | It's account name, email, billing status sitting in the repo |
| Resolve `scoring.py` vs `scoring_engine.py` — keep one | Two files claiming to be the same thing will confuse every future step |
| Add a blocking comment to `trends_store.py` about the upsert bug | So nobody builds on it before Phase 2 |

## Phase 1 — Understand what exists (the Claude Code pass)

Run `claude_code/PROJECT_BRIEF.md`. Output: seven architecture docs, the real
de-duplicated tool count, and every contradiction logged with file and line.

**Nothing else should start before this.** Every later phase depends on knowing
what's actually there versus what the docs claim.

## Phase 2 — Fix the temporal model ⚠️ BEFORE ACCUMULATING DATA

The one thing that **cannot be retrofitted**. Every day you run without it is a
day of history you can't reconstruct.

1. Make `trends` (and every time-varying table) append-only with `collected_at`.
2. Add a `*_latest` view for current-state reads.
3. Write the guard test first: ingest twice, assert two rows, assert the original
   is intact. Watch it fail, then fix.

## Phase 3 — Start the two tables that lose data forever

`rank_observations` and `launches`. **Start recording now, even by hand.**
Everything else can be computed retroactively; a prediction cannot be backfilled
after you know the outcome.

Minimum viable: a CSV you append to. The schema matters more than the tooling.

## Phase 4 — Extract the layers (the strangle)

Move code into `src/` per `REPO_STRUCTURE_AND_CONFIG.md`, one layer at a time,
lowest-dependency first:

1. `analysis/` — pure functions, no I/O. Easiest, most testable, zero risk.
   (`profit_calculator.py` → `analysis/profit.py`, scoring → `analysis/scoring.py`.)
2. `store/` — schema + accessors.
3. `ingest/guards.py` — consolidate every guard into **one** boundary module.
4. `sources/contracts.py` — define the normalized records.
5. `sources/*` — wrap existing fetch code to emit normalized records. **Wrap, don't
   rewrite.**
6. `pipelines/` — thin orchestration over the above.

After each step: run the tests, run the pipeline, confirm nothing broke.

## Phase 5 — Bronze

Persist raw responses before parsing. Cheapest change with the highest option
value: from here on, every analysis bug is fixed by replay, never by re-fetching.

## Phase 6 — Config & budget

Externalize fees, weights, TTLs, and operator values to YAML. Add the token-bucket
budget allocator for the metered tier.

## Phase 7 — Tests to the coverage targets

Guards to 100%, analysis to ~95%, per `TESTING_STRATEGY.md`.

## Phase 8 — API, then UI

`api/` read layer over Gold, then the three core UI pages (Discover, Cockpit,
Settings). Not ten pages. Three.

---

## Migration risk table

| Risk | Mitigation |
|---|---|
| Breaking a working pipeline mid-move | Strangle pattern: old path runs until the new one passes the same tests |
| Losing history during the temporal fix | Export existing rows first; the fix is additive (new table + view) |
| Guards silently not migrating | Guard tests written *before* the move, run after |
| Scope creep into rewriting | Each phase is shippable; stop and use the system between phases |

---

# Part 2 — Operations

## Weekly rhythm

| When | What | Check |
|---|---|---|
| Weekly | DISCOVER sweep | new terms found; frontier growing |
| Weekly | Archive backfill | one row per week per preset, no gaps |
| Weekly | Alerts diff | needs ≥2 archived weeks |
| 3×/week | Rank observations | both organic *and* absolute recorded |
| On demand | VALIDATE (metered) | budget consumed < allowance |
| After input change | SCORE | pool size, confidence distribution |
| After outcomes mature | LEARN calibrate | ≥10 launches before tuning |

## What to check after every run — the health questions

A weekly batch system fails **silently**. These five questions catch it:

1. **Did every stage complete?** → `run_state` table: stage, started, finished,
   rows written, errors.
2. **How fresh is the freshest data?** → max `collected_at` per table. If it didn't
   move, the run did nothing.
3. **How many rows were guard-flagged?** → counts of `capped`, `noisy`,
   `cvr_source=default`. A sudden jump means a source changed shape.
4. **What did the budget cost?** → metered calls used vs allowance, and cache hit
   rate (the number that becomes your margin if this ever goes SaaS).
5. **Did any circuit breaker trip?** → which source degraded, for how long.

## Logging

Structured (JSON) lines, one per stage, carrying: stage, duration, rows in/out,
cache hits/misses, metered calls spent, guard-flag counts, errors. Enough to answer
all five questions above without opening the database.

**Log the guard counts specifically.** They're your early warning that a provider
changed something — a spike in `capped` or `noisy` means the data shape moved
before anything visibly breaks.

## Failure handling

| Failure | Behavior |
|---|---|
| One source down | Circuit-break it; other stages run on what exists; mark data stale |
| Budget exhausted | Serve stale **flagged**, never silently; queue for tomorrow |
| Stage crashes | Re-run it — everything is idempotent and cached, so re-runs are cheap |
| Bad derivation found | Fix the transform, replay Bronze. **Zero API calls.** |
| Schema drift at a source | Contract tests fail by name, telling you which claim broke |

## The recovery guarantee

Because Bronze is immutable and every pipeline is idempotent:

> Any state after Bronze can be rebuilt from Bronze with no network calls.

That single property means a corrupted Silver, a bad weight change, or a wrong
clamping rule is a *rebuild*, not a data loss. It's the reason Bronze is Phase 5
and not an afterthought.

---

## Definition of "the system is healthy"

- Last run completed all stages with zero errors.
- Freshness moved on every table it should have.
- Guard-flag rates are stable week over week.
- Budget consumed < allowance, cache hit rate steady.
- Contract tests pass (no source drifted).
- `launches` has entries for every real launch, with frozen inputs.

If all six hold, the numbers coming out can be trusted as much as this system ever
promises — which is: honestly labeled, with their confidence and freshness attached.
