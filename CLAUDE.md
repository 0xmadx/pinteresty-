# CLAUDE.md — working notes for this repo

Operational knowledge that is expensive to rediscover. Architecture lives in
`docs/architecture/`; this file is *how to work here without repeating mistakes we
have already made.*

---

## What this is

A decision system for one operator selling on Etsy (digital, physical **and**
personalized). It joins three sources — Pinterest (momentum, timing, demographics),
Etsy Private (real volume, CVR, prices, competitors) and Etsy Public (supply,
reviews, saturation) — and answers: **what to list, when, and whether it pays.**

**The goal (D-20):** a **calendar-first** product — 🔴 list now / 🟡 list by Sept 22 /
⚪ watching — with keyword search as a second door. Not a niche checker; every
competitor is a niche checker.

**The defining failure mode:** *a plausible wrong number, not a crash.* Almost every
guard in this codebase exists to stop one specific wrong number reaching the operator.

---

## Running things

```bash
# ALWAYS use the venv — the system Python lacks bs4, curl_cffi, dotenv
.venv/Scripts/python.exe -m etsy.engines.master_niche_finder

# Everything is a module. Run from the repo root, never `python path/to/file.py`
# (etsy/ is a real package now; the sys.path hacks were deleted)
```

**Live data works.** Sessions come from `.env`, refreshed by the Chrome extension via
`core/cookie_server.py`.

- **The cookie server must be running**, and an Etsy Shop Manager tab open, or the
  private API returns **401**. That is auth, not rate limiting.
- After the operator restarts it, reload with `load_dotenv(override=True)` before
  constructing a client — stale env values persist otherwise.
- **You may fetch live data while building.** Probing the real API is usually faster
  and more truthful than reasoning about it (see D-24 below).

```bash
# Full verification — run before every commit
.venv/Scripts/python.exe -m core.test_graph_db          # + the other 19 suites
# 20 offline suites, ~441 assertions, no network required
```

---

## Non-negotiable rules

### 1. Never index a raw private-API key — use the parser

Etsy returns **snake_case**; this repo historically read **camelCase**, so seven
modules fetched correct data and read `None` out of it. That is why every table held
0 rows for the whole project's life.

```python
from etsy.api.private.api import parse_results_data, parse_term_summaries, edge_term
data = parse_results_data(api.get_results_data(kw))   # ✅
vol  = data["stats"]["searchVolume"]                  # ❌ silently None forever
```

`edge_term(e)` for keyword edges — the enqueue response keys them `query`, the old
consumers read `searchTerm`.

### 2. Absent is not zero (N-02)

A badge that did not render means *unmeasured*, not *zero demand*. A review count that
did not parse means *unknown*, not *no reviews*. Use `None`, and let the caller decide
at the point of use. Columns are nullable for this reason.

### 3. Estimates carry a basis; bounds are labelled as bounds

Every derived number ships with provenance (`measured` / `derived` / `default`). The
"N bought today" badge is an **upper bound** — it only renders above a threshold, so
×30 projects the best day across a month. It is clamped against the shop's measured
daily rate where one exists.

### 4. Refuse rather than guess

- `score_pool` raises `PoolTooSmall` instead of scoring 2 candidates
- `can_discriminate()` refuses to rank when the dimensions cannot separate the pool
- `survivor_bound` reports a **bound**, never a rate, and calls a 100% share
  `uninformative` rather than "healthy"
- a failed fetch is never cached; a failed scrape is never stored as `0`

### 5. Time is append-only

`*_observations` tables have `collected_at` in the primary key. Never overwrite a
time-varying value. The cache (`core/request_cache.py`) is the opposite — it exists to
*forget*, with per-type TTLs. Different files on purpose (D-18).

### 6. Do not touch the access layer

`core/session_manager.py`, `core/cookie_server.py`, `chrome_extension/` — read them,
document them, never extend them. **No Playwright or headless browsers, ever.**
`requests` / `curl_cffi` are fine.

---

## Hard-won facts

| Fact | Detail |
|---|---|
| **No quota** | `results-data` reports `quota_data {total:15, remaining:15}` but three consecutive distinct calls left it at 15/15 — this endpoint does not consume it (D-14). `deep_dive_limit` defaults to unlimited. |
| **401 ≠ 429** | 401 = stale session (restart cookie server). 429 = real throttle; `SessionManager.rate_limited` counts them. Nothing has ever recorded a 429. |
| **`.env` is untracked** | `git rm --cached` was applied. `registry.json` was also untracked — it held 32 live session cookies. |
| **20 competitors per call** | `results-data` returns them free. Do not scrape the public SERP to rebuild what you already have. |
| **Etsy has its own momentum** | `wow_data.value` — week-over-week %, free, in the same response. |
| **Unused, verified to exist** | `similar_search_terms`, `market_gap_recommendations`, `predicted_days` (Pinterest 91-day forecast), `page` (pagination), `include_trendline`. See `08_capability_map.md`. |

---

## Doc map

| File | Answers |
|---|---|
| `docs/architecture/09_build_plan.md` | **what we are building and in what order** — start here |
| `docs/architecture/08_capability_map.md` | every endpoint + parameter, used vs never called |
| `docs/architecture/07_gaps_and_risks.md` | the defect list; §ROOT CAUSE explains the empty tables |
| `docs/architecture/bias_audit.md` | the **verified** bias picture |
| `docs/DECISION_LOG.md` | why anything is the way it is (D-01…D-26) |
| `docs/GOAL.md` | the north star |
| `BIASES_AND_BLIND_SPOTS.md` | ⚠️ self-declared **unverified**; 2 of its 10 claims were wrong. Prefer `bias_audit.md`. |

Skills in `.claude/skills/`: `system-architect`, `bias-aware-analysis`, `ui-builder`,
`git-and-comments`. They are enforced, not advisory.

---

## Current state

**Working:** all three API clients · profit gate · survivor bound · gap analysis ·
scoring with discrimination check · freshness floor · tag mining · term join ·
request cache · run log · guards. 20 test suites, ~441 assertions, all offline.

**Empty:** every observation table except a first `keyword_observations` row. The
machine is built and has barely been switched on. **Value compounds only with time** —
the daily delta needs two readings a day apart, LEARN needs 10 launches.

**Next:** see `09_build_plan.md`. Phase 0 is Settings (real fee/cost numbers) and the
scheduler, because nothing downstream is trustworthy or accumulating without them.

---

## Working style that has paid off here

- **Probe the wire before theorising.** Three plausible, documented explanations for
  the empty tables were all wrong; one live call settled it in seconds (D-24).
- **Diff response keys against the keys the code reads.** That single check would have
  caught the project's biggest bug at any point in its life.
- **When a doc and the code disagree, believe the code — then check the wire.**
  Several docs describe features that were never built.
- **Write the test that proves the bug first.** Two real bugs this session were found
  by a test failing in a way I did not predict.
