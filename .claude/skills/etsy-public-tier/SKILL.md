---
name: etsy-public-tier
description: Use when calling or reasoning about Etsy Public — the SERP, listing pages, competitor shops, tags, saturation, gaps — or when tempted to trust a SERP filter. Enforces that 9 of 12 audited filters silently lie, that page one is ~12 slots of which half are ads, that total_results is an estimate, and that the shop counter is quantised so an unmoved counter is never zero. Trigger on public search, SERP, filters, saturation, gaps, tags, competitor shops, or review velocity.
---

# Etsy Public — unlimited, safe, and full of numbers that lie

A buyer session. Burning one costs a re-login, so **everything about competitors,
listings, tags and SERPs belongs here** (D-29) — never the seller account.

The risk on this tier is not access. It is that several of its numbers are
confidently wrong.

---

## 1. Nine of twelve SERP filters cannot be believed

`config/filter_trust.json` is the live registry; re-audit with
`python -m etsy.analytics.filter_trust`. Current verdict:

| Trusted ✅ | Ignored ❌ (returns the unfiltered total) | Not a subset ❌ | Unstable ⚠️ |
|---|---|---|---|
| `delivery_days` · `gift_wrap` · `is_personalizable` | `best_by_etsy` · `holiday` · `min_rating` | `attr_1` (colour) · `is_digital` | `free_shipping` · `is_discounted` · `is_star_seller` · `locationQuery` |

The evidence is not subtle:

- `min_rating=5` returns listings rated **4.8 and 4.9**, and a count identical to unfiltered
- colour brackets sum to **562%** of supply on one term, 173% on another
- `is_digital=1` returned **231,084** results where unfiltered was **217,213**
- `locationQuery` for one country returned **182%** of the unfiltered total; seven countries summed to **1116%**

**`find_gaps` returns `untrusted_source` rather than a percentage** for the nine
(D-32), and that verdict outranks every other rule. If you are about to divide by
a filtered count, check the registry first.

**Origin share is NOT obtainable from `locationQuery`.** Use
`sourcing.sample_origins()`, which reads each listing's declared origin — it can
also see countries Etsy's filter list omits entirely (it found a Turkish seller).

---

## 2. Page one is ~12 slots, half of them ads

`results_per_page` says 48. About **12 render server-side**, and roughly half are
ads. So:

- **Never divide by "the page"** — the denominator is wrong.
- **DOM order ≠ organic rank.** Use `organic_listing_ids` (39–51 real ranked ids
  per page) for position, not card order.
- A saturation share from ~9 organic cards spans both the "thin" and "crowded"
  thresholds. `card_saturation` attaches a Wilson interval and **withholds** any
  bracket whose bounds straddle a threshold — **0 of 6 does not establish an empty
  bracket; the true share could be 39%** (D-36).

⚠️ **`organic_listing_ids` was empty for the project's entire life** — a regex
proximity constraint that never held, silently, because an empty list is a
plausible value. Fixed 2026-08-20. If a collection is empty, **prove the pattern
matches before believing the data is absent.**

⚠️ **Page 2+ is never requested.** A `felt garland` search reports 20 pages; this
system reads one. Rank beyond page one is *unknown*, not absent — and rank
tracking cannot see a listing that fell to page two.

---

## 3. `total_results` is an ESTIMATE

Identical unfiltered searches returned **217,196 / 217,196 / 217,395**. Never
test it with exact equality — `filter_trust.COUNT_JITTER` allows 2%.

---

## 4. The shop counter is QUANTISED

A shop displaying "25,100" steps by **100**. So a zero delta means *"moved less
than the counter can show"*, never *"sold nothing"*.

`record_shop_observation` returns `below_resolution` plus an **upper bound**
rather than `sales_per_day: 0.0`. A shop delta is the **only measured sales
number in this system** — and it needs two readings a day apart and **cannot be
backfilled**.

⚠️ **The 4580 trap:** `Product.aggregateRating.reviewCount` on a listing page is
*sometimes the shop's total*, not the listing's. A count ≥90% of the shop total
is refused — 7 of 12 tracked listings returned the shop figure. Unrefused, it
manufactures a runaway winner.

---

## 5. What this tier uniquely answers

- **who** ranks (12 cards + 39–51 ranked ids)
- **what they tag** — 13 tags per listing, the blueprint's raw material
- **where they file it** — breadcrumb → category positioning
- **which type** they are — digital/physical/personalized, which decides the
  margin floor (D-22). Read from HTML markers, so a blocked page yields `None`,
  **never "physical"** — pages under 50k bytes are refused for exactly this
- **competitor outcomes over time** — review velocity is the one *unbiased*
  outcome dataset here, since a competitor's launches are independent of our model

`get_listing_data` is the cheapest call in the system: tags + breadcrumb + product
type + `listed_on` + **`broadened_queries`** from **one** fetch, cached 30 days. That
last one is the tail `tags[:13]` used to discard — Etsy's own expanded query set,
which is what tells a genuine accidental keyword from the synonym layer.

⚠️ **`listed_on` RESETS ON AUTO-RENEWAL.** Measured on a listing with **7,700
reviews** whose page said it was listed *that day*. Use `listing_age()`, which returns
an `age_days_lower_bound` and a **three-valued** `honeymoon` — `None` when the review
count contradicts a young date. Never restate it as an age.

⚠️ **The cart count is not on the listing page.** Favourites are (listing-level).
The "In N carts" badge lives behind an add-to-cart, and profile rotation makes a
two-step cart flow impossible without touching the access layer. `get_listing_live`
(never cached, `TTL_LIVE`) carries what is actually there, all **threshold-gated** —
absent means below the display threshold, never zero.

---

## 6. Review velocity is a FLOOR, sales estimates are BOUNDS

Reviews undercount sales, so a listing gaining reviews sells **at least** that
fast. Never restate a floor as a rate.

The "N bought today" badge only renders above a threshold, so ×30 projects the
best day across a month — it is an **upper bound**, clamped against the shop's
measured daily rate where one exists.

---

## Anti-patterns

- Trusting a filter without checking `filter_trust.json`
- Dividing a ~9-card sample by `total_results` — two different units
- Reading card order as rank
- Treating an unmoved shop counter as zero sales
- Testing `total_results` for exact equality
- Calling a page "not ranking" when only page one was read
- Concluding data is absent from an empty collection without proving the pattern matches
