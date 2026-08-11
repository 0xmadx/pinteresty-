# 02 — Data Model

Three principles govern every table:

1. **Guards are columns.** `cvr_source`, `noisy`, `*_capped`, `collected_at` live
   in the schema, not in comments. A guard you can't query is a guard you can't
   trust.
2. **Time-varying tables are append-only.** Never overwrite a value that changes;
   insert a new row with a new `collected_at`. This is Slowly-Changing-Dimension
   Type 2, and it's what makes the LEARN backtest honest.
3. **Gold is derived.** Nothing writes a score or a plan directly; they're computed
   from Silver and rebuildable.

Notation: 🕒 = append-only (temporal), 📌 = current-state (upsert OK), 🔒 =
immutable (write-once).

---

## BRONZE — raw, immutable

Not really tables — files. One record per response, path-keyed.

```
bronze/{source}/{endpoint}/{yyyy}/{mm}/{dd}/{cache_key}.json.gz
```

Each holds: the normalized response, the request that produced it, `fetched_at`,
and the adapter version. Never edited. This is the appeal court and the permanent
recompute cache.

---

## SILVER — clean entities

### `trends` 🕒 (Pinterest signals)

| Column | Type | Guard | Note |
|---|---|---|---|
| term | text | | |
| source | text | | 'pinterest' |
| collected_at | text | 🕒 | freshness; part of the temporal key |
| mom_clamped | real | ✓ | NULL if the 100.01 sentinel was caught |
| mom_capped | int | ✓ | 1 = sentinel was present |
| yoy_clamped | real | ✓ | fallback when mom is capped |
| yoy_capped | int | ✓ | |
| seasonality_score | real | | read-only, never derived |
| noisy | int | ✓ | near-zero-series flag — must survive to scoring |
| intent_ratio | real | | click ÷ save |
| demo_band | text | | dominant age band |

PK `(term, source, collected_at)` — append-only. A `trends_latest` view selects
the newest row per `(term, source)` for current-state reads.

> This corrects `trends_store.py`, which currently upserts and overwrites history.

### Source separation — Pinterest and Etsy never merge into one number early

⚠️ **The single most important modeling rule (bias B-05).** Pinterest and Etsy
measure *different worlds*: Pinterest is discovery interest, Etsy is marketplace
search+purchase. A term can be huge on one and dead on the other ("coquette
aesthetic bedroom" trends on Pinterest, has zero Etsy search). Merging them into a
single score too early hides that disagreement and produces confident nonsense.

**The schema enforces separation** — the `candidates` table carries *per-source*
confirmation and confidence, not just a blended score:

| Column | Meaning |
|---|---|
| `pinterest_signal` | strong / moderate / weak / absent |
| `pinterest_confidence` | high / low (low if `noisy` or capped) |
| `etsy_demand_signal` | strong / moderate / weak / absent |
| `etsy_confidence` | high / low (low if `cvr_source=default`) |
| `sources_agree` | bool — do both point the same way? |
| `combined_score` | the blend — **only trusted when `sources_agree` or both are confirmed** |
| `verdict_reason` | e.g. "pinterest strong / etsy weak → may not convert" |

**Rule:** `combined_score` is never presented without its two source signals
beside it. A score built on one strong source while the other is weak or absent is
flagged, never shown as a clean number. The scorer already gates on confidence;
this makes the *source-level* gate explicit in the schema so the UI and the LEARN
loop can both read it.

### `keywords` 🕒 (Etsy Private demand)

term, collected_at 🕒, search_volume, cvr, **cvr_source** (`private`/`default`),
price_median_paid, **demand_source**.

### `listings` 🕒 (Etsy Public — competitor listings)

listing_id, keyword, collected_at 🕒, price, est_sales, **sales_source**
(`daily_delta`/`ratio`/`badge`), est_views, velocity, favorites, in_cart_lower
(sentinel-clamped lower bound), scarcity_lower, seo_tags (json), top_flaws,
shop_name, **collected_at**.

### `shops` 🕒 (Etsy shop intelligence)

shop_name, collected_at 🕒, total_sales, total_reviews, age_months,
country, sales_per_month (derived col), **the daily delta comes from diffing rows**
— which append-only makes trivial.

### `rank_observations` 🔒 (OPERATE — the loop's ground truth)

| Column | Guard | Note |
|---|---|---|
| listing_id | | yours or a tracked competitor |
| keyword | | |
| country | | never compare across countries |
| observed_at | 🔒 | write-once |
| rank_absolute | | ads included — what a human sees |
| rank_organic | | ads excluded — whether SEO works |
| page | | the cliff |
| promoted_above | | ad load |
| is_own | | |

Never updated. Rolling medians are computed at read time.

### `reviews` 🕒

listing_id, review_id 🔒, rating, text, review_date, collected_at.

---

## GOLD — derived, disposable

### `candidates` 📌 (assembled, pre-score)

keyword, product_type, demand, momentum, intent, supply, serp_strength, margin,
cvr_source, noisy, **freshness_floor** (oldest collected_at of all inputs),
built_at. Rebuildable from Silver.

### `scores` 📌

keyword, product_type, score, confidence, reasons (json), contributions (json),
percentiles (json), **pool_id**, **pool_size**, weights_version, scored_at.

> `pool_id`/`pool_size` are mandatory: a percentile score means nothing without
> the pool it was ranked in. #1 of 5 and #1 of 500 look identical otherwise.

### `launch_plans` 📌

keyword, product_type, platform_recommendation, gap_bracket, list_by_date,
timing_basis, seo_title, seo_tags (json), flaws_to_beat (json), built_at.

### `alerts` 📌

week, kind (`entered`/`spike`/`seasonality_cross`/…), term, severity, payload.

---

## LEARN — immutable outcomes

### `launches` 🔒 (the machine's report card AND the training set)

**The whole feature vector is snapshotted here as literal values — never foreign
keys to rows that will change.** This is the single most important schema decision
for both LEARN and any future AI model.

| Group | Columns |
|---|---|
| identity | launch_id 🔒, keyword, listing_id, country, product_type |
| **predicted (frozen)** | score, confidence, weights_version, pool_id, **demand, momentum, intent, supply, serp_strength, margin** (the literal values used), predicted_sales_monthly, predicted_profit_monthly, gap_bracket, list_by_date, timing_basis, **freshness_floor** |
| **actual** | first_sale_at, sales_30d, sales_60d, sales_90d, profit_90d, best_rank_organic_90d, **traffic_pinterest_pct**, outcome_class, failure_mode |

Predicted columns are write-once at launch. Actual columns fill in over 90 days.
The pairing of frozen-input to real-outcome is the training example.

---

## The temporal rule, stated once

> Any value that changes over time is stored append-only with `collected_at`.
> Current-state reads use a `_latest` view. Predictions snapshot literal inputs.
> Nothing that a backtest or a model will ever read is allowed to be overwritten.

This is the rule that cannot be retrofitted. Everything else in this data model
can be added later; temporal correctness must be right from the first row.

---

## Storage engines per table

| Table group | Engine | Why |
|---|---|---|
| Bronze | gzipped JSON files | immutable, no schema to migrate |
| Silver, Gold, Learn | SQLite | embedded, ACID, you already use it |
| analytical reads | DuckDB over the SQLite/Parquet | columnar, in-place, built for this |
| series | existing series_store | already correct |
| graph edges | SQLite edges table | thousands of nodes = a SQL join |

See `05_stack.md` for the full rationale and the anti-choices.
