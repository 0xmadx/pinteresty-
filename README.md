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
| An empty list of ranked listing ids | The extraction regex never matched. It returned `[]` on every page for years — silently, because empty is a plausible value. There are 39–51. |
| "0% of listings offer this — a gap!" | Measured on 6 listings, the true share could be 39%. The sample cannot tell thin from crowded. |

---

## Running it

**Setting this up for the first time on a fresh clone?** Skip straight to
[`docs/QUICKSTART.md`](docs/QUICKSTART.md) — everything below assumes the vault
and `.env` already exist.

```bash
.venv/Scripts/python.exe -m core.vault_status
```

**Always use the venv** — the system Python lacks `bs4`, `curl_cffi`, `dotenv`.
**Everything is a module**, run from the repo root; never `python path/to/file.py`.

**Check the vault before any live run.** Sessions come from a Redis vault filled
by a Chrome extension, not from `.env`. This project reads db 0 directly — the
only database it uses (D-49). It used to mirror a shared db 0 into a private
db 1 to keep `pinterest-apify` from disturbing its sessions (D-33); that
project has since moved to its own separate Redis, so the mirror had nothing
left to defend against and was retired.

### The things you will actually run

```bash
.venv/Scripts/python.exe -m etsy.engines.calendar_engine
```
**The front door.** What to list and by when — Pinterest takeoff dates joined to
Etsy demand, ranked by winnability.

```bash
.venv/Scripts/python.exe -m etsy.engines.cockpit "christmas ornament"
```
**One candidate, examined.** Three sources read separately, then a verdict — and
the disagreement between them when there is one.

```bash
.venv/Scripts/python.exe -m etsy.analytics.discover
```
Cheap keyword front door — trending terms with real volumes, no quota cost.

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
One of **50 offline suites** — 1,354 assertions, no network required.

`pinterest/tests/` holds 5 further suites that are **live** (their docstrings say so):
they call the real Pinterest API, so their counts move with session state and they
go quiet when the vault is empty. The offline 58 are the gate.

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
     mcp_server/   read-only tools for Claude / Antigravity — THE interface (D-52)
```

There is no UI and no web server. The operator works through an agent, so the
agent's surface is the product — see `docs/MCP.md`.

| Directory | Holds |
|---|---|
| `etsy/api/{public,private,printify}/` | the three clients. `parse_*` functions own the wire format. |
| `etsy/analytics/` | every judgement: profit, gaps, sourcing, scoring, LEARN |
| `etsy/engines/` | the pipelines that string them together |
| `etsy/ui/` | **`app_data.py` only** — the one read layer (D-41), consumed by MCP. The screens that used to live here were deleted (D-52); the package name is kept so no import moves. |
| `core/` | sessions, database, cache, scheduler, guards, settings |
| `pinterest/` | the Pinterest tier — `endpoints/` (client + full wire reference), `pipelines/` (the Etsy-facing joins), and **`products/`: 8 standalone Pinterest tools with their own CLI and 54 live checks** (`pinterest/products/README.md`), which import nothing from Etsy or `core/` |
| `mcp_server/` | the agent-facing surface — 18 tools, wired by `.mcp.json` |
| `cookie_server_go/`, `chrome_extension/` | **the access layer.** Read, never extend. |
| `config/` | `settings.json`, `filter_trust.json`, scheduler state |
| `docs/` | see `docs/ONBOARDING.md` first |
| `tests/legacy/` | ⚠️ **not** the test gate — old access-layer probes; see its README |

**Where the real tests are:** beside the code, as `core/test_*.py`,
`etsy/analytics/test_*.py`, etc. `tests/` holds only pre-refactor probes.

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
6. **Do not touch the access layer** without the operator's explicit say-so.
   `core/session_manager.py`, `core/cookie_vault.py`, `cookie_server_go/`,
   `chrome_extension/`. It was hardened once, on 2026-08-19, with permission —
   see `docs/SESSION_LAYER_FIX.md`. **No Playwright or headless browsers, ever.**
7. **Rank by winnability, never market size.** A term with 2M listings is a wall.
8. **Public unless seller access is mandatory.** `etsy_private` authenticates as
   the operator's own seller account — the one unreplaceable asset here.

---

## Current state

**Working:** **the calendar** · all four API clients · profit gate and its two
inverses · survivor bound · gap analysis with a filter-trust gate and working
demand-in-bracket · sourcing and lead time · POD costing · scoring with a
discrimination check · scheduler running daily · verdict change log · LEARN
scaffold · 18 MCP tools — the interface (D-52).

**Thin:** the data. Trend, listing and shop observations accumulate daily;
keyword history covers 8 watched terms; **0 launches**. The machine is built and has
barely been switched on, and **value here compounds only with time** — a daily
delta needs two readings a day apart, and LEARN needs 10 launches. None of it
can be backfilled.

**Settings confirmed 2026-08-20:** fees verified against Etsy's published schedule,
operator rate $25/hr, capacity 10 hrs/week — `basis()` reports `operator`, so profit
verdicts are no longer blanket-provisional. The margin **floors** are still defaults;
check before trusting a verdict that sits close to one.

```bash
.venv/Scripts/python.exe -m core.settings_store show
```

---

## Docs

| File | Answers |
|---|---|
| `docs/ONBOARDING.md` | **start here** — what is true, what is a trap, what to read |
| `docs/MCP.md` | tutorial: wiring the MCP server into Claude / Antigravity, and where DeepSeek belongs |
| `ROADMAP.md` | what's missing today, and design notes for a future listed-MCP/SaaS version |
| `docs/VAULT_SEPARATION.md` | why this project and `pinterest-apify` no longer share a Redis, and the retired mirror that bridged the gap along the way |
| `docs/SESSION_LAYER_FIX.md` | the four session-layer gaps and how they were closed |
| `docs/HOW_WE_WORK.md` | the three seats and the loop |
| `docs/market_map/` | per-platform endpoint reference and what each signal is worth |
| `docs/architecture/09_build_plan.md` | what is being built, in what order |
| `docs/DECISION_LOG.md` | why anything is the way it is |
| `CLAUDE.md` | operational notes for an agent working in this repo |
