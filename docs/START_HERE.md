# START HERE — the complete project index

⚠️ **Setting this project up for the first time?** This is an index of the
*architecture* documentation, not a setup guide — go to
[`docs/QUICKSTART.md`](QUICKSTART.md) instead.

Everything produced for the Niche Decision Machine, in reading order, with what
each file answers and who it's for.

**If you are Claude Code:** read this file, then `GOAL.md`, then
`claude_code/PROJECT_BRIEF.md`. That's your task.

> ⚠️ **Read `architecture/` before trusting the rest of this index.** Much of what
> follows describes the design as *intended*; `docs/architecture/` records it as
> *built*, and they diverge. Three files settle most questions:
>
> | File | Settles |
> |---|---|
> | **`architecture/09_build_plan.md`** | **what we are building, in what order, and why** — start here |
> | `architecture/08_capability_map.md` | every endpoint, parameter and link across all three sources — used vs never called |
> | `architecture/bias_audit.md` | the **verified** bias picture (`BIASES_AND_BLIND_SPOTS.md` is self-declared unverified; 2 of its 10 claims were wrong) |
> | `architecture/07_gaps_and_risks.md` | the defect list, with what is fixed and what remains |
>
> **Two premises repeated throughout the docs below are now superseded:**
>
> - **D-14** — the Etsy Private quota was never observed, and the operator tested it
>   directly. The architecture is no longer "ration the metered call"; it is "crawl wide
>   everywhere and join the three sources". Any doc that budgets calls is stale.
> - **D-24** — every table held 0 rows because Etsy returns **snake_case** and every
>   consumer read **camelCase**, not because of the quota, a broken import, or missing
>   scheduling. All three of those were argued at length and all three were wrong.
>   `07_gaps_and_risks.md` §ROOT CAUSE has the detail.
>
> **The goal has been sharpened** (D-20…D-23): a **calendar-first** product — what to
> list, when, and whether it pays — with keyword search as the second door. Etsy-only
> for now, all three product types, and **Settings ships before anything else**.

**If you are the operator:** read `GOAL.md`, then `MASTER_DOCUMENT.md`, then
whatever section you're working on.

---

## The one-paragraph version

A single operator runs their own Etsy shops (digital, physical, personalized). This
system takes a keyword or a competitor's listing URL, pulls signals from three
sources (Pinterest for momentum, Etsy Private for true demand, Etsy Public for
supply/competition), scores the opportunity with **profit — not revenue — at the
center**, finds the competition gap, decides **whether to make it and where to sell
it**, then tracks what actually happened and tunes itself. Four modes: FIND, JUDGE,
OPERATE, LEARN. It's a loop, not a pipeline.

---

## Tier 1 — Goal & product (read first)

| File | Answers | Status |
|---|---|---|
| `GOAL.md` | What the operator wants, why, and what success looks like | **the north star** |
| `MASTER_DOCUMENT.md` | What the machine does — the reconciled source of truth for product logic | current |
| `PRODUCT_SPEC.md` | The original detailed spec (appendix to MASTER) | appendix |

## Tier 2 — Capability surface (what can be built)

| File | Answers | Status |
|---|---|---|
| `CAPABILITY_MAP.md` | 14 categories of tools (A–N): discovery, demand, supply, SEO, timing, market… | doc-derived |
| `CAPABILITY_MAP_ADDENDUM.md` | The missing modes (O–U): OPERATE, LEARN, pricing, ads, exit timing | doc-derived |
| `CAPABILITY_COUNT_DEDUP.md` | **Why "45 tools" is inflated** and how to get the real count | ⚠️ read before trusting counts |

## Tier 3 — Decision designs (the product logic in depth)

| File | Answers |
|---|---|
| `WHERE_TO_LIST_DESIGN.md` | Etsy vs Shopify vs Pinterest shop — the three-way platform decision |
| `OPERATE_AND_LEARN_DESIGN.md` | Rank tracking, the feedback loop, and how the machine learns |

## Tier 4 — Engineering blueprint (how to build it)

| File | Answers |
|---|---|
| `blueprint/00_README.md` | Index + the three invariants that govern everything |
| `blueprint/01_architecture.md` | The layered system, Bronze/Silver/Gold, two processes |
| `blueprint/02_data_model.md` | Every table, guard columns, the temporal model |
| `blueprint/03_source_adapters.md` | The provider interface — how sources become swappable |
| `blueprint/04_pipelines.md` | DISCOVER → VALIDATE → SCORE → SERVE → LEARN |
| `blueprint/05_stack.md` | Every tech choice with its reason and its anti-choice |
| `blueprint/06_ui_structure.md` | The 10 pages, component tree, API contract |
| `blueprint/07_saas_evolution.md` | What changes at multi-tenant scale |
| `SYSTEMS_ARCHITECTURE.md` | The scale reasoning behind the choices; what NOT to build |
| `CACHING_AND_OPTIMIZATION.md` | The five caching layers and the freshness discipline |

## Tier 5 — Engineering practice (how to build it correctly)

| File | Answers | Status |
|---|---|---|
| `TESTING_STRATEGY.md` | How anything gets verified. **The primary defense** — this system fails by returning plausible wrong numbers, not errors | ⚠️ nothing is tested yet |
| `REPO_STRUCTURE_AND_CONFIG.md` | Where files go, the import rule, config schema, secrets, the PII issue | — |
| `MIGRATION_AND_OPERATIONS.md` | Current code → target architecture (strangle, don't rewrite); weekly runbook, health checks, failure handling | — |

## Tier 6 — Working code (runs today)

| File | What it does | Status |
|---|---|---|
| `profit_calculator.py` | 3 product types, Etsy fees, capacity limits, confidence flags | ✅ runs, demoed |
| `scoring_engine.py` | Percentile-normalized weighted scoring + noisy guard | ✅ runs, demoed |
| `trends_store.py` | The join: Pinterest → trends table (guards) → candidates | ✅ runs, ⚠️ has the temporal bug |
| `scoring.py` | ⚠️ **DUPLICATE** — overlaps `scoring_engine.py` | ⚠️ resolve before building |

## Tier 7 — Claude Code handoff

| File | Purpose |
|---|---|
| `claude_code/PROJECT_BRIEF.md` | The architecture-pass task: goal, scope, 7 deliverables |
| `claude_code/.claude/skills/system-architect/SKILL.md` | The reusable skill enforcing the rules |
| `claude_code/README.md` | How to wire it into the repo |

---

## ⚠️ Known issues (fix or flag before building)

1. **`scoring.py` vs `scoring_engine.py`** — two files, both claim to be the
   corrected score. Only `scoring_engine.py` was built and demoed end-to-end.
   Pick one, delete the other.
2. **`trends_store.py` upserts** — `ON CONFLICT DO UPDATE` overwrites history;
   the architecture requires append-only. Code and docs disagree right now.
3. **Tool counts are doc-derived, not verified.** ~45 → likely ~28–32 real.
   See `CAPABILITY_COUNT_DEDUP.md`.
4. **Three source-doc contradictions unresolved** — the review star filter (1–3 vs
   1–4), `private_blueprint` described two ways, the reviews endpoint named three
   ways. Only the code settles these.
5. **Nothing is verified against real data.** Every module runs on invented
   numbers. First real task: validate against actual source output.

---

## The three invariants (govern every document here)

1. **Measured vs derived is tagged on every value.** The failure mode is a
   plausible wrong number, not an error.
2. **Time is first-class.** Nothing time-varying is overwritten; predictions
   snapshot their inputs. This makes LEARN honest and a future model possible.
3. **The source is an implementation detail.** One normalized shape behind an
   adapter, so swapping providers is config, not a rewrite.

## Recommended build order

1. Resolve the known issues above (1 & 2 are ten-minute fixes).
2. Run the Claude Code architecture pass (`claude_code/PROJECT_BRIEF.md`).
3. Fix the temporal model **before accumulating data** — it can't be retrofitted.
4. Start `rank_observations` and `launches` tables — the only data that's lost
   forever if you delay.
5. Wire real source data into `trends_store.py` → `scoring_engine.py`.
6. Then the UI (`blueprint/06_ui_structure.md`), starting with 3 pages, not 10.
