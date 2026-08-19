# Onboarding — read this before touching anything

For a fresh session (human or agent) picking this repo up cold. `CLAUDE.md` is
the operational cheat sheet; this is the *why*, and the list of things that have
already gone wrong so they do not go wrong again.

---

## 1. What this system is for

One operator sells on Etsy — digital, physical **and** personalized. This system
decides **what to list, when, and whether it pays.**

The output is a **calendar**, not a search box. "Should I make personalized
towels?" is a question every competitor's tool answers. "It is 19 August and
Halloween ornaments need to be listed within 11 days" is not.

---

## 2. The one failure mode

> **A plausible wrong number, not a crash.**

A crash is free — you see it and fix it. A number that is well-formed, sits in a
sensible range, and is *wrong* gets acted on. It costs a launch, and the operator
never learns why.

Every guard in this codebase traces to one of these. Four found in the last two
days, all by probing the wire rather than reasoning about it:

**`locationQuery` is not a filter.** Etsy's ships-from parameter returns a
*broader* result set than the search it filters. On a query with 10,011 listings,
Germany returned 28,271. Seven countries summed to **1116%** of the market they
claim to partition. Four of the eight were individually below the total and
passed every per-call sanity check — only the SUM revealed it. Origin share is
now measured by sampling listings, and `find_gaps` refuses the filter outright.

**9 of 12 SERP filters cannot be believed.** `min_rating=5` returns listings
rated 4.8 and 4.9 and a count identical to the unfiltered search. Colour brackets
sum to 562% of supply. `is_digital` reports more digital towels than towels.
`config/filter_trust.json` records the verdict and `find_gaps` enforces it.

**`total_results` is an estimate.** Repeating an identical unfiltered search
returned 217,196 / 217,196 / 217,395. Exact-equality tests on it are fragile;
`COUNT_JITTER` (2%) absorbs the drift.

**Etsy's shop counter is quantised.** A shop displaying "25,100" steps by 100, so
a zero delta means "moved less than the counter can show", not "sold nothing".
The system was reporting `sales_per_day: 0.0, basis: measured_delta` for a
25,000-sale shop across 4.7 days. It now reports a bound.

**The lesson each time was the same: probe the wire, do not reason about it.**
Three plausible, documented explanations for the empty tables (D-24) were all
wrong; one live call settled it in seconds.

---

## 3. Things that will waste your afternoon

| Trap | Reality |
|---|---|
| **An empty session vault HANGS** | `get_valid_account` sleeps in an unbounded loop. It never returns and never errors. Always `python -m core.vault_status` first; use `vault_status.scan()` in code, never `get_valid_account`. |
| **Two Redis servers share port 6379** | `localhost` reaches a stale native one; the real vault is the Docker container at the address in `.env`. If the vault suddenly reads empty, this is the first suspect. |
| **snake_case vs camelCase** | Etsy Private returns snake_case. Seven modules read camelCase and got `None` for the project's whole life. Always go through `parse_results_data` / `parse_term_summaries`. |
| **`.env` and `dump.rdb` hold live secrets** | Both are gitignored. `dump.rdb` contains session cookies. Never `git add -A` in this repo — it has already leaked credentials twice (`.env`, `registry.json`). |
| **Docs describe things that were never built** | When a doc and the code disagree, believe the code — then check the wire. `BIASES_AND_BLIND_SPOTS.md` is self-declared unverified and 2 of its 10 claims were wrong. |
| **`similar_search_terms` / `market_gap_recommendations`** | In the schema, always empty. Probed on three keywords: `total_results_count: 0` every time. Do not build on them. |
| **There is no quota** | `results-data` reports `quota_data {total: 15, remaining: 15}` and three consecutive distinct calls left it at 15/15. This endpoint does not consume it. |
| **Filters are cumulative, not exclusive** | `delivery_days=14` *contains* the `≤7` listings. Reading brackets as bands double-counts. |

---

## 4. How to tell what is actually true

Four checks, in this order:

1. **Does the function exist?** A capability is real when it is a function, not a
   paragraph. Count functions.
2. **Does a test cover it?** ~593 assertions across ~35 offline suites. A test
   that fails in a way you did not predict has found a real bug — twice this week.
3. **What does the wire say?** The vault is usually green; probing is faster and
   more truthful than reasoning. This is explicitly allowed.
4. **What is the `basis`?** Every stored number carries `measured` / `derived` /
   `bound` / `unmeasured` / `provisional`. If it does not, that is the bug.

---

## 5. What is real right now

**Built and tested:** four API clients (Etsy public, Etsy private, Pinterest,
Printify) · profit gate with per-type margin floors and a weekly capacity ceiling
· `required_price` and `affordable_cogs` (its two inverses) · survivor bound ·
gap analysis gated on filter trust · sourcing, origin sampling and lead time ·
POD costing · scoring with a discrimination check · request cache · run log ·
scheduler · LEARN scaffold · 12 MCP tools.

**Empty or thin — and this is the real constraint:**

```
     84  trend_observations      (written today, first ever)
    304  listing_observations
      6  shop_observations       (3 readings x 2 shops)
      1  keyword_observations
      0  launches                <-- LEARN cannot start
```

**Value compounds only with time.** A daily delta is the difference between two
readings. LEARN needs 10 launches, with controls. None of this can be
backfilled — a day the scheduler did not run is gone permanently.

**Every profit verdict is provisional.** `config/settings.json` has
`"confirmed": []`, so the fee schedule, COGS and hourly rate are defaults rather
than the operator's real numbers:

```bash
.venv/Scripts/python.exe -m core.settings_store set global.operator.hourly_rate 25
```

Setting a value marks it confirmed. Until then `basis()` reports the weakest link
and every verdict says `provisional: true`.

---

## 6. Scope boundaries that are not yours to move

**No Playwright, no Puppeteer, no headless browser — ever.** `requests` and
`curl_cffi` are fine. Sessions come from the Chrome extension via the Go cookie
server into Redis. Read that layer, document it, never extend it. If a task seems
to require new session-handling code, stop and say so.

**Never put a competitor's `shop_id` in a private URL.** The `{shop_id}` in a
private endpoint is *who we are*, not who we are asking about. A burned buyer
session costs a re-login; a burned seller account costs the business. Competitor
shops, listings, reviews and SERP are **public, always**.

**No LLM produces a number.** DeepSeek summarises reviews and drafts copy. It
never estimates COGS, volume, price or CVR. See `docs/MCP.md`.

---

## 7. Reading order

1. `README.md` — what it is, how to run it
2. this file — what is true and what is a trap
3. `docs/HOW_WE_WORK.md` — the three seats and the loop
4. `docs/architecture/09_build_plan.md` — what is being built next
5. `docs/market_map/` — per-platform endpoints and what each signal is worth
6. `docs/DECISION_LOG.md` — why anything is the way it is

Skills in `.claude/skills/` are enforced, not advisory. Two matter most and are
deliberately a pair: **`etsy-pipeline-work`** catches a wrong number;
**`etsy-seo-and-opportunity`** catches a correct number shown in the wrong order.
Both cost a wasted launch, and only the first looks like a bug.
