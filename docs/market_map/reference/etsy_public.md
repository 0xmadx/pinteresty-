# Reference — Etsy Public

**Competition truth.** `etsy/api/public/api.py`. Buyer session — everything about
competitors, unlimited, no seller-account risk. ALL competitor/listing/SERP work MUST
happen here (D-29): a burned buyer session is a re-login, a burned seller account is the
business.

Legend: ✅ verified live · ⚠️ known defect · ❌ available, not called.

---

## `get_public_search(query, filters=None)` — the SERP ✅ re-verified 2026-08-27
`GET /search?q={query}&explicit=1&{filters}` — `filters` is a raw passthrough
(`params.update(filters)`), so **any** Etsy search parameter works; the code imposes
no whitelist.

| Field | Meaning | Verified |
|---|---|---|
| `total_results` | `organic_listings_count` — total competing listings | ✅ |
| `results_per_page` | reports 48 | ⚠️ **PS-1**: only ~12 render server-side; do not divide by "the page" |
| `current_page` / `total_pages` | `initial_current_page` / `initial_total_pages` | ✅ present, never paged past 1 (see gap below) |
| `organic_listing_ids` | the ranked id list, full page order | ✅ **fixed 2026-08-20** — see below |
| `cards` | ~12 listing cards (server-rendered; rest hydrate client-side) | ✅ |
| per card | `listing_id`, `title`, `url`, `shop_id`, `shop_name`, `is_ad`, `shop_years_on_etsy`, `rating`, `review_count`, `price`, `original_price`, `percent_discount`, `free_shipping`, `star_seller`, `image_url` | ✅ all parsed |

### `organic_listing_ids` — was ALWAYS empty, now real
Historical bug (`PS-2`), fixed 2026-08-20: the old regex required `"result_count"`
within 200 characters of the array as a proximity heuristic. The real neighbouring
keys are `bucket_id`/`user_id`/`is_async` — nowhere near. **Every page for the
project's life returned `[]`, silently**, because an empty list is a plausible value
for a page with no results. The array itself is now the identifying feature (taking
the **longest** `"listing_ids": [...]` match distinguishes the page-level ranking
from a per-card analytics payload's single id). Now returns 39–51 ranked ids per
page — this is what unblocked rank tracking.

⚠️ DOM order ≠ organic rank — 6 of 12 cards were ads on one measured page. Use
`organic_listing_ids` for rank, not card position.

---

## The 12 known filter parameters — ground truth is `config/filter_trust.json`, not this doc

This table is a snapshot; **`config/filter_trust.json` is the live source of truth**,
re-audited by `python -m etsy.analytics.filter_trust`. As of its last run: **9 of 12
cannot be believed.**

| Filter | Status | Evidence |
|---|---|---|
| `delivery_days` | ✅ trusted | subset on every probe |
| `gift_wrap` | ✅ trusted | subset on every probe |
| `is_personalizable` | ✅ trusted | subset on every probe |
| `best_by_etsy` | ❌ ignored | every value = the unfiltered total |
| `holiday` | ❌ ignored | `halloween` and `christmas` both = the unfiltered total |
| `min_rating` | ❌ ignored | `min_rating=5` returns listings rated 4.8/4.9, count = unfiltered total |
| `attr_1` (colour) | ❌ not a subset | 7 colour buckets summed to **173%** and **562%** of the unfiltered total on two different terms |
| `is_digital` | ❌ not a subset | `is_digital=1` returned MORE digital-tagged results (231,084) than the unfiltered total (217,213) |
| `free_shipping` | ⚠️ unstable | passes on some queries, exceeds the unfiltered total by 3% on another |
| `is_discounted` | ⚠️ unstable | exceeds the unfiltered total by 85% on one query |
| `is_star_seller` | ⚠️ unstable | passes on some, silently ignored (= unfiltered total) on others |
| `locationQuery` | ⚠️ unstable | one country code alone returned **182%** of the unfiltered total; origin share is NOT obtainable from this filter — use `sourcing.sample_origins()` instead, which reads each listing's declared origin |

`find_gaps()` enforces this registry — `untrusted_source` outranks every other
verdict (D-32). Any code asking one of the 9 untrustworthy filters for a saturation
claim gets refused, not a wrong number.

**Beyond these 12, the real parameter surface is unknown and unverified** —
`filters` passes anything straight to the URL. `min`/`max` (price band, feeds the
profit gate) and `attr_2`/`attr_3` (size/material, if colour is `attr_1`) are
plausible names never confirmed against Etsy's own filter UI (O-6).

---

## Etsy public pagination — the biggest structural gap, still unfixed as of 2026-08-27

`total_pages` is read and stored; **nothing ever requests `page=2`.** Every search
this system runs reads page 1 only (~12 server-rendered cards out of Etsy's stated
48/page, out of `total_results` that can run into hundreds of thousands). This caps:
- the survivor bound sample at ~12 listings
- competitor analysis at whoever ranks on page 1
- rank tracking, which cannot see a listing that ranks 13th or later — it reads as
  "not found," indistinguishable from "not ranking at all"

`listing_sample.py` works around this differently (opening individual listing pages,
`LISTING_SAMPLE` default 0, operator's call per request cost — D-37), but that is a
sample of specific listings, not a second page of the ranked SERP itself. This gap
predates this refresh and nothing in the current codebase closes it; flagged here as
confirmed-still-open, not newly found.

---

## `get_listing_data(listing_id)` — one listing's guts ✅ re-verified 2026-08-27
`GET /listing/{listing_id}` — the cheapest reusable thing (30-day cache). From ONE
fetch of the page HTML:

| Field | Meaning |
|---|---|
| `tags` | the listing's **13 tags** — page-one SEO gold (`Listzilla_ApiSpecs_Tags_Landing` JSON block) |
| `breadcrumb` | its **taxonomy path**, from the page's `BreadcrumbList` LD+JSON |
| `product_type` | digital / physical / personalized, from the same HTML (D-22) |

All three from one fetch — no extra calls. Feeds `blueprint`, `taxonomy`, `product_type`.

⚠️ Product type is read from HTML markers (a personalization form field, "Digital
download" text). Absence of markers = physical ONLY on a page that actually
rendered; a blocked/short page has no markers either, so pages under 50k bytes are
refused rather than called physical.

---

## `ShopScraper` (`core/shop_scraper.py`) — competitor shops ✅ 2026-08-16, unchanged
Public tier. Do NOT fall back to `etsy_private` cookies here (was a D-29 violation, fixed).

| method | returns |
|---|---|
| `get_shop_metrics(shop)` | total_sales, total_reviews, active_listings |
| `get_shop_listings(shop, page)` | the shop's inventory: id, title, price, is_ad |
| `get_listing_outcome(id, shop_total_reviews)` | per-listing review count + rating |

⚠️ **The 4580 trap:** `Product.aggregateRating.reviewCount` on a listing page is
SOMETIMES the shop's total, not the listing's. A count ≥90% of the shop total is
refused (would fake a runaway winner). Verified: 7 of 12 shopflowerlane listings
returned 4580.

⚠️ **Etsy's shop counter is quantised** — a shop displaying "25,100" steps by 100.
A zero delta between readings means "moved less than the counter can show," not
"sold nothing." `record_shop_observation` returns `below_resolution` + an upper
bound rather than `sales_per_day: 0.0`.

---

## What the public tier UNIQUELY answers
- **who** ranks for a term (12 SERP cards, now with a real ranked id list of 39–51)
- **what they tag** (13 tags per listing — the blueprint's raw material)
- **where** they file it (breadcrumb → category positioning)
- **which type** the winners are (digital/physical/personalized)
- **competitor outcomes** over time (review velocity = validated winners, the unbiased set)

What it CANNOT answer: real search volume, CVR, or the seasonal cycle → that is private.
