---
name: etsy-pipeline-work
description: Use when building, extending, or debugging any data pipeline, API client, endpoint, or analytics module in this Etsy/Pinterest repo — adding an endpoint, wiring a new signal, fixing a scraper, writing an engine, or investigating why data is missing or a table is empty. Enforces verifying endpoints live before building on them, using the response parsers instead of raw keys, and the absent-is-not-zero rule.
---

# Etsy Pipeline Work

How to build in this repo without repeating mistakes that have already cost this
project its entire dataset. `CLAUDE.md` has the quick reference; this is the method.

---

## Rule 1 — Verify the endpoint live BEFORE building on it

`.agents/AGENTS.md` has said this from the start:

> *"Always build the Endpoints first to see the big picture. Test and verify all
> endpoints live to discover what actually works. Do not build heavy architecture on
> weak or untested endpoints."*

**It was violated, and here is what it cost.** Etsy returns `snake_case`. Seven
modules were written reading `camelCase` — `searchVolume`, `termSummaries`,
`competitiveResearchListingCards`. Every one fetched correct data and read `None` out
of it. **Every table in the system held 0 rows for the entire life of the project**,
and three separate plausible explanations (a quota, a broken import, missing
scheduling) were argued at length across an architecture pass and a bias audit. All
three were wrong. One live call found it in seconds.

So, before writing or trusting any consumer:

```python
from dotenv import load_dotenv; load_dotenv(override=True)
from etsy.api.private.api import EtsyPrivateAPI
d = EtsyPrivateAPI().get_results_data('mom necklace')
print(list(d))                      # top-level keys
print(list(d['stats']))             # nested keys
```

Then **diff the response keys against the keys the code reads.** That one check is the
highest-value thing in this document.

**You may fetch live data while building.** The cookie server must be running and an
Etsy Shop Manager tab open, or the private API returns 401 (auth — *not* a rate limit).

---

## Rule 2 — Go through the parsers, never raw keys

```python
from etsy.api.private.api import parse_results_data, parse_term_summaries, edge_term

data = parse_results_data(api.get_results_data(kw))     # ✅ stable shape
rows = parse_term_summaries(api.get_chart_series(kws))  # ✅
term = edge_term(edge)                                  # ✅ query | searchTerm
```

They accept both spellings so the drift cannot silently recur, and they normalise two
shapes that otherwise fail quietly: review counts arrive as **strings** (`"1459"`) and
price as a **nested object**.

When you add a field, add it to the parser — not to the caller.

---

## Rule 3 — Absent is not zero

The single most repeated defect class in this repo. A badge that did not render, a
review count that did not parse, a listing not found in the SERP, a shop never
tracked — all **unmeasured**, none of them zero.

```python
daily_sales = listing.get("daily_sales")     # ✅ None when no badge rendered
daily_sales = listing.get("daily_sales", 0)  # ❌ "we couldn't see it" becomes "it sold nothing"
```

Storage follows the same rule: `rank = NULL` means *checked and not found*; **no row**
means *never checked*. They are different facts and both matter to LEARN.

---

## Rule 4 — Refuse rather than guess

Every one of these exists because the alternative was a confident wrong number:

| Situation | Behaviour |
|---|---|
| pool below `MIN_POOL_SIZE` | `PoolTooSmall`, not a score |
| dimensions cannot separate the pool | `can_discriminate()` returns a labelled **filter**, no score |
| only survivors visible | a **bound**, and 100% reads `uninformative`, never "healthy" |
| badge-derived sales | an **upper bound**, clamped to the shop's measured rate |
| fetch failed | not cached, not stored as 0 |
| price unreadable | `None`, never `0.0` |

If you find yourself writing a fallback constant, ask whether `None` plus a reason is
the honest answer instead.

---

## Rule 5 — Write the test that proves the bug first

Two real bugs this session were caught by a test failing in a way that was not
predicted — a `None` format crash and a LIKE-wildcard escape. Both would have shipped.

Tests are hand-rolled `check(label, ok, detail)` scripts (no pytest installed), fully
offline, run as modules:

```bash
.venv/Scripts/python.exe -m etsy.analytics.test_scoring
```

**Never assert an order among genuinely tied items** — that is the N-01 error in
miniature. Assert the set, or assert that the tie is reported.

**Never mix `utcnow()` with hardcoded dates** in one test. One did, and it passed only
until the wall clock crossed the hardcoded date mid-session.

---

## Rule 6 — The access layer is read-only to you

`core/session_manager.py`, `core/cookie_server.py`, `chrome_extension/`,
`pinterest/core/client.py`. Read them, document them, depend on them. Do **not**
extend, refactor or improve them.

**No Playwright, Puppeteer or headless browsers, ever** — the prohibition predates this
work (`_old_etsy_master_architecture.md:153`). `requests` and `curl_cffi` are fine.

Adding *observation* (counting a 429, naming an error) is acceptable; adding
*capability* (new auth, new cookie handling, retry/backoff policy) is not.

---

## Before you commit

```bash
# every module still parses
.venv/Scripts/python.exe -c "import pathlib,py_compile;[py_compile.compile(str(p),doraise=True) for p in pathlib.Path('.').rglob('*.py') if '.venv' not in p.parts and '_old' not in p.parts]"

# all 20 offline suites
for t in core.test_graph_db core.test_guards core.test_runlog core.test_request_cache \
         core.test_keyword_provenance etsy.analytics.test_gaps etsy.analytics.test_scoring \
         etsy.analytics.test_profit etsy.analytics.test_profit_gate etsy.analytics.test_derivations \
         etsy.analytics.test_rank_tracker etsy.analytics.test_daily_delta \
         etsy.analytics.test_survivorship etsy.analytics.test_discrimination \
         etsy.analytics.test_tag_mining etsy.analytics.test_freshness \
         etsy.analytics.test_ratio_estimator etsy.analytics.test_term_join \
         etsy.api.public.test_reviews_parse pinterest.tests.test_trends_bridge; do
  .venv/Scripts/python.exe -m $t 2>&1 | tail -1
done
```

Commit atomically per `git-and-comments`: one logical change, conventional message,
the **why** in the body — the diff already shows the what.

---

## Anti-patterns seen in this repo

- Reading a raw provider key instead of the parser *(cost: the entire dataset)*
- `.get(x, 0)` on a value that can be legitimately absent
- Believing a doc over the code, or the code over the wire
- Building a pipeline on an endpoint whose response was never printed
- A fallback constant where `None` + a reason is the truthful answer
- Deleting a guard because it fires often — it firing often is usually the finding
