# Project Rules

## Architecture & Workflow Rules

**Rule 1: Testing and Discovery First, Pipeline Second**
Always build the Endpoints first to see the big picture. Test and verify all endpoints
live to discover what actually works. Keep ONLY the verified endpoints, and THEN build
Pipelines on top of them. Do not build heavy architecture on weak or untested endpoints.

> ⚠️ **This rule was violated, and the cost was the entire dataset.** The pipelines were
> written against assumed field names. Etsy returns `snake_case`; seven modules read
> `camelCase`, fetched correct data, and read `None` out of it — so every table held 0
> rows for the life of the project, while three plausible wrong explanations (a quota, a
> broken import, missing scheduling) were argued at length. One live call settled it.
>
> **The operational form of Rule 1: print the real response, then diff its keys against
> the keys the code reads.** See `DECISION_LOG.md` D-24 and the `etsy-pipeline-work`
> skill.

**Rule 2: Absent is not zero**
A badge that did not render, a count that did not parse, a listing not found — all
*unmeasured*, none of them zero. Use `None` and let the caller decide at the point of
use. `rank = NULL` means "checked, not found"; no row means "never checked".

**Rule 3: Refuse rather than guess**
Where the honest answer is "we cannot know this", return `None` plus a reason rather
than a fallback constant. The system's failure mode is a plausible wrong number, not a
crash.

**Rule 4: The access layer is read-only**
`core/session_manager.py`, `core/cookie_server.py`, `chrome_extension/` — read and
depend on them, never extend them. No Playwright or headless browsers, ever.

---

Start every session with `CLAUDE.md`, then `docs/architecture/09_build_plan.md`.
