---
name: etsy-private-tier
description: Use when calling, wiring, or reasoning about Etsy Private (Marketplace Insights) — results_data, chart_series, daily_stats, similar_keywords, trending — or when deciding whether a question is worth the seller account at all. Enforces D-29 (this authenticates as the operator's OWN shop), the snake_case parsers, SessionDown vs 429, and that query_cvr is relative-only with no known units. Trigger on etsy_private, results-data, chart-series, CVR, search volume, keyword expansion, or "measure this term".
---

# Etsy Private — the scarce tier

**This authenticates as the operator's own seller account.** It is the single
unreplaceable asset in the system. A burned buyer session costs a re-login; a
burned seller account costs the business.

Everything below follows from that.

---

## 1. Spend it LAST, and only on survivors

The value chain is **discover cheap → qualify public → measure private**. Private
is where you confirm, never where you browse.

| Question | Tier |
|---|---|
| what terms exist near this seed? | Pinterest `expand`, or private `similar_keywords` if you must |
| how many compete, what do they tag? | **public** — unlimited, safe |
| real volume, real CVR, the seasonal curve | **private** — nothing else answers these |
| who ranks, what do they charge? | **public** — 20 competitor cards also ride free on `results_data` |

A run that calls `results_data` on 100 raw ideas has spent the irreplaceable
account on a question free tools answer.

**Never put a competitor's `shop_id` in a private URL.** The `{shop_id}` template
is *who we are*, not who we are asking about. Substituting a competitor's is both
wrong data and a ban signal.

---

## 2. Read through the parsers. Never index a raw key.

Etsy returns **snake_case**; this repo historically read **camelCase**. Seven
modules fetched correct data and read `None` out of it. **Every table in the
system held 0 rows for the project's entire life** because of this.

```python
from etsy.api.private.api import parse_results_data, parse_term_summaries, parse_chart_series, edge_term

data = parse_results_data(api.get_results_data(kw))   # ✅
vol  = data["stats"]["searchVolume"]                  # ❌ silently None forever
```

The parsers accept **both** spellings so a future drift in either direction cannot
re-zero the system. `edge_term(e)` for keyword edges — the enqueue keys them
`search_term`, older consumers read `searchTerm`, and a mismatch makes a crawl
stop silently at the seed while looking exactly like "the API returned nothing".

**When you add a field, add it to the parser — not to the caller.**

---

## 3. What this tier uniquely knows

| Call | Gives | Note |
|---|---|---|
| `results_data` | volume, supply, `query_cvr`, price band, **20 competitor cards free** | one call; do not scrape the SERP to rebuild the cards |
| `daily_stats` | a **daily** volume curve + 7-day rolling average | rides free on the SAME `results_data` call (D-51). ~3 weeks of days. Answers "is this moving NOW" |
| `chart_series` | the **12-month** curve, multi-term | ⚠️ **Etsy answers only 3 terms per request, silently and positionally.** The client chunks; cost is `ceil(N/3)`. Read an absence via `chart_coverage()`, never `returned` alone. ⚠️ last bucket is the current month counted so far — judging on it manufactures a collapse (D-45) |
| `similar_keywords` | ~120–165 terms, **each already sized** with volume and supply | async enqueue+poll; the tree has CYCLES, dedupe |
| `trending` | rising terms per taxonomy | ⚠️ Etsy's PICKS, not the market (B-01). Only 7 of 15 taxonomy ids return anything |

---

## 4. `query_cvr` has NO KNOWN UNITS

The most dangerous number on this tier, because it looks like a rate you can
multiply.

> `volume × query_cvr` for `personalized gift` implies **39.8 orders/month
> market-wide** — for a term whose #1 listing holds **14,733 reviews**.

It is a rate against a denominator Etsy does not publish. **Compare it BETWEEN
terms; never threshold it as a quantity** (D-43). `opportunity.market_demand()`
claimed otherwise for the project's whole life; its basis is now
`relative_only`.

`cvr_bucket` is a *different* field — an ordinal bucket that is often 0. Not the
rate. Do not substitute one for the other.

---

## 5. Failures: tell them apart before debugging

| Signal | Means | Do |
|---|---|---|
| **401 / 403** | session stale or absent — browser/extension off | raises `SessionDown`. Check `python -m core.vault_status`. **Not** a broken endpoint |
| **429** | real throttling | the session is FINE. `classify()` must not evict on this |
| empty result, 200 | could be genuine, could be a parser bug | prove the pattern matches before believing the data is absent |

**When a private call returns nothing, suspect the session BEFORE the code.** A
dead seller session and a broken endpoint look identical from the consumer side —
this exact ambiguity once made a *working* endpoint look like a bug for days.

Order of suspicion is fixed: `vault_status` → then diff response keys against
what the code reads.

---

## 6. Cost, measured

`get_similar_keywords(iterations=N)` runs **N enqueue rounds**, each polling 2–3
times. At the CLI default of 10 that is ~35 requests and **~90 seconds per
keyword**. The MCP path caps it at 3.

`results_data` is cached 7 days, `similar_keywords` 30 days. **A repeat is free** —
a 40-term crawl of an already-seen neighbourhood returned in under a second
having spent nothing. So a request-count estimate is an **upper bound**, never a
measurement.

No quota has ever been observed (D-14): `quota_data` reports 15/15 and does not
move across distinct calls. The ceiling is folklore inherited from old docs.

---

## Anti-patterns

- Calling `results_data` to browse rather than to confirm
- Indexing a raw API key instead of using the parser *(cost: the entire dataset)*
- Multiplying `volume × query_cvr` and calling it orders
- Treating a 401 as an endpoint bug, or letting a 429 evict a session
- Reading the last `chart_series` bucket as a real reading
- Reading a term missing from `chart_series` as "Etsy cannot size it" without
  checking `chart_coverage` — for the project's life that meant "we never asked"
- Reporting a derived request count as if it were measured
