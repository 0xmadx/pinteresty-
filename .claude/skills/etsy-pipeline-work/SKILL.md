---
name: etsy-pipeline-work
description: Use when building, extending, or debugging any data pipeline, API client, endpoint, or analytics module in this Etsy/Pinterest repo — adding an endpoint, wiring a new signal, fixing a scraper, writing an engine, or investigating why data is missing or a table is empty. Enforces verifying endpoints live before building on them, using the response parsers instead of raw keys, and the absent-is-not-zero rule.
---

# Etsy Pipeline Work

How to build in this repo without repeating mistakes that have already cost this
project its entire dataset. `CLAUDE.md` has the quick reference; this is the method.

---

## Rule 1 — Verify the endpoint live BEFORE building on it

The project's founding rule said this from the start:

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

**You may fetch live data while building — check the vault first.** Sessions come from
Redis now (D-28), and an empty pool makes the call **hang forever**, not fail:

```bash
.venv/Scripts/python.exe -m core.vault_status     # one second; run it before any long job
```

A `401`/`403` means the profile is not authenticated as a seller — auth, *not* a rate
limit. See `docs/architecture/10_session_layer.md`.

**When a private endpoint returns nothing, check the session BEFORE the code.** A dead
seller session (browser/extension off) and a broken endpoint look identical from the
consumer's side — an empty result. This exact ambiguity once made a *working* endpoint
look like a bug: the operator's browser was off, the session was stale, and the empty
response was diagnosed as a code fault. The order of suspicion is fixed:

1. `python -m core.vault_status` — is there a live `etsy_private` profile?
2. only then diff the response keys against the code

The private clients now raise **`SessionDown`** on a 401/403 rather than returning
`None`, so this can't be silently mistaken again. If you add a private endpoint, raise
it too.

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

`core/session_manager.py`, `core/cookie_vault.py`, `cookie_server_go/`,
`chrome_extension/`, `pinterest/core/client.py`. Read them, document them, depend on
them. Do **not** extend, refactor or improve them.

`10_session_layer.md` lists eight real defects in this layer (S-1…S-8). **They are the
operator's to fix.** Finding a ninth means documenting it there — not patching it.

**No Playwright, Puppeteer or headless browsers, ever** — the prohibition predates this
work (`_old_etsy_master_architecture.md:153`). `requests` and `curl_cffi` are fine.

Adding *observation* (counting a 429, naming an error) is acceptable; adding
*capability* (new auth, new cookie handling, retry/backoff policy) is not.

---

## Rule 7 — Public tier unless seller access is mandatory (D-29)

`etsy_private` is the operator's **own** seller account — the one thing here that
cannot be replaced. Before writing any fetch, ask which tier owes you the answer:

| You need | Platform |
|---|---|
| search volume · CVR · chart series · trending terms · LLM keywords | `etsy_private` |
| competitor shops · listings · reviews · SERP · saturation | `etsy` |

**Never pass a competitor's `shop_id` into a private URL.** The `{shop_id}` template is
*whose dashboard we are authenticated as* — substituting a competitor's is wrong data
*and* a ban signal.

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
