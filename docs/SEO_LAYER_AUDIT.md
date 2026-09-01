# Etsy SEO + Brand System: What You Already Have, What's Missing, and What to Build

*Audited 2026-09-01 across 19 agents. Findings survived an adversarial verify pass;
Part 2b records the plausible gaps that did **not** survive, which is the more useful
half.*

**Independently re-verified before this doc was accepted** — these are not relayed
claims:

| Claim | How it was checked | Result |
|---|---|---|
| The ranked SERP is reduced to an integer daily | read `core/scheduler.py:500` | ✅ `ranked_ids_count=len(...)`, ids discarded; `keyword_competition` has no column for them |
| `chart-series-data` truncates at 3, positionally | `keyword_seasonality` holds **exactly** `felt garland`, `birthday crown`, `felt flower` — terms **1, 2, 3** of the 11 passed daily | ✅ reproduced from stored data, no live call needed |
| `analyze(operation="discriminate")` judges on 2 of 6 dimensions | ran `build_discovered()` and intersected its keys with `scoring.DIMENSIONS` | ✅ overlap is `{momentum, supply}` only |
| `listing_api.py:15` raises on line one | `hasattr(EtsyPublicAPI, 'cookies')` | ✅ `False` |
| `trends_latest` cannot discriminate by source | read `core/database.py:101` | ✅ partitions on `(trend_name, country)` only |
| `score_pool` has no MCP door | grepped every call site | ✅ two CLI engines, zero MCP |
| `private_comparison.py` truncates silently | read `:11` | ✅ `keywords[:3]`, no note in output |

**Not independently re-verified** (single live probe by one agent, believable but
unpinned): the Pinterest `/metrics/` ceiling of ≥60, the `ga_search_query` /
`sr_gallery` occurrence counts, and `Listed on <date>` in the listing page's
`og:description`. Probe before building on them.

---

## Part 1 — What already exists (this is the important part)

You described eight capabilities. **Roughly 55% of them are built, tested, and running daily.** The problem is almost never acquisition. In three separate places this repo **fetches exactly the data you want, every day, then stores a scalar summary and throws the rows away.**

### 1.1 Rank position arithmetic — BUILT, correct, better than what you described

`etsy/analytics/rank_tracker.py:38-70` — `find_rank()` is a pure function that returns **both** rank flavours from a parsed SERP:

```python
for position, card in enumerate(cards, start=1):   # absolute rank, ads included
...
organic_rank = organic_ids.index(listing_id) + 1    # organic rank
```

It keeps both deliberately, because a listing can slide in absolute rank while holding organic rank purely because a competitor started buying ads. That is a distinction most rank trackers get wrong. It is offline-testable and scope-agnostic — it would work unchanged on any competitor listing id.

**Reachable via MCP: no.** No tool wraps it. Its only caller is `track_ranks()`, which begins at `rank_tracker.py:85` with `launches = db.get_launches()`, finds zero, prints "No launches recorded yet", and returns `[]`. That is what the scheduled 56-hour `rank_check` job has done on every run.

### 1.2 The full ranked id list per keyword — BUILT and live

`etsy/api/public/api.py:117-120` extracts `organic_listing_ids` by taking the **longest** `"listing_ids": [...]` match in the SERP HTML. This was broken for the project's entire life (the old regex demanded `"result_count"` within 200 chars) and was fixed 2026-08-20. It now returns **39–51 ids in rank order for one public request.**

That is a 40-deep keyword→position map, free, today.

**Reachable via MCP: yes** — `etsy_public(operation="search")` returns it as `ranked_listing_ids` (`mcp_server/tools_etsy.py:200`).

### 1.3 Per-card shop name, listing id, ad flag, price, reviews, shop tenure — BUILT

`etsy/api/public/api.py:143-161`. Every field your `keyword | listing_id | position | shop_name` table needs already comes back in DOM order from one request:

```
listing_id, title, url, shop_id, shop_name, is_ad, shop_years_on_etsy,
rating, review_count, price, original_price, percent_discount,
free_shipping, star_seller, image_url
```

Position is implicit in list order and is never named as a field. **That single omission is the whole gap.**

**Reachable via MCP: yes** — the full `cards` list comes back from `etsy_public(operation="search")`.

### 1.4 The data is being collected daily and discarded — this is the headline finding

`core/scheduler.py:496-503` (`job_competition_sweep`) pulls a full ranked SERP for your 11 watched terms every day, parses every card correctly, and then persists:

```python
ranked_ids_count=len(serp.get("organic_listing_ids") or []),   # scheduler.py:500
```

An **integer**. The 38 ordered ids are gone. `keyword_competition` (`core/database.py:203`) has a `ranked_ids_count` column and no column for the ids or their order.

In parallel, `core/scheduler.py:257-262` (`job_keyword_sweep`) receives **20 shop-named competitor cards** from the private `results-data` call and records only volume, supply, CVR, price_low, price_high. And `analyze_keyword` (`mcp_server/tools_opportunity.py:62`) returns `competitors_returned: 20` — the count, not the shops.

**The keyword→shop map is computed and thrown away roughly 31 times a day.** Building it costs zero additional requests.

### 1.5 Tag mining and pattern-matching across winners — BUILT, and more sophisticated than you asked for

`etsy/analytics/tag_mining.py:51-124` and `etsy/analytics/blueprint_support.py:14-51`.

`earned_weight()` decays a listing's vote by review count (halflife 100) and shop tenure (halflife 3y), combined with `min()` — the reasoning being that being established on *either* axis is a sufficient non-tag explanation for why it ranks. Floor 0.15, never zero. `mine_consensus()` requires a tag to appear in 2+ listings before it can rank at all. Ads are excluded on purpose: a promoted listing bought its position, so its tags are evidence of a budget, not of what ranks (`blueprint_support.py:81-83`).

`etsy/generators/listing_generator.py:43-56` already counts exact-phrase presence across the top-10 competitor titles and emits a GREEN/YELLOW/KILL `gap_score`.

All 13 tags of any competitor listing come from `etsy/api/public/api.py:204-210` at a 30-day cache.

**Reachable via MCP: tags yes** (`etsy_public(operation="listing")`). **Consensus mining: no** — no tool wraps blueprint or tag mining.

### 1.6 Price relative to who actually ranks — BUILT (D-46)

`results-data`'s median band is market-wide ($11.70–$14.30 on `personalized baby blanket`) while the 20 listings that actually rank charge a median of **$25.19** — free in the same response. Pricing the POD margin floor off the band computes a $5.21 ceiling; off page one, $12.69. The repo already prices off page one. `etsy/analytics/pod_check.py`, reachable via `pod_quote` and `price_and_cost_ladder`.

### 1.7 Review velocity — BUILT with an explicit refusal set

`etsy/analytics/competitor_tracker.py:44-88` differences `total_reviews` between our own sightings and refuses with a named basis rather than producing a number: `insufficient_history`, `window_too_short` (<12h), `unmeasured`, `counter_decreased`. Flags `is_lower_bound: True`. Real data behind it: 605 `listing_observations`, 14 `shop_observations`.

**Reachable via MCP: partially** — `tracked_shops`, and the raw readings via `history(operation="listing")`.

### 1.8 "N bought today" handled as a selection-biased upper bound — BUILT, exemplary

`etsy/analytics/derivations.py:72-127`. Basis values are `daily_badge_x30_upper_bound` or `daily_badge_x30_clamped_to_shop` when the badge implies a listing outsells its own shop. `daily_sales=0` explicitly means "no badge rendered", never "0 sales".

### 1.9 The comparison engine — BUILT, and this is the largest missed reuse in the system

`etsy/analytics/scoring.py:132` (`score_pool`), `:97` (`percentile_ranks`), `:320` (`shortlist`), `:359` (`explain`).

It percentile-normalizes six dimensions (demand, momentum, intent, profit, supply, serp_difficulty), inverts the ones where bigger is worse, maps `None` to `None` rather than to 0.0 so an unmeasured value never asserts "worst in pool", averages tied ranks, carries a freshness floor, and raises `PoolTooSmall` below n=3. When a dimension is missing it redistributes the weight and drops `confidence` proportionally (`scoring.py:165-181`).

`explain()` already emits one human-readable line per dimension saying why a candidate ranked where it did. **That is literally the comparison narrative you are asking for.**

**Reachable via MCP: no.** Its only call sites are two CLI engines. MCP reaches `can_discriminate` (`mcp_server/tools_analyze.py:220-225`) — the guard that says *"this pool cannot be ranked"* — without the thing it guards. **That asymmetry is why the surface feels like it can only judge one term at a time: it can only ever say no to a comparison, never produce one.**

### 1.10 A real ranked comparison table — BUILT and reachable

`etsy/ui/app_data.py:145-164` → `discover()` at `mcp_server/tools_decide.py:59-81` returns exactly the shape you want: term, seed, volume, supply, demand_per_listing, verdict, cvr, momentum, momentum_mom, moment, list_by, timing — one row per term, pre-ranked by demand-per-listing, deduped.

**The limitation is the input, not the output.** It only contains terms the scheduler expanded from watched seeds, filtered to the latest run. You cannot inject terms of your own. This matters for your complaint and I return to it in Part 3.

### 1.11 The discover pipeline is already a two-pass batch design

`etsy/analytics/discover.py:275` (`measure_intent`), `:289` (`reference_median`), `:306` (`judge_intent`). `measure_intent` spends the calls and judges nothing; `reference_median` pools every CVR from this run **plus every CVR ever stored** (`db.measured_cvrs()`); `judge_intent` classifies all terms against that one shared reference. The docstring at `discover.py:264-268` says why: *a single term cannot be judged alone.*

`etsy/analytics/momentum.py:102` (`attach`) tags an entire pool rising/flat/fading/unmeasured off **one batched Pinterest call**.

### 1.12 Shop tenure as a proxy for honeymoon — BUILT

`etsy/api/public/api.py:139` parses `(\d+) years on Etsy` per card and feeds it into `earned_weight`. This is your honeymoon intuition applied at **shop** level. It cannot see a young **listing** in an old shop — which is the case that actually proves a keyword winnable.

### 1.13 Supplier injection seam — BUILT

`etsy/analytics/pod_costing.py:104` — `def find_options(client, term, market="US", limit=8)`. The client is **injected, not constructed**. Only two concrete `PrintifyClient()` instantiations exist in non-test code. Everything downstream consumes `PodOption` objects, not the client.

### 1.14 Multi-source trend storage — BUILT

`trend_observations` has `source` **in the primary key** (`core/database.py:89`) and currently holds two distinct sources side by side: `pinterest_featured_topics` (336 rows) and `pinterest_moments` (39 rows). A second writer can insert without colliding.

---

## Part 2 — What is genuinely missing

Only items that survived independent attack.

### M1 — Rank-over-time for anyone but ourselves *(CONFIRMED)*

Your signal — "climbing 40 → 8" — is about **competitors**, and that is the unbiased dataset. Watching only our own listings reproduces bias B-04, which the repo already names: LEARN can never discover it was wrong to **reject** a niche.

The blocker is narrower than "scope". Only the **subject enumeration** is launch-bound:
- `record_rank` (`core/graph_db.py:523`) carries **no foreign key** to `launches` — contrast `record_launch_outcome`, which raises for an unlaunched listing.
- `get_rank_history` filters on `listing_id` alone.
- MCP `history(operation="rank", subject=...)` already accepts an arbitrary listing id.

**The storage and read halves need zero change.** What's missing is (a) a writer that enumerates competitor ids instead of launches, and (b) a `shop_name` column on `rank_observations` (`core/graph_db.py:125-139` has none).

The sharpest evidence of absence is not that `launches` is empty — it's `scheduler.py:500` storing an integer. **A full year of daily sweeps could not reconstruct a single competitor's rank series retroactively.**

Honest constraint: only page one is ever requested. "40 → 8" is observable within the 38-51 `organic_listing_ids`; a listing entering from page 2 looks like it appeared from nowhere.

*Prior art you already own:* `pinterest/products/history.py:44` is a populated rank-over-time table (week | rank | term, ~600 rows) with a `rank_history()` reader, exposed via MCP. It tracks Pinterest leaderboard position, not Etsy SERP position — so it doesn't cover this, but the schema and reader shape are already written and proven.

### M2 — Reading Etsy's own position params off the SERP anchors *(CONFIRMED)*

Probed live on `felt garland`: **24 `ga_search_query` occurrences and 12 `sr_gallery` per SERP.** Grid position is encoded twice — `ref=search_grid-101477-1-N` on the anchor href (N=1..12) and `class="... sr_gallery-1-N ..."` on the card image. (Your recollection was accurate; `sr_gallery-1-1` is a CSS class, not a ref value.)

**Zero code in this repo reads either.** Grepped `ga_search_query`, `sr_gallery`, `ga_order`, `ga_view_type` — no matches outside `.venv`.

Worse, the parser actively discards them: `etsy/api/public/api.py:146` takes the card URL from the hidden add-to-cart form (`meta.get('listing_url')`), which is the **clean** URL. The params live only on the `<a href>`, which is never read.

Why it matters: today position is **inferred from DOM order** — an assumption. These params are Etsy's own statement of (query, page, position) and would let a stored map be *audited* rather than trusted. `ga_search_query` also survives onto the listing page, which is the only mechanism that could attribute an arriving visitor to a keyword.

Two corrections to the naive framing: the card **is** stored today (`etsy/analytics/grid_analytics.py:270` writes a `listing_observations` row per SERP card; `competitor_tracker.py:189` does the same). What is not stored is its **position** — `grid_analytics.py:215` computes `{"rank": i + 1}` for its JSON report and that key is simply not among the kwargs passed to `record_listing` (`core/database.py:493`, which accepts neither keyword nor rank). So this needs a column and a param on the competitor path, not just a parser tweak.

*Useful:* the original parser (`scraper/parser.py`, commit `a180059`) captured the anchor href verbatim, and `data/search/parsed_results.json` in that commit still contains `ref=search_grid-520616-1-1` … `-1-4`. **Use that as an offline fixture instead of re-probing live.**

### M3 — Accidental-keyword detection *(CONFIRMED)*

A listing ranking for a term absent from its title and tags. Nothing exists — grepped for accidental/unclaimed/hidden-keyword variants, only unrelated hits.

**This is the highest-value inference on your entire list.** It isolates a ranking signal Etsy is applying that the seller did not ask for — which is either a gift (an unclaimed term) or proof that something other than tags is driving the rank. Nothing in this repo currently distinguishes "ranks because of its tags" from "ranks despite them".

One correction that makes this **cheaper than it looks**: it does *not* depend on M1 landing. `blueprint_support.material_for_term` / `consensus_for_term` already co-locate both halves inside a single function — they fetch the SERP for a term, take the organic cards, and call `get_listing_data(card["listing_id"])` for each, so `term` and that listing's `tags` are already in scope together at `blueprint_support.py:38` and `:99`. **The join is a few lines inside an existing loop.**

The hard part is judgement, not plumbing, and getting it wrong produces this project's signature failure. `felt garland` vs a listing tagged `felt ball garland` is a substring match, not an accident — it needs `term_join.content_words` set logic, not string containment. And Etsy expands queries server-side, so an apparent accident may be Etsy's synonym layer.

**And the repo currently throws away the one signal that would separate those.** `etsy/api/public/api.py:208-210` reads `click_queries` from the Listzilla blob and truncates: `result['tags'] = tags[:13]`, with the comment *"The first 13 are usually the actual tags, the rest are broadened matches."* **That discarded tail is Etsy's own broadened/expanded query set for the listing.** Keep it in a second field and the disambiguation becomes trivial.

### M4 — The `chart-series-data` truncation bug *(CONFIRMED — live defect, fix this week)*

Probed live with all 11 watched terms: **n=3 → 3 series; n=5 → 3 series; n=11 → 3 series**, and in every case exactly `['felt garland', 'birthday crown', 'felt flower']` — the first three, in order. **The endpoint hard-truncates at 3, positionally and silently.**

Consequences, all live right now:

1. `core/scheduler.py:275` passes all 11 watched terms daily and has only ever stored seasonality for the first three. `keyword_seasonality` holds **6 rows = 3 terms × 2 days**. `mom necklace` — 4th in the list, whose December peak CLAUDE.md/D-45 cites as a headline finding — is **absent from the table**.

2. `mcp_server/tools_etsy.py:95-108` splits an unbounded comma list, never chunks, and tells the agent: *"Terms Etsy cannot size are OMITTED, not zeroed: requested > returned means unmeasured (N-02)."* **That sentence is false.** It presents a server-side cap as Etsy being unable to size the term. An agent will repeat it to you as a finding about the market.

3. There is a fourth silent-loss site the surface audit missed: `etsy/engines/private_comparison.py:11` — `self.keywords = keywords[:3]  # Etsy's API hard limit is 3, even though UI says 2.` It doesn't merely fail to chunk; it **discards terms 4+ before the call** and reports a "comparison" over a truncated set with no note.

4. The conflation has an earlier and more damaging instance in the parser docstring itself, `etsy/api/private/api.py:198-200`: *"Asked for four terms, the response carried three; `linen apron` was simply absent."* Given a measured ceiling of exactly 3, positional — a 4-in/3-out result **is the ceiling**, and `linen apron` sits at exactly the cut. That is almost certainly a truncation artifact recorded as a verified N-02 finding, and it has propagated into `docs/market_map/reference/etsy_private.md:93-95` as fact.

**Fix:** a `MAX_CHART_TERMS = 3` constant next to the probe date, chunking inside `get_chart_series`, merging `term_summaries` and `series` across chunks. Then split the MCP note into two distinct claims: *omitted by Etsy* (unmeasured) vs *never asked* (truncated). Re-probe `linen apron` alone and correct the docstring and the market-map doc. **The scheduler picks up all 11 seasonal curves the same day, for free.**

### M5 — Multi-term operations on the free `analyze` tool *(CONFIRMED)*

`mcp_server/tools_analyze.py:50-56` — the signature is `term: str | None = None`. `winnability`, `intent`, `seasonality`, `saturation`, `freshness` are pure DB reads or pure arithmetic. The tool's own docstring says *"thinking is never rationed."* Yet five terms means five round-trips for numbers already in hand.

Not all seven operations broadcast: `filter_trust` and `discriminate` take no term (see `_NEEDS_TERM`), and `winnability`'s scalar `volume`/`supply` path cannot broadcast across a list and needs an explicit refusal. The pooled reference is not new work — `_intent` already computes `reference_median()` over `db.measured_cvrs()` on **every** call; the task is to hoist it out of the loop and state it once.

### M6 — Source-aware reads of `trend_observations` *(CONFIRMED — reproduced, not inferred)*

The write path is multi-source. **The read path is not.** `core/database.py:101` defines the `trends_latest` view with `MAX(collected_at)` keyed on `(trend_name, country)` and **no source term**. `get_trend` (`:642`) does `.fetchone()` on it.

Reproduced: wrote a `pinterest_moments` row and an `amazon_merch` row for the same trend/country/timestamp. `trends_latest` returned both; `get_trend('christmas')` returned the **amazon** row. `etsy/engines/master_niche_finder.py:279` then stores that result under the key `niche["pinterest"]`.

`find_trend` (`:672`) inherits it. So does `get_trend_history` (`core/database.py:677`), which merges observations from all sources into one chronological series — and `mcp_server/tools_history.py:80-82` calls `find_trend` then feeds the match into `get_trend_history`, inheriting the defect twice. `etsy/ui/app_data.py:176-181` branches `if r["source"] == "pinterest_moments"` and sends **everything else** to the `topics` list, so an Amazon row would render as a Pinterest topic.

Exactly one reader in the entire codebase scopes by source: `etsy/engines/calendar_engine.py:86`, `WHERE source = 'pinterest_moments'`. That proves the column was meant to discriminate; every other reader forgot.

**Impact is latent, not active.** The two live sources have **zero** `trend_name` overlap. `get_trend` is deterministic against current data. It starts returning a wrong number the moment a second source names anything the first already names. That is an argument for fixing it *now* — before rows accumulate under an ambiguous key — not later.

### M7 — Momentum is Pinterest-shaped in its sentinel and its prose *(CONFIRMED)*

`etsy/analytics/momentum.py:38` imports `clamp_change` from `pinterest.endpoints.constants` and applies it at `:61-62`. That function exists to neutralise `100.01`, which is **Pinterest's "10,000%+" display cap**. Applied to a Google Trends or Amazon series where 100.01 could be a real value, it silently blanks a genuine reading.

`:57` sets `basis: "absent_from_pinterest"`; `:58, :74, :77, :80` and `conflicts()` at `:138-147` hardcode "Pinterest" into strings you read verbatim in the terminal. Feeding Amazon data through unchanged produces text asserting Pinterest measured it.

Also: `series_index()` at `:86-98` decodes Pinterest's `{term, growth_rates}` response shape and is the only feeder for `attach()`. A second source needs its own index builder.

*Context:* you already carry a non-Pinterest momentum signal — Etsy `wow_data`, parsed at `etsy/api/private/api.py:105-107` — that several consumers print raw rather than routing through `classify()`. **The wiring target for a generalised classifier already exists and has data waiting for it.**

### M8 — Two hard runtime bugs kill the cart/badge/review-date branch entirely

Not "unused" — **dead code that raises on line one**:

1. `etsy/api/public/listing_api.py:15` passes `cookies=public_api.cookies`. `EtsyPublicAPI` has no `cookies` attribute — `hasattr(EtsyPublicAPI, 'cookies')` is `False`. **AttributeError on the first line of every call.** It is swallowed by the try/except at `etsy/engines/master_listing_analyzer.py:58-62`, so it fails silently as PHASE 3 of a pipeline you think is running.

2. All three call sites of `get_recent_reviews`/`get_review_details` pass `shop_id=` against a `target_shop_id=` signature (`grid_analytics.py:142`, `single_listing_analytics.py:88`, `sentiment_analytics.py:41`). **TypeError.**

Between them these kill `grid_analytics`, `single_listing_analytics`, `sentiment_analytics` and `seo_analytics`. **This is why "in N people's carts" has never reached a database** — the regex at `listing_api.py:44-52` is correct and has simply never executed. There is also no `in_cart` or `favorites` column in `listing_observations` (`core/database.py:217-236`), so a working fetch has nowhere to land.

`etsy/api/public/reviews_api.py:36-115` (`deep_dive_reviews` with `sort_option='Recency'`) returns real date strings — but the *tested* path, `parse_reviews_html`, hardcodes `"date": "Recent"` at `reviews_api.py:224`. So the reachable path has no dates and the path with dates is unreachable. Also worth knowing: `reviews_api.py` POSTs `"should_show_variations": True` at lines 63 and 163 and the parser reads back only text/rating/date — **variation data is requested on every review call and discarded.**

### M9 — Listing age is published and you are not reading it

This is the one where the repo holds a stated belief that is **false for the page it needs**.

`core/database.py:308-312` records: *"Etsy does not publish a creation date."* That is true of the **shop grid**, which is where it was measured. It is **false of the listing page**. `Listed on Aug 29, 2026` sits in the listing page's `og:description` meta tag, and again in the body.

`EtsyPublicAPI.get_listing_data` (`etsy/api/public/api.py:165-214`) **already fetches and 30-day-caches that exact HTML** and reads only breadcrumb, tags and product_type from it. `etsy/api/public/listing_api.py:67-69` even captures the `og:description` string verbatim into `description` — without ever parsing the date out.

Review dates are published the same way, as LD+JSON `datePublished` (read live: 2026-02-21, 2026-03-17, 2026-05-07, 2026-08-01 off a single listing). **Review velocity from actual review dates is one regex away, on HTML you are already paying for**, versus the current approach which differences counts across two of your own sightings ≥12h apart.

`etsy/analytics/competitor_tracker.py:91-115` (`observed_age_days`) is the *honest* half of this — it returns `age_is_bounded: sighting == 'first_sighting'` because only a listing you watched appear has a knowable age. It is correct code built on an assumption that is no longer true.

**Honeymoon detection is not missing infrastructure. It is a missing 20-line parser on a cached page.**

---

## Part 2b — Plausible gaps that did NOT survive (useful signal)

Four things that look like gaps and are not. Do not spend on them.

- **"No table joins keyword and shop_name."** False. `listing_observations` (`core/database.py:217-236`, written by `job_shop_sweep`) stores listing_id | shop_name | matched_term | collected_at, append-only — **605 rows, 331 with a watched term**. The only missing field is position, and its keyword link is title containment rather than SERP rank.

- **"Nothing compares titles across the winners for one keyword."** False — `etsy/generators/listing_generator.py:43-56` does exactly that and emits a gap score. What's actually missing is title **structure** (length, lead words, delimiters, segment order), which is a genuinely smaller and different task. Also unblocked today: card titles come off `parse_search_html` and `organic_listing_ids` has returned 39-51 in rank order since the August fix. Gate any cross-title claim through `card_saturation.wilson` — only ~6-9 organic cards render, so "N of the winners do X" is an n<10 sample.

- **"Free local tables aren't exposed to MCP."** Mostly false. `keyword_competition` is exposed via `analyze(operation="saturation")` (`tools_analyze.py:160`, returning strictly more fields than `build_keywords` would); `keyword_observations` via `history(operation="keyword")` and `cockpit`. `build_keywords`/`build_competition`/`build_snapshot` are **orphans with zero callers since the UI was deleted (D-52)**, not an unbuilt feature. Reviving them is not the fix. The residual real gap is narrow: no single call returns all watched terms at once, so an agent reads `settings_summary` and fans out N calls.

- **"`score_pool` can't be serialised to MCP."** False. `Scored` is a plain dataclass and the SDK's return path (`func_metadata.py:571`, `pydantic_core.to_json(..., fallback=str)`) emits it as a field-named JSON object — measured, not assumed. The NamedTuple warning at `tools_analyze.py:225-226` is a stale comment that no longer reproduces.

  **But that investigation found a real bug next door.** `analyze(operation="discriminate")` (`tools_analyze.py:219-236`) feeds the **unmapped** `build_discovered` pool to `can_discriminate`. `build_discovered` emits `term`/`volume`/`demand_per_listing`; `score_pool` expects `key`/`demand`/… So it currently judges rankability on **`supply` and `momentum` only**, silently ignoring demand, intent and profit. Every "this pool cannot be ranked" verdict it has ever given was computed on two of six dimensions.

- **"The cockpit can't distinguish 'source not consulted' from 'source has no data'."** Mostly false for the cockpit — the distinction is carried in the prose `note`, which `read()` prints. It is a cosmetic issue (not machine-readable), not a structural one, and `etsy/engines/test_cockpit.py:108-110` deliberately pins *"no, for lack of evidence rather than bad evidence"* as intended behaviour. **Do not change the verdict logic.** The one genuine instance is elsewhere: `etsy/analytics/pod_check.py:141-144` collapses three states — `--no-printify` (deliberate exclusion), Printify exception (unreachable), and genuine empty result — into one `basis: "unmeasured"` with a detail string that actively misdescribes the first two.

- **"The cockpit's public supply number is contaminated."** Restated correctly: it's a **display-label bug in one renderer**, not a data problem. `etsy/engines/cockpit.py:290` prints the header "ETSY PUBLIC — competition" over `keyword_observations.competition`, which is written `source="etsy_private"` from `avg_total_listings`. **The number is fine; the provenance claim is false.** `mcp_server/tools_opportunity.py:37-49` already returns `supply_private` and `supply_public` as separate, individually-based fields, and the public count is stored daily as `keyword_competition.total_results`. Fix: relabel the panel into two — "ETSY PRIVATE — market-wide supply & winnability" and "ETSY PUBLIC — page-one competition". **Do not re-attribute `demand_per_listing` to the public count** — private volume ÷ private supply share a population, which is what D-31 intends; substituting the public count mixes denominators. Note `etsy/engines/test_cockpit.py:77` asserts the mislabel, and the fixture sets both values identically at `:53`, so no test can catch the swap. De-duplicate the fixture.

---

## Part 3 — Your batch complaint, answered directly

> *"i get always limited scan for only one keyword... he can not process all that and give me list and comparison."*

**The complaint is real. The cause is not where it looks, and the fix is much smaller than you think.**

### The wire batches asymmetrically. I probed it rather than trusting the constants, and both directions of received wisdom were wrong.

| Endpoint | Real ceiling | What the code believes |
|---|---|---|
| Pinterest `/metrics/` | **≥60**, no positional truncation | `PINTEREST_METRICS_BATCH = 50` (`core/scheduler.py:45`), docstring says "~50" |
| Etsy `chart-series-data` | **exactly 3, positional, silent** | Doc says "pass a LIST", states no maximum; MCP tool never chunks |
| Etsy `results-data` | **1, irreducibly** | correct |

Pinterest probe: requested 60, returned 41, drawn from positions **up to 59**. No positional truncation at all — only the documented dropping of untracked terms. **The 50-cap is self-imposed.**

`results-data` is the real cost driver — one term per call, carrying volume, CVR, price band, wow *and* 20 competitor cards. Mitigated by 7-day TTL caching and no observed quota (D-14). **N sequential calls is a loop, not a blocker.**

### The bottleneck is the tool signatures, not the wire and not the analytics.

Nine MCP tools, every one typed singular: `analyze_keyword(keyword: str)`, `sourcing_profile`, `cheap_competitors`, `deep_dive_keyword(seed)`, `cockpit(term)`, `pod_quote(term)`, `analyze(term)`, `history(subject)`, `keyword_crawl(seed)`.

Behind them sit `score_pool`, `percentile_ranks`, `shortlist`, `explain`, `rank_expanded`, `measure_intent`, `reference_median`, `judge_intent`, `momentum.attach` — **a complete, careful, tested pool-ranking engine that no agent can invoke.** The fan-out loop, the pooled CVR reference, and the single batched Pinterest call all already exist inside `core/scheduler.py::job_discover`.

So: **the comparison machinery is built, the wire mostly cooperates, and the only missing piece is an entry point that accepts a list of terms *you* typed.**

### Smallest change that fixes it

**Add a `compare` operation to an existing grouped tool** (not a new `tools_compare.py` — the surface was just consolidated into grouped ops under D-53, and a single-purpose tool cuts against that).

It needs to write essentially no new analytics. Four pieces of genuinely new code:

1. An entry point accepting an arbitrary term list.
2. A decision on which wire path to spend: N `results-data` calls (CVR + page-one price band, ~1 request/term, 7-day cached) versus one chunked `chart_series` sweep (volume/supply/12-month curve for the whole batch, no CVR). **Offer both — cheap mode and full mode.**
3. A refuse-above-cap guard, following the precedent at `tools_crawl.py:113-125` — never a silent clamp like `private_comparison.py:11`.
4. The table formatter.

Everything else is lifted: `parse_results_data` for the row, `discover.winnability` for the ratio, `measure_intent`/`reference_median`/`judge_intent` for the relative CVR gate, `momentum.attach` for one Pinterest call, `can_discriminate` then `score_pool`/`explain` for ranking and per-dimension justification.

**Cost for a 10-term table: 10 `results-data` calls + 4 chunked `chart_series` calls + 1 Pinterest call ≈ 15 requests.**

Two floors must be stated plainly rather than fudged: `MIN_POOL_SIZE = 3` (`scoring.py:41`) means a 2-term comparison cannot be scored, and `MIN_POOL_FOR_INTENT = 8` (`discover.py:142`) means the intent axis stays `not_checked` below 8 terms. Say so; don't fabricate a ranking.

And **delete `etsy/engines/private_comparison.py`** or make it the seed of the implementation. Right now it is a second, wronger answer to the same question: it truncates to 3 silently, returns `None` from `run()` (the same defect fixed in `master_arbitrage` under D-50), prints instead of returning, computes `ratio = 0` when supply is missing (violating N-02), and ranks by volume÷listings with no CVR — reproducing D-43's exact error.

### Free intermediate win, ship it first

Make `analyze` take a comma list (M5). Zero network, zero session, zero cost, ~15 lines, hoisting `reference_median` out of the loop. **That alone takes most of the sting out of the complaint before `compare` lands.** Comma-splitting is already the house pattern in four places (`tools_pinterest.py:63-64`, `tools_pinterest_research.py:116-117`/`:147`, `tools_etsy.py:96`).

---

## Part 4 — Extensibility verdict

### Supplier pluggability: **small change.** Not a refactor.

The seam exists and is real. `pod_costing.find_options(client, ...)` takes an injected duck-typed client; only two concrete `PrintifyClient()` instantiations exist in non-test code (`pod_check.py:221-222` behind `--no-printify`, and `mcp_server/tools_economics.py:85-87`); everything downstream consumes `PodOption`, not the client. **A second supplier does not require touching the analytics chain.**

Two things block it, both small:

1. The Printify JSON shapes are inlined inside `find_options`. Extract a `SupplierClient` Protocol (`catalog_search`, `providers_for`, `handling_days`) and move the shape-reading into `etsy/api/printify/`.
2. `PodOption` has **no supplier field** — two suppliers' results are indistinguishable at the output. Add one and thread it through `pod_check.lead_time_verdict` and the ceiling.

Everything else is already there. `config/settings.json` `product_profiles` already lets you model two suppliers as two profiles for the **profit-gate** path with zero code change (`hunt.py:84`, `:133`). The catalog-lookup path is what needs the Protocol.

**First thing to change:** fix `pod_check.py:141-144` to emit `not_checked` (the token `discover.py:313` already uses) versus `fetch_failed` (`discover.py:317`) versus `unmeasured`. `render()` at `:265-268` prints only `lt["detail"]`, so no other consumer branches on the field. That is a 10-line change and it is a prerequisite for any second supplier, because with two suppliers "unmeasured" becomes ambiguous across three axes instead of two.

Also add a skip flag to `pod_quote` — `mcp_server/tools_economics.py:88-89` hard-fails on a missing token where the CLI degrades gracefully.

### Trend-source pluggability: **medium refactor, and one part of it is urgent.**

The **storage half is done.** `source` is in the primary key of `trend_observations`, `keyword_observations` and `keyword_competition`. A second writer inserts cleanly today.

The **read half is not, and it fails silently in the wrong direction** — a second source would poison the Pinterest join with no error, and the poisoned value gets stored under the key `niche["pinterest"]`. This is the project's defining failure mode wearing the right label.

**First thing to change, before anything else on this axis:** add `source` to the `trends_latest` partition (`core/database.py:101-107`) and a `source` argument to `get_trend` (`:642`), `find_trend` (`:672`) and `get_trend_history` (`:677`). Then fix the else-branch at `app_data.py:181` that sends any non-`pinterest_moments` row to the `topics` list. `calendar_engine.py:86` is already correct and needs nothing.

This is small-to-medium and costs nothing today because there is zero name overlap between your two live sources. **It gets more expensive the longer you wait**, because rows accumulate under an ambiguous key.

Then, second: parameterise `momentum.py`'s clamp and source label, and write a second `series_index()` for whatever shape the new source returns. `classify()`'s `{mom_change, wow_change}` contract already generalises. Point it at Etsy's own `wow_data` (`etsy/api/private/api.py:105-107`) as the first non-Pinterest consumer — you already have that data and several call sites print it raw.

### Source selection ("private + public only" vs "all three"): **low-to-medium, and less absent than it looks.**

Source selection is **not** absent from the system. It is expressible in four places today: as CLI flags on the offense engines (`hunt --no-calendar` at `hunt.py:201/232`, dropping Pinterest via the optional `calendar_rows=None` at `:24`; `discover --no-intent-check` at `discover.py:492`; `pod_check --no-printify` at `:201`); as a weights dict on the ranker (`score_pool(weights=...)`, which drops an axis and decays `confidence` accordingly — already used two ways at `master_niche_finder.py:161` and `:429`); as `Job.platforms` + `--force` at ingestion (`core/scheduler.py:66/125/557-571`); and on MCP as **separate per-source tools by explicit design** (`tools_etsy.py:1-7`, D-29).

What genuinely doesn't take a source argument is the three **composite** decision entry points: `cockpit.build` (`etsy/engines/cockpit.py:171`), `calendar_engine.build` (`:144`), and the MCP tools wrapping them (`tools_decide.py:14/42/59`). Threading a `sources` set through them is mechanical, maps directly onto `core/preflight.py:103` (`def require(*platforms, ...)`, already varargs and per-platform), and is **not blocked** on the other fixes — the unmeasured-source path already exists and degrades honestly (`cockpit.py:166-168`, `_combine` at `:230`).

One hardcoding to clean up on the way: `core/preflight.py:44` iterates a literal `("etsy", "etsy_private", "pinterest")` in `hygiene()`.

---

## Part 5 — The strategic point

> *"What happens when every seller in your niche has this same system? Opportunity-score chasing is mechanical — the moment it's common, it stops being an edge. Brand and taste are the only parts nobody can copy."*

**You are right about the first half and I think slightly wrong about the second, in a way that matters for what you build next.**

### Where you're right

Opportunity scoring is already commoditised — eRank, Marmalead, Alura, Sale Samurai all ship volume ÷ competition and a colour. If your system's output is "here are ranked keywords by demand-per-listing," you have built a better version of a thing that costs $10/month. And you have built it on the one asset you cannot replace (D-29: the seller session), which is a bad trade for a commodity output.

Worse: your system is *converging* on those tools rather than diverging. `discover` ranks by demand-per-listing. `confirm_intent` adds a relative CVR gate. Both are better-reasoned than the competition, and both are the same **category** of answer.

### Where I'd push back

"Brand and taste are uncopyable" is true and it is also a way of saying *the defensible part isn't software*, which — if you accept it fully — means the correct move is to stop building this repo. I don't think that's right, and here's the distinction that matters:

**What commoditises is the score. What doesn't is the private time series.**

Every competitor tool computes a score from a snapshot anyone can buy. Almost none of them hold a **longitudinal record of who ranked where, when, and what changed.** That data has three properties commodity tools structurally lack:

1. **It cannot be bought.** It only accrues by observing. CLAUDE.md already says this: *"a daily delta needs two readings a day apart and cannot be backfilled."* Every day you don't store the ranked ids is a day of moat you cannot buy back later.
2. **It answers questions a score cannot.** "Which shops dominate which keywords" is a snapshot. "Which shop went 40 → 8 on three related terms in six weeks, and what changed in their tags between those readings" is a *causal* observation about what Etsy's algorithm actually rewards this quarter. Nobody can copy that from a snapshot no matter how good their scoring is.
3. **It compounds against your own taste rather than replacing it.** Accidental-keyword detection (M3) doesn't tell you what to sell — it tells you *what Etsy is willing to give you for free that the incumbent didn't ask for.* That's an input to a judgement call, not a substitute for one.

So the honest framing isn't "scores commoditise, brand doesn't." It's: **scores are a snapshot business and snapshots commoditise. Time series and causal observation are an accrual business and accrual doesn't.** This repo has the accrual infrastructure — `*_observations` tables with `collected_at` in the primary key, an append-only discipline, a running scheduler — and it is currently **not accruing the one series that matters most**, because `scheduler.py:500` writes an integer.

### And the thing your own data is telling you

**0 launches. 0 rows in `launches`. 0 rows in `rank_observations`. LEARN cannot start.**

That is the loudest signal in the whole audit, and it changes the priority order.

You have built an increasingly refined decision system and have made zero decisions with it. Every guard in this codebase exists to stop a wrong number reaching you — but a wrong number that reaches you and is never acted on costs nothing, and a right number that reaches you and is never acted on costs everything. **The system is currently optimising a variable that has never been sampled.**

More concretely: `rank_check` has been running on a 56-hour cadence for weeks, doing nothing. The one instrument you built to measure whether any of this works is idling because there is nothing to measure. And the bias the repo already names (B-04 — LEARN can never discover it was wrong to *reject* a niche) is compounded by a second, worse one: **LEARN has no data at all, so it cannot discover anything.**

The competitor rank series (M1) partially fixes this and is the reason I rank it first. It gives you an outcome dataset **without waiting for your own launches** — every competitor climbing or falling is a labelled example of what Etsy rewards, generated by other people's launches at zero risk to you. That is the single highest-leverage thing available, and it costs zero extra requests because you are already fetching the page.

But it is not a substitute for launching. **Launch something in the next two weeks, even a bad one, even one the system rates 'watching'.** The instrument is built and idle. One launch turns `rank_check` from a no-op into the beginning of a real outcome record, and it turns `verdict_log` and `learn.py` — both built, both unused — from dead code into feedback.

---

## Part 6 — Build order

### Ship this week (all small, all high-leverage)

1. **Persist the ranked SERP.** New `serp_rankings` table (keyword, listing_id, position, shop_name, is_ad, source, observed_at), plus ~15 lines in `job_competition_sweep` (`core/scheduler.py:496-503`) writing `enumerate(cards)` and the `organic_listing_ids` list, and ~10 lines in `job_keyword_sweep` (`:257-262`) writing `data['listings']`. **Zero extra requests — you are already fetching all of it.** One design decision is load-bearing: the ~9 server-rendered cards and the 38-51 `organic_listing_ids` are **different populations with different position semantics.** Merging them into one `position` column is exactly the unit-mixing error `card_saturation` exists to prevent. Store them as separate `source` values. Reuse `find_rank` (`rank_tracker.py:38-70`) for the arithmetic — it already computes organic vs absolute as separate fields.

   *Every day you delay this is a day of time series you cannot backfill.*

2. **Fix the `chart_series` truncation.** `MAX_CHART_TERMS = 3` + chunking in `get_chart_series` (`etsy/api/private/api.py:288`), merging summaries and series. Fix the false note at `tools_etsy.py:104-107`. Re-probe `linen apron` and correct `api.py:198-200` and `docs/market_map/reference/etsy_private.md:93-95`. **This is a live defect producing a plausible wrong number on the MCP surface right now**, and it recovers 8 of your 11 seasonal curves the same day. Kill or rewrite `private_comparison.py:11` in the same commit.

3. **Fix the two AttributeError/TypeError bugs** (`listing_api.py:15`, and the `shop_id=`/`target_shop_id=` mismatch at three call sites). Four analytics modules go from dead to alive. Add `in_cart` and `favorites` columns to `listing_observations`. Remove the swallowing try/except at `master_listing_analyzer.py:58-62` or make it log loudly — it hid this for the project's life.

4. **Parse `Listed on <date>` out of `og:description`** in `get_listing_data` (`etsy/api/public/api.py:165-214`). The HTML is already fetched and 30-day cached. Correct the stale belief at `core/database.py:308-312` — it's true of the shop grid, false of the listing page. **This is honeymoon detection, done.**

5. **`analyze` takes a comma list.** ~15 lines, zero cost, hoist `reference_median` out of the loop, explicit refusal for `winnability`'s scalar path and for `filter_trust`/`discriminate`.

6. **Fix `analyze(operation="discriminate")`** — map `build_discovered`'s `term`/`volume`/`demand_per_listing` onto `score_pool`'s `key`/`demand` contract. It is currently judging rankability on 2 of 6 dimensions.

7. **Add `source` to `trends_latest` and to `get_trend`/`find_trend`/`get_trend_history`.** Costs nothing today, gets more expensive every day, and prevents a silently wrong number the moment you add a second trend source.

8. **Relabel the cockpit's supply panel.** Split into "ETSY PRIVATE — market-wide supply & winnability" and "ETSY PUBLIC — page-one competition". Do **not** re-attribute `demand_per_listing`. Fix `test_cockpit.py:77` and de-duplicate the fixture at `:53`.

### Next (weeks 2–3)

9. **`compare` operation on an existing grouped tool.** Cheap mode (one chunked `chart_series` sweep) and full mode (N `results-data` calls). Reuses seven existing functions. Refuse above a cap, never clamp. State the `MIN_POOL_SIZE=3` and `MIN_POOL_FOR_INTENT=8` floors in the output. **This is the direct answer to your complaint.**

10. **Expose `score_pool` + `explain`** as `analyze(operation="rank")` over any pool. Enforce D-31 at the tool boundary — the ratio ships beside any composite score, so "you cannot rank here" stays checkable.

11. **Competitor rank series.** Once #1 has a week of data, the series falls out of a query. `record_rank` needs a `shop_name` column; nothing else in storage or read changes. Be explicit that page-one-only means a listing entering from page 2 looks like it appeared from nowhere.

12. **Launch something.** Record it via `graph_db.record_launch`. Turns `rank_check`, `verdict_log` and `learn.py` from dead code into a feedback loop.

### Then (weeks 4+)

13. **Accidental-keyword detection.** Add the join inside `blueprint_support.py:38/:99` — both halves are already in scope, no dependency on #1. **First, stop truncating `click_queries` at `api.py:208-210`** — keep the tail as `broadened_queries`; that discarded data is what separates a real accident from Etsy's synonym layer. Use `term_join.content_words` set logic, never containment. **Refuse on partial word-set overlap rather than reporting a find.**

14. **Read `ga_search_query` / `ref=search_grid-N` off the anchors.** One `card.find('a', href=True)` + urlparse in the existing loop, plus a column on the competitor storage path. Add a guard that ref-derived position agrees with DOM order and **refuses when they diverge**. Use the fixture in git history (`data/search/parsed_results.json` at commit `a180059`) rather than re-probing.

15. **Review dates from LD+JSON `datePublished`** on the same cached listing HTML — real review velocity instead of count-differencing across your own sightings.

16. **Supplier Protocol** + `supplier` field on `PodOption`. Prerequisite: the `pod_check.py:141-144` three-state fix.

17. **Title structure mining** (length, lead words, delimiters, segment order) across the winners — small once #1 stores ranked cards. Gate through `card_saturation.wilson`; n<10.

18. **Attributes / variations parsing.** Run `web-surface-mapping` first — this is an unmapped part of the listing page. Note `reviews_api.py:63/163` already requests variations and discards them.

### Do NOT build

- **A new `tools_compare.py` module.** Add an operation to an existing grouped tool. The surface was consolidated under D-53 and the schema budget is a real constraint (3,991 of 6,000 tokens).
- **Reviving `build_keywords` / `build_competition` / `build_snapshot`.** Both tables they read are already exposed with strictly more fields via `analyze(operation="saturation")` and `history(operation="keyword")`. These are orphans from the deleted UI, not an unbuilt feature.
- **Extending `private_comparison.py`.** Delete it or make it the seed. Right now it is a second, wronger answer to the same question — silent `[:3]`, returns `None`, no CVR, `ratio=0` on missing supply.
- **A `not_consulted` basis threaded through the cockpit.** The distinction is already carried in the prose note, `test_cockpit.py:108-110` pins the current verdict as intended, and the one real instance of the conflation is in `pod_check`, where it's a local 10-line fix.
- **Re-attributing `demand_per_listing` to the public listing count.** Private volume ÷ private supply share a population. Substituting the public count mixes denominators — it would look like a correctness fix and be a regression.
- **Anything built on `similar_search_terms` or `market_gap_recommendations`.** Probed empty on three terms; Etsy returns nothing in them.
- **Raising `PINTEREST_METRICS_BATCH` above ~60 without probing.** 60 is measured; above that is untested.
- **More scoring dimensions.** You have six, `confidence` decay, a discrimination guard and a pool-size floor. The marginal dimension is worth less than one launch. **The binding constraint is 0 outcomes, not 6 dimensions.**

---

**One-line summary:** the SEO/ranking data you want is already being fetched daily and reduced to an integer at `core/scheduler.py:500`; the comparison engine you want is already written at `etsy/analytics/scoring.py:132` and simply has no MCP door; the wire batches Pinterest ≥60 and Etsy chart-series at exactly 3 with silent positional truncation that is currently corrupting your seasonal table and lying about it on the MCP surface; supplier pluggability is small and trend-source pluggability is medium with one urgent read-path fix at `core/database.py:101`; and the strategically defensible asset is not the score but the rank time series you are currently deleting once a day — which is why persisting it is item 1 and launching something is item 12 rather than item 40.