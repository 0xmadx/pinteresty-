# Claude Code Brief — Architecture & System Design Pass

**Your job in one sentence:** study this existing scraper codebase and the
operator's goal, then produce a set of architecture / system-design / data-flow /
stack documents for *this scraper as it exists* — so it's clean, coherent, and
ready to build a UI on later.

You are **not** building the UI. You are **not** rewriting to official APIs. You
are documenting and designing the system that's already here, correctly.

---

## Step 0 — Understand the goal before touching anything

The operator runs their own Etsy shops (digital, physical, and personalized
products) and has built a data system that spans **three sources**:

- **Pinterest** — trend/momentum/audience signals (the accurate, tested half)
- **Etsy Private** — true demand: search volume, CVR, price paid
- **Etsy Public** — supply, competitors, reviews, SEO

The goal of the whole machine is to answer two questions per product idea:
**"should I make this?"** (scoring: demand × momentum × intent ÷ supply × SERP,
with profit at the center) and **"where do I sell it?"** (Etsy vs Shopify vs
Pinterest shop). Plus an inward half: track the operator's own shops and learn
whether the machine's predictions were right.

**Read these first** (they are the product spec and design intent — do not
re-derive them):
- `MASTER_DOCUMENT.md` — what the machine does, the four modes (FIND/JUDGE/
  OPERATE/LEARN), the decision logic
- `blueprint/` (00–07) — the target architecture, data model, pipelines, stack
- `SYSTEMS_ARCHITECTURE.md`, `CACHING_AND_OPTIMIZATION.md` — the scale reasoning
  and caching design
- `CAPABILITY_COUNT_DEDUP.md` — why the tool count is uncertain and what to verify

Your architecture work must be *consistent with* these. Where you find the code
disagreeing with them, report it — don't silently pick a side.

---

## THE BOUNDARY — analyze everything, extend nothing in the access layer

**Read and analyze the entire codebase, including the access layer.** You cannot
document the data flow without understanding where data enters the system, so the
request/session/cookie/fingerprint modules are in scope *for study*: how they're
structured, what they return, how the rest of the system depends on them, where
they sit in the layering.

**What you must NOT do:** extend, improve, refactor, optimize, or write new code
for the evasion/access mechanics —

- the DataDome / anti-bot bypass logic
- cookie relay / cookie sync / the Chrome extension
- `tls_client` fingerprinting, app keys, CSRF/lazy-load intercepts
- anything whose job is *evading detection* or *acquiring credentials*
- **NO PLAYWRIGHT OR BROWSER AUTOMATION:** You are strictly forbidden from writing or running Playwright scripts. Use `core/cookie_server.py` and the existing Chrome Extension for all bypass logic.

So: **document how it works and how the system depends on it — do not make it work
better or add to it.** Describe, map, diagram, critique its coupling. Don't extend
its capability.

If a task would require writing new evasion/access code, **stop and flag it**
rather than proceeding. Everything else in the codebase — pipelines, analytics,
engines, storage, scoring, generators — is fully in scope for both analysis *and*
design recommendations.

---

## What to produce (the deliverables)

Create these under `docs/architecture/`. Each is described by the skill
`system-architect` (read it — it defines format, depth, and the rules below).

1. **`01_system_overview.md`** — what the system is, the three sources, the
   layered shape, the two processes (ingestion vs serving). A map, not prose.
2. **`02_design_approach.md`** — **the central deliverable.** What design approach
   does this codebase actually use? Identify the real patterns in play (layered?
   pipeline? adapter? repository? god-objects? scripts-with-shared-utils?), where
   the abstraction boundaries fall, how modules depend on each other, what's
   coupled that shouldn't be, and what the *intended* approach appears to be
   versus what was actually implemented. Then recommend the target approach and
   the refactor path from here to there.
3. **`03_data_flow.md`** — trace a record's full life through the **real modules**:
   entry → parse → transform → store → derive → output. Include where data is
   transformed, where it's persisted, where it's cached, where provenance is
   kept or lost. Diagram it end to end, then annotate each hop with the file
   that does it.
4. **`04_data_model.md`** — the actual tables/files as they exist now, plus the
   temporal + guard columns they *should* have. Mark what exists vs what's missing.
5. **`05_module_map.md`** — every real module/function grouped by layer, with the
   de-duplicated tool count (map each documented tool to its actual function per
   `CAPABILITY_COUNT_DEDUP.md`). This resolves the "45 tools?" question.
6. **`06_stack_and_deps.md`** — what's actually imported and used today (with
   versions), what each dependency earns its place for, and the **justified target
   stack going forward** (storage, compute, serving, packaging). Flag anything
   heavy that the system's real scale doesn't justify, and anything missing that
   it does.
7. **`07_gaps_and_risks.md`** — the contradictions, the missing guards, the
   temporal bug, dead code, and anything fragile. The honest defect list.

**The three that matter most are `02_design_approach.md`, `03_data_flow.md`, and
`06_stack_and_deps.md`** — design approach, data flow, and stack are the operator's
primary questions. Give them the most depth.

**Not in scope for this pass:** the UI (next phase), the official-API migration,
new feature code. Design and document only.

---

## The three invariants your architecture must reflect

Every document you write must respect these — they're the spine of the whole
system:

1. **Measured vs derived is tagged on every value.** The failure mode is a
   plausible wrong number, not an error. Wherever the code stores a number, note
   whether it's measured or derived, and whether that's tracked.
2. **Time is first-class.** Anything that changes over time must be append-only
   with a `collected_at`, never overwritten. Flag every place the code overwrites
   history (there is at least one known: the trends upsert).
3. **The source is an implementation detail.** The access layer is a black box
   behind an interface. Your architecture treats "where data comes from" as
   swappable, even though you're not doing the swap now.

---

## How to work

1. **Read the goal docs and the skill first.** Don't start writing until you've
   read `MASTER_DOCUMENT.md`, `blueprint/`, and the `system-architect` skill.
2. **Inventory the real code** — every module, class, function. Build the map from
   what exists, not from what the docs claim.
3. **Cross-check code against the existing docs.** Every contradiction goes in
   `06_gaps_and_risks.md` with the file and line.
4. **Write the six documents.** Diagrams and tables over prose. Mark
   exists / missing / aspirational explicitly.
5. **Do not build the UI. Do not touch the access layer. Do not migrate to APIs.**
6. **End with a one-page summary**: what's solid, what's broken, what's the
   recommended build order for the *next* phase (which will be the UI).

---

## Definition of done

- Six architecture docs exist under `docs/architecture/`, consistent with the
  product spec.
- The tool count is resolved: each documented tool mapped to a real function, or
  marked aspirational.
- Every known contradiction and the temporal bug are logged with locations.
- The access layer appears in diagrams as a black box and was never modified.
- A clear, sequenced recommendation for the UI phase closes it out.

The goal of this pass is a **clean, honest, buildable picture of the system as it
is** — the foundation the UI gets built on next. Accuracy over optimism; a flagged
gap is worth more than a confident guess.
