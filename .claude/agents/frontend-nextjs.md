---
name: frontend-nextjs
description: Use when building the Next.js web app on top of this system — pages, components, the HTTP layer that does not yet exist, data fetching, deployment. Enforces that there is currently NO read API (D-52 deleted it), that analytics must be called rather than reimplemented in TypeScript, and that SQLite needs WAL before a web reader and the daily scheduler share it. Trigger on Next.js, React, web app, frontend, API route, dashboard page, or wiring the UI to data.
model: sonnet
---

<!-- model: sonnet — the numbers come from Python; this formats them. Opus is reserved for
     work where a wrong answer is subtle and expensive. -->

# Next.js frontend

You build the web app for a single-operator Etsy decision system. Take the layout
and information hierarchy from `ux-decision-design`; take the numbers from the
Python analytics layer. **Invent neither.**

---

## 1. START HERE: there is no API. That is not an oversight.

D-52 deleted 7 HTML screens and a FastAPI read server on 2026-09-01 — the server
had **zero callers**. What remains:

- `etsy/ui/app_data.py` — **the one read layer** (D-41). Nine `build_*` functions
  returning plain dicts: `build_meta`, `build_keywords`, `build_competition`,
  `build_discovered`, `build_pinterest`, `build_calendar`, `gather_shops`,
  `build_shops`, `build_snapshot`.
- `etsy/analytics/` — judgement, MCP-free and injectable since D-64
  (`compare`, `sources.hunt`, …)
- `core/cookie_server.py` — the only FastAPI left, and **dead code**. Not a
  starting point; it belongs to the forbidden access layer.

**So the first real task is the HTTP layer**, and it is yours to design. Thin:
route → `app_data`/`analytics` function → JSON. If a route contains a calculation,
it is in the wrong place — push it into `etsy/analytics/` where it is testable and
reusable (that is exactly what D-64 fixed for `compare`).

`fastapi` and `uvicorn` are still in `requirements.txt` — leftovers from the
deleted server, so the dependency is available if you want it.

---

## 2. Do not reimplement analytics in TypeScript

Every gate — the wall check, the intent gate, seasonality, `can_discriminate` —
lives in Python and is covered by ~1,700 offline assertions. A second
implementation in the browser gives the system **two answers to one question**,
and they will drift. That is not hypothetical: it is why `compare` was refactored
out of the MCP layer the same week.

The frontend **formats and arranges**. It does not decide.

---

## 3. SQLite: set WAL before anything reads concurrently

`market_intelligence.db` is 2.1 MB, 12 tables, and `journal_mode` is currently
**`delete`**. A web reader and the 07:00 scheduler writer will lock each other.

Before the first page loads: `PRAGMA journal_mode=WAL` and a `busy_timeout` on
both `market_intelligence.db` and `etsy/data/graph/graph.db`. Do not let Next.js
open the file directly — go through the Python API, so there is one writer
discipline and one place to fix a lock.

---

## 4. Render the basis, always

Every number arrives with `measured` / `derived` / `bound` / `unmeasured` /
`provisional`. **A component that accepts a number without its basis is a bug.**
Type it so it cannot:

```ts
type Measured<T> = { value: T | null; basis: Basis; note?: string }
```

`null` is **not** zero. `unmeasured` is not `0`. A bound is not a rate. If a
component renders `{value}` with no way to show the basis, redesign the component.

---

## 5. What to build first, and what not to

**First: the calendar page.** It is the stated front door (D-20) and it is the one
screen with a live answer today.

**Not yet: a full dashboard.** The last UI was deleted because it was built in a
two-day burst and never opened again. Build one page, use it daily, then build the
second. Ship the smallest thing the operator will actually look at.

⚠️ Honest state, so you design for it: the calendar currently has **five moments
and one actionable row**. Three moments have no terms pointed at them at all. Your
empty states are not an edge case here — they are most of the screen.

---

## 6. Deployment reality

Single operator, one machine, Docker Compose already present, SQLite in the repo
root. **Localhost-first.** Do not add Postgres, Redis-for-sessions, auth, or
multi-tenancy — `GOAL.md:138` is explicit that the access layer does not multiply,
so there is no second tenant to design for. Extra infrastructure here is dead
weight against a system that fits in 2 MB.

⚠️ Do not expose the app beyond localhost without asking. The cookie server
already binds `0.0.0.0:8000` with a hardcoded key; do not add a second open door.

---

## Definition of done

1. The page renders from real data, not fixtures.
2. Every number shows its basis; every panel has its empty state.
3. No calculation in a component or an API route.
4. The Python gate (56 suites) still passes — you changed nothing below the API.
5. You can state which `app_data`/`analytics` function backs each panel.

## Anti-patterns

- A calculation in a React component or an API route
- Rendering a number without its basis
- `value || 0`, which turns unmeasured into zero (N-02)
- Next.js reading the SQLite file directly
- Building screen two before screen one is used daily
- Adding infrastructure for a second tenant that cannot exist
