---
name: ui-builder
description: Use when building the web dashboard UI for the niche decision tool — React pages, components, the API-consuming layer, and the visual surface. Enforces decision-first layout, source separation (three cards before one verdict), honest surfacing of estimates and confidence, and building only against endpoints that actually exist. Trigger on "build the UI", "the dashboard", "the frontend", any page/component work, or wiring the frontend to the API.
---

# UI Builder

You build the dashboard **against what the backend actually exposes**, not against
what the design docs hoped for. The architecture pass (`docs/architecture/`) and
the read API define what data exists. Build only what real endpoints can feed.

## Prime directive: don't build UI for data that doesn't exist

Before building any page or component:

1. Read `docs/architecture/` to learn what the code actually produces.
2. Read `docs/architecture/bias_audit.md` — the **verified** bias picture. Two of
   the Tier-4 statements this skill requires you to display ("survivor data only",
   "Pinterest predicts interest") have **no backing number in the code yet**, so
   they get an honest empty state rather than a label over a figure that does not
   exist. Do not trust `BIASES_AND_BLIND_SPOTS.md` alone — it is self-declared
   unverified, and 2 of its 10 claims turned out to be wrong.
3. Read the API routes to learn what's actually served.
4. Build only components backed by a real endpoint returning real fields.
5. A page whose data isn't produced yet is **stubbed with an empty state that
   says why**, never faked with mock data that looks real.

> Faking data in the UI is the same sin as the backend returning a plausible wrong
> number. An empty state that says "rank tracking starts once you log a launch" is
> honest; a chart of invented ranks is a lie the user will trust.

## The design system

The full visual spec is `docs/blueprint/06_ui_structure.md` (moved there 2026-08-11 —
it had been misfiled in `docs/architecture/`, where it collided with the as-built
`06_stack_and_deps.md`). Read it. The essentials:

- **Decision-first, not data-first.** The user gets a verdict and a plan, then
  drills into layers. Never open with a wall of charts.
- **Two front doors, one engine:** keyword search OR paste-a-URL, both landing on
  the same Cockpit.
- **Left rail = views; main = the decision assembling top-to-bottom.**
- **Country is a global selector**, not a page — it re-scopes every view.
- **Ten page types, built in order** (see build order below), not all at once.

## The non-negotiable UI rules (these encode the guards)

### 1. Three cards before one verdict (bias B-05)

The Cockpit shows each source's own verdict — Pinterest, Etsy Private, Etsy Public
— with its own confidence, **before** the combined verdict renders. When sources
disagree, the combined banner says so ("Pinterest strong / Etsy weak → may not
convert") instead of showing a clean blended number. Never collapse the three into
one number without the three visible above it.

### 2. Estimates look different from measurements

A derived number (competitor sales, est. views) must be *visually distinct* from a
measured one (your own sales, daily delta). Different weight, a marker, a tooltip —
something. The user must never mistake an estimate for a fact.

### 3. Confidence is visible, and low confidence reads as "guess"

A low-confidence score is not a soft asterisk. `cvr_source=default` or `noisy=true`
must surface as plain language: "this is an estimate" / "trend signal unreliable."
Three primitives carry this everywhere: a freshness badge, a confidence tag, a
provenance dot.

### 4. Freshness travels to the screen

Every value shows its age when it matters. A month-old supply count next to a fresh
Pinterest reading must not look equally current.

### 5. Market language on the surface, honest signal underneath

Copy speaks the seller's language ("310 sales in 7 days", "$8.40 profit per unit",
"list by Sept 12") — but the translation never drops a caveat. Survivor-only data
is still labeled survivor-only; an estimate still says estimated. Friendly ≠
dishonest. See `BIASES_AND_BLIND_SPOTS.md` Tier 4 for the exact phrasings.

## Stack

> ⚠️ `blueprint/05_stack.md` **does not exist in this repo** — the blueprint set is
> 3 of 8 (`02_data_model`, `04_pipelines`, `06_ui_structure` only; `00`, `01`, `03`,
> `05`, `07` were never added). The stack below is therefore the authoritative
> statement, not a summary of a fuller doc. Cross-check against
> `architecture/06_stack_and_deps.md`, which records what is actually installed.

- React + Vite (SPA, no SSR — it's a logged-in dashboard, nothing to server-render)
- TanStack Query for server state — mirror the backend's freshness model client-side
- Recharts/visx for charts; drop to D3 only for one bespoke thing if ever
- No global state library at this size — URL + query cache is enough
- CSS variables for theming; must work light and dark
- No browser storage APIs beyond what the framework needs

## The read-only contract

The UI **only reads**. It never triggers a scrape, never runs a pipeline. The one
write path is Settings (and optionally *enqueueing* a batch job, which returns
immediately — the job writes, not the request). A user click must never wait on a
provider call that could be slow or fail.

## Build order (outward before inward)

Build in this order because inward views need history the system hasn't collected
on day one:

1. **Settings** — first. Nothing else works without the operator's costs/fees/labor.
2. **Calendar** — **the home screen** (D-20), and ✅ **built 2026-08-20**
   (`etsy/ui/calendar_page.py`). This moved up from #4: the operator chose a
   calendar-first product, and `06_ui_structure.md` was updated to match. An older
   version of this list put Discover here; that is superseded.
3. **Cockpit** — the decision screen for one candidate (the product's core).
4. **Discover** — the ranked candidate pool, reached from the search bar.
5. **Market + X-ray** — competitive depth.
6. **My Shops / Performance** — inward views, LAST, once launches and ranks exist.

Ship 1–3 as a usable product. Do not build 4–6 until 1–3 work on real data.

### There is no read API, and that changes the stack question

`06_ui_structure.md` specifies a React SPA calling `GET /launch-plans`. **No such
endpoint exists** — the only HTTP server in the repo is `core/cookie_server.py`,
which is dead code nothing imports. The prime directive above therefore bites on the
whole stack, not just on one component.

The Calendar was built as a **generated page** for that reason: no server, no build
step, no daemon — matching how everything else here runs — and it satisfies the
read-only contract absolutely, because a file cannot trigger a fetch. Regenerated
daily by the scheduler, plus an `.ics` export so deadlines land in the operator's
real calendar rather than in a tool they must remember to open.

Build the next screen the same way unless a read API exists by then. If you add one,
the SPA replaces these renderers without touching the engine underneath.

## Empty states are a feature, not a fallback

Every view needs a real empty state that explains *why* it's empty and what unlocks
it:
- Performance with <10 launches: "Weight tuning unlocks at 10 launches — 7 to go."
- My Shops before any shop is added: "Add your shop name to start tracking."
- Rank tracking before observations: "Rank history builds over your first weeks."

An empty state that teaches is worth more than a chart of fake data.

## Component checklist (per component)

- Backed by a real endpoint? (or an honest empty state)
- Estimates visually distinct from measurements?
- Confidence + freshness surfaced?
- Works in light and dark mode?
- Rounds displayed numbers (no float artifacts)?
- Loading and error states, not just the happy path?
- No mock data that could be mistaken for real?

## Anti-patterns

- Building a page for data the backend doesn't produce yet.
- Mock data that looks like real data.
- One blended score with no source breakdown.
- Estimates and measurements with identical styling.
- Low confidence shown as a small gray asterisk.
- The UI triggering a fetch on user click.
- Ten pages built before three work.
- Charts where an empty state would be honest.
