# Etsy market intelligence

A decision system for one Etsy seller. It joins three sources — **Pinterest**
(momentum and timing), **Etsy Private** (real search volume, CVR, prices) and
**Etsy Public** (supply, reviews, saturation) — and answers one question:

> **What should I list, when, and will it actually pay?**

It is deliberately *not* a niche checker. Every competitor is a niche checker.
The output is a calendar — 🔴 list now / 🟡 list by *date* / ⚪ watching — with
keyword search as a second door.

**The failure mode it is built against is a plausible wrong number, not a crash.**
Almost every guard in this codebase exists to stop one specific wrong figure
reaching the operator. Recent examples, all found by probing rather than reasoning:

| What looked fine | What was true |
|---|---|
| `sales_per_day: 0.0` for a tracked shop | Etsy's counter steps by 100 at that size. The shop sold *fewer than 21/day* — a bound, not a zero. |
| "US 83% / China 3.1% of listings" | Etsy's ships-from filter returns a *broader* set than the search. Seven countries summed to **1116%** of the market. |
| `min_rating=5` saturation percentage | The filter is silently ignored; its own results are rated 4.8 and 4.9. |
| 7-day and 14-day delivery as two bands | They are cumulative — `≤14` contains `≤7`. Reading them as bands double-counts fast sellers. |

---

## Running it

```bash
.venv/Scripts/python.exe -m core.vault_status
```

**Always use the venv** — the system Python lacks `bs4`, `curl_cffi`, `dotenv`.
**Everything is a module**, run from the repo root; never `python path/to/file.py`.

**Check the vault before any live run.** Sessions come from a Redis vault filled
by a Chrome extension, not from `.env`. An empty pool does not fail — it *hangs*,
in an unbounded sleep loop.

### The things you will actually run

```bash
.venv/Scripts/python.exe -m etsy.analytics.discover
```
Cheap front door — trending terms with real volumes, no quota cost.

```bash
.venv/Scripts/python.exe -m etsy.engines.master_arbitrage
```
Full sweep on a seed keyword: demand, supply, gaps, sourcing, lead time.

```bash
.venv/Scripts/python.exe -m core.scheduler --once
```
Runs whatever readings are due. Already registered as a daily Windows task
(`EtsyScrapperDaily`, 07:00) via `run_scheduler.cmd`.

```bash
.venv/Scripts/python.exe -m etsy.analytics.learn
```
Did past predictions come true? Refuses to tune below 10 launches.

```bash
.venv/Scripts/python.exe -m etsy.analytics.filter_trust
```
Re-audits which Etsy SERP filters can be believed. **9 of 12 currently cannot.**

### Verification

```bash
.venv/Scripts/python.exe -m core.test_graph_db
```
One of ~35 offline suites, **593 assertions**, no network required.

---

## Shape

```
                  ┌───────────────┐
   Pinterest ────►│               │
   Etsy Private ─►│   analytics   │──► calendar · gaps · profit · sourcing
   Etsy Public ──►│               │
                  └───────┬───────┘
                          │
     core/         session vault (Redis) · cache · run log · guards
     mcp_server/   12 read-only tools for Claude / Antigravity
```

| Directory | Holds |
|---|---|
| `etsy/api/{public,private,printify}/` | the three clients. `parse_*` functions own the wire format. |
| `etsy/analytics/` | every judgement: profit, gaps, sourcing, scoring, LEARN |
| `etsy/engines/` | the pipelines that string them together |
| `core/` | sessions, database, cache, scheduler, guards, settings |
| `mcp_server/` | the agent-facing surface |
| `docs/` | see `docs/ONBOARDING.md` first |

---

## The rules that are not negotiable

1. **Never index a raw private-API key** — Etsy returns snake_case, this repo
   historically read camelCase, and seven modules silently read `None` for the
   project's entire life. Use `parse_results_data()`.
2. **Absent is not zero.** A badge that did not render is *unmeasured*, not "no
   demand". Use `None` and let the caller decide.
3. **Bounds are labelled as bounds** and never restated as rates.
4. **Refuse rather than guess.** `PoolTooSmall`, `untrusted_source`,
   `below_resolution` and `uninformative` are all real answers.
5. **Time is append-only.** `*_observations` have `collected_at` in the primary
   key. Derivations may be recomputed; observations may not be overwritten.
6. **Do not touch the access layer.** `core/session_manager.py`,
   `core/cookie_vault.py`, `cookie_server_go/`, `chrome_extension/` — read them,
   never extend them. **No Playwright or headless browsers, ever.**
7. **Rank by winnability, never market size.** A term with 2M listings is a wall.
8. **Public unless seller access is mandatory.** `etsy_private` authenticates as
   the operator's own seller account — the one unreplaceable asset here.

---

## Current state

**Working:** all four API clients · profit gate and its two inverses · survivor
bound · gap analysis with a filter-trust gate · sourcing and lead time · POD
costing · scoring with a discrimination check · scheduler · LEARN scaffold ·
12 MCP tools.

**Thin:** the data. 84 trend observations, 304 listing observations, 6 shop
readings, 1 keyword observation, **0 launches**. The machine is built and has
barely been switched on, and **value here compounds only with time** — a daily
delta needs two readings a day apart, and LEARN needs 10 launches. None of it
can be backfilled.

**Blocking the numbers being real:** `config/settings.json` has `"confirmed": []`,
so every profit verdict is *provisional* — computed from default fees and costs
rather than the operator's own.

```bash
.venv/Scripts/python.exe -m core.settings_store show
```

---

## Docs

| File | Answers |
|---|---|
| `docs/ONBOARDING.md` | **start here** — what is true, what is a trap, what to read |
| `docs/MCP.md` | wiring the MCP server into Claude / Antigravity, and where DeepSeek belongs |
| `docs/HOW_WE_WORK.md` | the three seats and the loop |
| `docs/market_map/` | per-platform endpoint reference and what each signal is worth |
| `docs/architecture/09_build_plan.md` | what is being built, in what order |
| `docs/DECISION_LOG.md` | why anything is the way it is |
| `CLAUDE.md` | operational notes for an agent working in this repo |
