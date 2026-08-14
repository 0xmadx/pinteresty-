# Claude Code — setup

Two things here: a **project brief** (the plan/goal you hand Claude Code) and a
reusable **skill** that makes the architecture pass consistent.

## Files

```
claude_code/
├── PROJECT_BRIEF.md                          ← the plan: goal, scope, deliverables
└── .claude/
    └── skills/
        └── system-architect/
            └── SKILL.md                       ← the reusable skill
```

## How to use it

1. **Copy `.claude/` into your project root** (the scraper repo). Claude Code
   auto-discovers skills in `.claude/skills/`.
2. **Copy the goal/spec docs into the repo too** so Claude Code can read them:
   `MASTER_DOCUMENT.md`, the `blueprint/` folder, `SYSTEMS_ARCHITECTURE.md`,
   `CACHING_AND_OPTIMIZATION.md`, `CAPABILITY_COUNT_DEDUP.md`.
3. **Give Claude Code the brief.** Point it at `PROJECT_BRIEF.md` as the task —
   e.g. "Read PROJECT_BRIEF.md and do the architecture pass it describes."
4. The `system-architect` skill triggers on that kind of work and enforces the
   rules (mark exists/missing/aspirational, count functions not descriptions,
   never touch the access layer, respect the three invariants).

## What it will and won't do

**Will:** read and analyze your **entire** codebase — access layer included, since
data flow starts there — inventory every module, identify the real design approach
and dependency structure, resolve the tool count, determine the stack, produce
seven architecture docs under `docs/architecture/`, and log every contradiction
with locations.

**Won't:** **extend** the scraping/bypass access layer (documenting and critiquing
it is fine; adding evasion capability is not), build the UI (next phase), or
migrate to official APIs.

The three deepest deliverables are **design approach**, **data flow**, and
**stack** — the primary questions.

## The point of this pass

A clean, honest, buildable picture of the scraper **as it is** — the foundation
the UI gets built on next. The brief and skill are tuned so Claude Code produces
*accuracy over optimism*: a flagged gap is worth more than a confident guess.

## After this pass

Once the six docs exist and the tool count is real, the next phase is the UI
(`blueprint/06_ui_structure.md` is the target). Hand Claude Code that doc as the
next brief when you're ready.
