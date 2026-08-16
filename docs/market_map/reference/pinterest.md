# Reference — Pinterest

The audience layer. `pinterest/endpoints/api.py`. Reads cookies from the Redis vault
(fixed 2026-08-15). Weekly data — sampling faster re-reads the same numbers.

Legend: ✅ verified live · ⚠️ wired, returned empty/None · ❓ never probed · ❌ dead.

---

## The 3 UI pages → endpoints

Pinterest Trends has three pages the operator navigates:

| Page | Shows | Endpoint |
|---|---|---|
| **Trends overview** | "Trends in the Spotlight" (5 curated cards) + a general table | `featured_topics` (cards) + `top_trends` (table) |
| **Search trends** | trending search keywords | `top_trends` |
| **Shopping trends** | trending product categories | `top_categories` |

**Decision:** from the overview we take only the Spotlight cards; its general table
duplicates the Search-trends page. See `analysis/pinterest.md`.

---

## `top_trends(preset, ...)` — Search trends ✅ 2026-08-16
`GET /top_trends_filtered/`. Up to 100 rising keywords per call.

### The preset is the master switch — `trendsPreset` 1–4, same page four answers
| preset | trendsPreset | ranks by | live example | use for |
|---|---|---|---|---|
| `top_monthly` | 1 | volume this month | nails, hairstyles | biggest terms now |
| `top_yearly` | 2 | volume this year | nails, wallpaper | evergreen giants |
| `growing` | 3 | velocity | isopod wants, sterling point tv | breakouts (noisy) |
| **`seasonal`** | 4 | seasonal spike NOW | first day of school prayer, august pedicure colors | **timing** |

### Row (9 fields)
`term` · `mom_change`/`yoy_change`/`wow_change` (each `{index, value}`) · `seasonality_score`
(0–1) · `searchCount` + `normalizedCount` (volume) · `affinity` · `reverseRank`.

### Parameters — the FIVE UI filters, all verified
| UI filter | param | format | notes |
|---|---|---|---|
| — | `trendsPreset` | 1–4 | the master switch |
| — | `numTermsToReturn` | 1–100 | UI sends 50; **100 = free 2× breadth**, first 50 identical, 101→400 |
| — | `lookbackWindow` | 1/2/3/5 | **cosmetic** — byte-identical rows |
| **Interest** | `l1interests` | category id, comma-joined | Beauty → nail/hair terms |
| **Age** | `ageBuckets` | **NUMERIC index** (18-24 = [2,3]) | ⚠️ label "25-34" → 500; code maps it now |
| **Gender** | `gender` | **NUMERIC** 0/1/2 | ⚠️ "female" → 500; code maps it. `male`→wallpaper/anime, `female`→nails/outfits — strong split |
| **Moments** | `moments` | slug: lowercase, no apostrophes, spaces kept, comma-joined | "Mother's Day"→`mothers day`. **Same vocabulary as `moments_calendar`** |
| **Include keyword** | `keywordsToInclude` | free text, comma-joined | `costume` → costume terms |

⚠️ **The recurring trap:** age/gender want numbers; the string form 500s and looks like
"unsupported". It is supported. Always probe the format before concluding.

---

## `featured_topics(interests, country)` — Trends in the Spotlight ✅ 2026-08-16
`GET /ads/v4/trends/topics/featured/{country}/SAVE`. Exactly 5 curated topics, SAVE-ranked.

- Region: US / CA / GB+IE only. `interests`: exactly one id, the Fashion triple, or None.
- Per topic: `name`, `description`, `pct_growth_mom` (⚠️ **UI ×100**: raw 3 = "300%"),
  `related_search_trends` (**4+ keyword seeds**), `interests`, `time_series`, `pins`.
- Verified exact match: Back to School Nail Designs, Senior Spirit Jeans, Starbucks Drink
  Orders, Senior Picture Ideas, Pottery Painting Ideas.
- SAVE = aspiration, not purchase. Pair with `top_categories` OUTBOUND_CLICK for intent.

---

## `top_categories(event, country)` — Shopping trends ✅ 2026-08-16
`OUTBOUND_CLICK` → 37 categories · `SAVE` → 20 · `ENGAGEMENT` → 35. **The intent signal.**

Per category: `summary` (`saves`/`engagement`/`outbound`, each with `percent_growth`) ·
`related_search_trends` (**25 terms**) · `product_category` · `parent_product_categories`.

⚠️ Not yet deep-probed for the per-category drill (top_products, etsy_competitors).

---

## Keyword expansion (Pinterest's recursive tree)
| endpoint | returns | verified |
|---|---|---|
| `related_terms(term)` | ~5 related terms, each a `counts` momentum series | ✅ mom necklace → silver/charm/cross necklace |
| `prefix_match(query)` | ~10 autocomplete completions (string, noisy) | ✅ "mom neck" → neck tattoo, mom outfits |

---

## Timing & audience
| endpoint | returns | verified |
|---|---|---|
| `moments_calendar(country)` | 13 moments, `takeoff_ms`/`peak_ms`/`phase` (string epochs) | ✅ |
| `demographics(terms)` | `{term_distributions: {}}` | ⚠️ empty on "mom necklace" — unproven |
| `metrics(terms, days)` | momentum series | ⚠️ None on "mom necklace" — inconsistent |
| `split_forecast` / `predicted_days` | 91-day forecast | ❓ never probed |

---

## Never-probed surface ❓
`category_metrics`, `category_demographics`, `top_products`, `etsy_competitors`
(Pinterest's view of Etsy competitors per category — worth probing),
`editorial_content` (narrative layer, no metrics), `product_categories`. Assume nothing.
