# Reference — Etsy Private (the seller tool)

**Demand truth.** `etsy/api/private/api.py`. Authenticates as the operator's OWN seller
account (Marketplace Insights) — the scarce, unreplaceable asset (D-29). Use ONLY for
what no public call can answer. No quota has ever been observed (D-14).

⚠️ **Every response is snake_case.** Read through the parsers, never raw keys — this is
the bug that emptied every table for the life of the project.
⚠️ **401/403 → `SessionDown`** (browser/extension off), NOT a broken endpoint.

Legend: ✅ verified live · ⚠️ empty/None · ❓ present on the wire, never parsed · ❌ dead.

---

## `get_results_data(query)` — the master demand call ✅ re-verified live 2026-08-27

One keyword in, everything about its demand out. The single most valuable call.
`GET .../marketplace-insights/results-data?query={term}&search_term_hash=&search_trigger=similar_term`

**Full top-level response, live ("mom necklace", 2026-08-27):**
```
competitive_price_data · competitive_research_listing_cards · daily_stats ·
is_competitive_metrics_cvr_enabled · is_competitive_metrics_enabled ·
is_concurrent_data_viz_enabled · is_etsy_plus · is_extended_data_range_enabled ·
is_market_gap_enabled · is_new_features_education_enabled ·
is_new_features_walkthrough_dismissed · is_quota_reached · is_search_allowed ·
is_search_term_saved · is_shop_in_deferred_downgrade · market_gap_max_tiles ·
market_gap_recommendations · max_comparison_terms · max_saved_searches_limit ·
quota_data · search_term_id · shop_subscription_data · shop_tier · similar_search_terms ·
stats · wow_data
```

| Field (via `parse_results_data`) | Meaning | Verified |
|---|---|---|
| `volume` | monthly search volume | ✅ 12,972 |
| `supply` | avg total listings competing | ✅ 368,478 |
| `cvr` | `query_cvr` — the real conversion RATE | ✅ 0.000276 |
| `cvr_bucket` | `cvr` — an ordinal bucket, often 0, NOT the rate | ✅ |
| `price_low` / `price_high` | median band, coerced "$18.00"→18.0 | ✅ |
| `price_bar_low` / `price_bar_high` | a DIFFERENT, wider band — kept separate | ✅ |
| `wow_change` / `wow_direction` | Etsy's own week-over-week % + arrow | ✅ +3.4, up |
| `listings` | **20 competitor cards free** (title, reviews, shop, price, star-seller) | ✅ |
| `quota_total`/`remaining` | 15/15, never moves — not metered | ✅ D-14 |
| `similar_terms` | `similar_search_terms` | ❌ still empty (`total_results_count: 0`), re-confirmed 2026-08-27 |
| `market_gap` | `market_gap_recommendations` | ❌ still `null`, re-confirmed 2026-08-27 |

### 🆕 `daily_stats` — a completely free daily time series, currently unparsed ❓

Found probing the raw response for this refresh, 2026-08-27. Every single call to
`results-data` also carries a **day-by-day** search volume series with a rolling
7-day average, at no extra cost — it rides on the same call `get_results_data`
already makes. Nothing in this codebase reads it.

```json
"daily_stats": {"stats": [
  {"date": "Jul 22", "search_volume": 246, "wow_rolling_average": 408},
  {"date": "Jul 23", "search_volume": 189, "wow_rolling_average": 358},
  ...
  {"date": "Aug 11", "search_volume": ...}
]}
```

This is a materially different instrument from `get_chart_series` (§ below), not a
duplicate: `chart-series` is **monthly** resolution over a year; `daily_stats` is
**daily** resolution over roughly the trailing 3 weeks. For a calendar-first product
whose whole premise is "list by day N," a daily curve is a strictly sharper timing
signal than a monthly one, and it costs nothing beyond a call this project already
makes on every measured keyword. Same shape trap as everything else here applies —
`search_volume` per day, not per week or month; do not assume the field name matches
`get_chart_series`' points.

**Not wired into anything.** This is a found-but-unbuilt capability, not a bug —
flagging it for a decision, same as `get_trending_terms` was before D-43 wired it in.

### Other new top-level fields, checked and NOT worth building on
`shop_tier`, `shop_subscription_data`, `is_etsy_plus`, `is_shop_in_deferred_downgrade`,
`is_search_allowed`, `is_search_term_saved`, and the `is_*_enabled` flags are the
operator's OWN shop/subscription/feature-flag state, not market data — Etsy telling
its own dashboard what UI to render. `search_term_id`, `market_gap_max_tiles`,
`max_comparison_terms` (2), `max_saved_searches_limit` (50) are UI-limit metadata
with no use here. None of these belong in `parse_results_data`.

---

## `get_chart_series(terms, days=365)` — the SEASONAL CYCLE + compare ✅ 2026-08-27
`POST .../marketplace-insights/chart-series-data`
`{search_terms:[...], days, include_trendline:false, include_wow_data:true, include_search_volume:true, include_avg_total_listings:true}`

Pass a LIST of terms → a 12-month time series for EACH. The "cycle diagram".

🚨 **THE ENDPOINT ANSWERS ONLY THE FIRST 3 TERMS.** Positionally, silently, with a
well-formed 200. Measured 2026-09-01. This page previously said *"pass a LIST"* and
stated **no maximum**, which is how the scheduler came to send 11 terms every day and
store 3 — terms 1, 2 and 3, every run, for the life of the job. `MAX_CHART_TERMS = 3`
now lives in `etsy/api/private/api.py` and `get_chart_series` **chunks and merges**,
so callers may pass any number of terms. Cost is `ceil(N / 3)` requests.

- `series[].points[]` = `{timestamp, label "Sep 2025", value}` — 12 monthly points.
  **Now parsed** by `parse_chart_series()` (D-45) — read the `series` block, not just
  `term_summaries`. `is_last_bucket_partial` rides on every curve: the final point is
  the current month counted so far, and reading it naively manufactures a false
  collapse.
- **A missing term has three possible causes, and they are not interchangeable.** Use
  `chart_coverage()`: `omitted` (asked, request succeeded, Etsy sent nothing — this
  and only this is N-02 unmeasured), vs `failed_chunks > 0` (may never have been
  fetched), vs never requested at all.

  ⚠️ **DISPUTED, pending a re-probe.** This page and the parser docstring both cited
  *"asked for four terms, `linen apron` came back absent"* as a worked example of
  N-02. With a measured positional ceiling of exactly 3, a four-in / three-out result
  **is the ceiling** and `linen apron` sat on the cut. Treat it as unresolved — probe
  `linen apron` ALONE before repeating either reading.
- `term_summaries[]` = per-term `{search_volume, avg_total_listings, wow_data}` —
  read via `parse_term_summaries()`.
- **Multi-term compare**: up to 3 per request; the client chunks above that.
- Verified: "mom necklace" peaks Nov–Dec (Christmas) + April (pre-Mother's Day);
  `christmas ornament` peaks Nov at 93× its trough.
- **This is the calendar's engine, from Etsy alone.** No Pinterest needed for
  seasonality — see D-45.
- `include_trendline` is **inert** — probed 2026-08-20, `True`/`False` return
  byte-identical structures. Left `False`; setting it would only imply it does
  something.

---

## `get_similar_keywords(keyword, iterations=10)` — the RECURSIVE keyword tree ✅ 2026-08-27
Async, two-step:
- Enqueue `POST .../llm-exploratory-keywords/search/enqueue` `{keyword}` →
  `{run_id, thread_id, cached_data}`. If Etsy already computed the keyword,
  `cached_data` is full on enqueue (instant). Cold → poll `.../poll`
  `{run_id, thread_id, search_term}`: **400 with a null body, 202, or 200-null all
  mean "still cooking, keep polling"** — only a 401/403/429 or a parseable 200
  result ends the loop.
- One keyword → ~120–165 related terms, EACH with `search_volume` and
  `avg_total_listings` inline — no separate lookup needed per term.
- Results key the term on `search_term` (snake). Read via `edge_term()`, which also
  accepts `searchTerm`/`query`/`term`/`keyword` so a future spelling drift cannot
  silently zero the crawl again (this already happened once, at three layers).
- The tree has **cycles** ("felt banner" → "felt garland" back) — a crawl must
  dedupe; `keyword_crawl.py` does.
- `iterations` controls how many enqueue+poll rounds run (and de-dupe) per call —
  restored to 10 from an old frugality hack; `edges_per_node` on the caller side
  controls how many of those get kept.
- Powers `discover.expand_seed`, `hunt --seed`, `MasterNicheFinder`'s BFS crawl.

---

## `get_trending_terms(taxonomy_id=199)` — curated front door ✅ 2026-08-27
`GET .../marketplace-insights/trending-search-terms-v2?taxonomy_id={id}`. Rising
terms per category, with volumes, no quota cost.
⚠️ **Only 7 of 15 probed taxonomy ids populated:** 1, 66, 199, 323, 891, 1429, 1633
— 28 terms total.
⚠️ **Etsy's PICKS, not the market** — `basis="etsy_curated"`, B-01 applies at
discovery. The seed crawl (`get_similar_keywords`) is the stronger discovery path.
**Wired in** as the DISCOVER front door (`etsy.analytics.discover`) — this was
listed as "built, unwired" as recently as 2026-08-16; it is not any more.

---

## What the private tier UNIQUELY answers
- real search **volume** (not a proxy) — public SERP gives total listings, not searches
- real **CVR** — nobody else has conversion
- the 12-month **seasonal cycle**, now with a daily-resolution alternative sitting
  unused right beside it (`daily_stats`)
- the **keyword tree** with metrics inline
- Etsy's **own** week-over-week momentum, free in every results-data call

Everything about competitors, listings, tags, SERP → **public tier, always** (D-29).
