# Reference — Etsy Private (the seller tool)

**Demand truth.** `etsy/api/private/api.py`. Authenticates as the operator's OWN seller
account (Marketplace Insights) — the scarce, unreplaceable asset (D-29). Use ONLY for
what no public call can answer. No quota has ever been observed (D-14).

⚠️ **Every response is snake_case.** Read through the parsers, never raw keys — this is
the bug that emptied every table for the life of the project.
⚠️ **401/403 → `SessionDown`** (browser/extension off), NOT a broken endpoint.

Legend: ✅ verified live · ⚠️ empty/None · ❌ dead.

---

## `get_results_data(query)` — the master demand call ✅ 2026-08-16
One keyword in, everything about its demand out. The single most valuable call.

| Field (via `parse_results_data`) | Meaning | Verified |
|---|---|---|
| `volume` | monthly search volume | ✅ |
| `supply` | avg total listings competing | ✅ |
| `cvr` | `query_cvr` — the real conversion RATE | ✅ |
| `cvr_bucket` | `cvr` — an ordinal bucket, often 0, NOT the rate | ✅ |
| `price_low` / `price_high` | median band, coerced "$15.30"→15.30 | ✅ |
| `price_bar_low` / `price_bar_high` | a DIFFERENT, wider band — kept separate | ✅ |
| `wow_change` | Etsy's own week-over-week % | ✅ |
| `listings` | **20 competitor cards free** (title, reviews, shop, price, star-seller) | ✅ |
| `quota_total`/`remaining` | 15/15, never moves — not metered | ✅ D-14 |
| `similar_terms` | `similar_search_terms` | ❌ empty, total_results_count 0 |
| `market_gap` | `market_gap_recommendations` | ❌ null |

**Payload:** GET, query string. `?query={term}&search_term_hash=&search_trigger=similar_term`.

---

## `get_chart_series(terms, days=365)` — the SEASONAL CYCLE + compare ✅ 2026-08-16
Pass a LIST of terms → a 12-month time series for EACH, in one call. The "cycle diagram".

- `series[].points[]` = `{timestamp, label "Sep 2025", value}` — 12 monthly points
- `term_summaries[]` = per-term `{search_volume, avg_total_listings}`
- **Multi-term compare** in one call (pass 2+ terms → 2+ series).
- Verified: "mom necklace" peaks Nov–Dec (Christmas) + April (pre-Mother's Day).
- **This is the calendar's engine, from Etsy alone.** The points series is NOT parsed
  yet — the peak→list-by feature would read it.

**Payload:** POST, JSON: `{search_terms:[...], days, include_wow_data, include_search_volume,
include_avg_total_listings}`.

---

## `get_similar_keywords(keyword)` — the RECURSIVE keyword tree ✅ 2026-08-16
The LLM expansion. One keyword → ~120–165 related terms, EACH with `search_volume` and
`avg_total_listings` inline. Powers `expand_seed`, `hunt --seed`, `keyword_crawl`.

- **Async, two-step.** Enqueue `POST .../llm-exploratory-keywords/search/enqueue`
  `{keyword}` → `{run_id, thread_id, cached_data}`. If Etsy already computed the keyword,
  `cached_data` is full on enqueue (instant). Cold → poll `.../poll`
  `{run_id, thread_id, search_term}`: 202/400 while cooking → 200 with results.
- Results key the term on `search_term` (snake). Read via `edge_term`.
- The tree has **cycles** ("felt banner" → "felt garland" back) — a crawl must dedupe.
- Fixed after the snake_case bug hid at THREE layers (enqueue `run_id`, poll loop,
  `edge_term`). RK-2.

---

## `get_trending_terms(taxonomy_id=199)` — curated front door ✅ 2026-08-16
Rising terms per category, with volumes, no quota cost.
⚠️ **Only 7 of 15 taxonomy ids populated:** 1, 66, 199, 323, 891, 1429, 1633. 28 terms.
⚠️ **Etsy's PICKS, not the market** — tag `etsy_curated`, B-01 at discovery. The seed
crawl (get_similar_keywords) is the stronger discovery path.

---

## What the private tier UNIQUELY answers
- real search **volume** (not a proxy) — public SERP gives total listings, not searches
- real **CVR** — nobody else has conversion
- the 12-month **seasonal cycle** — timing without Pinterest
- the **keyword tree** with metrics inline
- Etsy's **own** week-over-week momentum, free in every results-data call

Everything about competitors, listings, tags, SERP → **public tier, always** (D-29).
