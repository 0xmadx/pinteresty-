# Reference — Etsy Public

**Competition truth.** `etsy/api/public/api.py`. Buyer session — everything about
competitors, unlimited, no seller-account risk. ALL competitor/listing/SERP work MUST
happen here (D-29): a burned buyer session is a re-login, a burned seller account is the
business.

Legend: ✅ verified live · ⚠️ known defect.

---

## `get_public_search(query, filters=None)` — the SERP ✅ 2026-08-16
| Field | Meaning | Verified |
|---|---|---|
| `total_results` | total competing listings | ✅ |
| `cards` | ~12 listing cards (server-rendered; rest hydrate client-side) | ✅ 12 |
| per card | title, price, review_count, shop, is_ad, star_seller | ✅ |

**Payload:** GET `/search?q={query}`. `filters` param exists but the real Etsy filter
names are unverified — **O-6**, read them off Etsy's filter UI before trusting.

### Known defects (do not build on these blind)
- ⚠️ **PS-1:** `results_per_page` says 48 but ~12 render — do NOT divide by "the page".
- ⚠️ **PS-2:** `organic_listing_ids` always empty — no authoritative rank order, and DOM
  order ≠ organic rank (6 of 12 cards were ads).

---

## `get_listing_data(listing_id)` — one listing's guts ✅ 2026-08-16
The cheapest reusable thing (30-day cache). From ONE fetch of the page HTML:

| Field | Meaning |
|---|---|
| `tags` | the listing's **13 tags** — page-one SEO gold |
| `breadcrumb` | its **taxonomy path** (`Paper & Party Supplies > Party Decor > ...`) |
| `product_type` | digital / physical / personalized, from the same HTML (D-22) |

All three from one fetch — no extra calls. Feeds `blueprint`, `taxonomy`, `product_type`.

⚠️ Product type is read from HTML markers (a personalization form field, "Digital
download"). Absence of markers = physical ONLY on a page that rendered; a blocked page
has no markers either, so pages under 50k bytes are refused, not called physical.

---

## `ShopScraper` (`core/shop_scraper.py`) — competitor shops ✅ 2026-08-16
Public tier. Do NOT fall back to `etsy_private` cookies here (was a D-29 violation, fixed).

| method | returns |
|---|---|
| `get_shop_metrics(shop)` | total_sales, total_reviews, active_listings |
| `get_shop_listings(shop, page)` | the shop's inventory: id, title, price, is_ad |
| `get_listing_outcome(id, shop_total_reviews)` | per-listing review count + rating |

⚠️ **The 4580 trap:** `Product.aggregateRating.reviewCount` on a listing page is
SOMETIMES the shop's total, not the listing's. A count ≥90% of the shop total is refused
(would fake a runaway winner). Verified: 7 of 12 shopflowerlane listings returned 4580.

---

## What the public tier UNIQUELY answers
- **who** ranks for a term (the 12–20 SERP cards)
- **what they tag** (13 tags per listing — the blueprint's raw material)
- **where** they file it (breadcrumb → category positioning)
- **which type** the winners are (digital/physical/personalized)
- **competitor outcomes** over time (review velocity = validated winners, the unbiased set)

What it CANNOT answer: real search volume, CVR, or the seasonal cycle → that is private.
