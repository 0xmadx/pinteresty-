# Reference — Pinterest

The audience layer. `pinterest/endpoints/api.py`. Reads cookies from the Redis vault
(fixed 2026-08-15). Weekly data — sampling faster re-reads the same numbers.

Legend: ✅ verified live · ⚠️ wired, returned empty/None · ❓ never probed · ❌ dead.

---

## Navigation map — every URL → endpoints ✅ re-verified 2026-08-16

**Five** routable pages, not three (the two drilldowns were missed until 2026-08-16).
Every one is directly addressable — no click-path required except where noted:

| # | URL | Shows | Endpoints |
|---|---|---|---|
| 1 | `/` | Spotlight (5 curated cards) · Moments calendar · Shopping preview | `featured_topics` · `moment/available/{country}` · `top_categories` |
| 2 | `/search/` | trending keyword table (4 preset tabs) | `top_trends_filtered` + batched `/metrics/` |
| 3 | `/detail/?terms={term}` | single-keyword drilldown: chart · related chips · demographics · pins | `/metrics/` · `/demographics/` |
| 4 | `/shopping/` | trending category table (`?tab=trending`) + full taxonomy list (`?tab=all`) | `product_categories/top/{c}` · `.../metrics/{c}` · `product_categories` |
| 5 | `/shopping/{cat_id}?country=US` | per-category drilldown: top products · performance · demographics · related | `top_products` · `.../metrics/{c}` · `.../demographics/{c}` |

⚠️ **`parentProductCategory` is OPTIONAL on route #5** — `/shopping/1057?country=US`
renders the full page identically (✅ 2026-08-16). The UI includes it when you arrive
by clicking a row, but the page does not need it; `{cat_id}` alone is sufficient.

**Route construction — both drilldowns are reachable without crawling the UI:**
- **#3** — `?terms={term}` accepts any term string (comma-join for multi-term compare).
  Also reachable by typing in the search box + Enter, or clicking a `/search/` row.
- **#5** — both ids come from the single cached `product_categories` call; see its
  section below. Renders correctly on a cold direct load.

⚠️ Direct-URL navigation is fine for #5 but the client-side router did **not** hydrate
state on a cold `/detail/` load in one test — reaching #3 via the search box is the
reliable path when driving a browser.

**Decision:** from the overview (#1) we take only the Spotlight cards; its general table
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

### UI column → raw field, exact transform ✅ 2026-08-16
The table (`Keywords · Search volume · Weekly change · Monthly change · Yearly change`)
maps like this — verified against raw `/top_trends_filtered/` response, not inferred:

| UI column | raw field | transform |
|---|---|---|
| Keywords | `term` | direct |
| Search volume (bar) | `normalizedCount` (== `searchCount` when unfiltered — untested whether they diverge under an Age/Gender filter) | direct, bar-scaled to the visible page's max |
| Weekly change | `wow_change.value` | **× 100**, e.g. raw `80` → "8,000%" |
| Monthly change | `mom_change.value` | × 100, same as weekly |
| Yearly change | `yoy_change.value` | × 100, same as weekly |

**Display is capped at "10,000%+"**, not the literal number: raw `100.01` (×100 =
10,001%) and any larger raw value both render as "10,000%+". Do not read "10,000%+"
as a specific number — it's a ceiling label, same discipline as the featured-topics
×100 note above. This confirms and extends that note: the ×100 scaling is not a
one-off on `featured_topics`, it is the standard convention for every `*_change`
field in this API, wherever it appears.

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

### `ageBuckets` enum, confirmed 2026-08-16
`18-24=[2,3]` (the only UI bucket that maps to TWO server buckets) · `25-34=4` ·
`35-44=5` · `45-49=6` · `50-54=7`. `55-64`/`65+` not tested — ❓ assume `8`/`9`.

### `endDate` — real historical query, not cosmetic ✅ 2026-08-16
`endDate=YYYY-MM-DD` on `top_trends_filtered`. Backdating actually recomputes
weekly/monthly/yearly change (verified: "nails" weekly change changed 2%→7% between
end dates 2 days apart) — this is the lever for taking two readings apart in time,
not just a display filter.

### The table's sparklines are ONE batched call, not one per row ✅ 2026-08-16
Every visible row's mini-sparkline comes from a single
`/metrics/?terms=term1,term2,...&normalize_against_group=false&days=90&aggregation=2`
call listing every term on screen (comma-joined, ~50 terms). Free breadth — do not
call per-keyword when a batch is already on screen.

---

## `/detail/` page — single-keyword drilldown ✅ 2026-08-16
Reached by clicking any keyword row in `top_trends_filtered`. Not a resource call
itself — it's a client route: `/detail/?country=US&terms={term}&dateRange=365D&
ageDetailsPage={bucket}&genderDetailsPage=&aggregationLevel=2`. Three real sections:

1. **Interest over time** — `GET /metrics/?terms={term}&country=US&end_date=...&
   age_bucket={n}&days={365|90|30}&aggregation=2&normalize_against_group=true&
   predicted_days=0`. `normalize_against_group=true` is what turns this into a
   Google-Trends-style 0–100 index for the single term (vs `false` for the batched
   table sparklines above — same endpoint, different meaning by this one flag).
2. **Demographics (age + gender bars)** — `GET /demographics/?terms={term}&country=US&
   end_date=...&days=365`. **Corrects the earlier ⚠️ note below**: demographics is
   NOT dead — it returned empty on the low-volume probe term `mom necklace`, but is
   fully populated on a high-volume term (`nails`: 49% age 18-24, 92% female). Treat
   emptiness as a volume-threshold effect, not a broken endpoint — retest before
   writing off a specific keyword's demographics as unavailable.
3. **Pin gallery** — thumbnails only, no metric equivalent. Visual/qualitative signal
   per the skill's "what is shown as a shape/image, not a number" check.

### Date range — always use 2 years, not the 90/365-day defaults
The chart's own picker offers **3mo / 6mo / 1yr / 2yr** (`dateRange=90D/180D/365D/730D`
→ `days=` on `/metrics/`). Default page-load is 365D. **Use 730D (2 years) —
it's the only range that reveals a full second seasonal cycle**, needed to confirm a
peak repeats rather than being a one-off (same discipline as Etsy's `chart-series`,
see `analysis/combinations.md` JOIN 1).

### Related trends — compare up to N keywords on one chart, one call ✅ 2026-08-16
Below the chart: `Related trends — Add related keywords to the graph to compare
trends`, 5 chips (e.g. for "nails": `nails 2026`, `summer nails 2026`, `nail designs`,
`classy nails`, `back to school nails`), each with its own mini-sparkline preview.
Clicking a chip's `+` adds that term to the SAME comma-joined `terms=` list on BOTH
`/metrics/` and `/demographics/` — one call now returns overlaid indexed trend lines
AND age/gender comparison for every term selected, not one call per term:
```
GET /metrics/?terms=nails,nail+designs&country=US&end_date=...&age_bucket=7&days=730&aggregation=2&normalize_against_group=true&predicted_days=0
GET /demographics/?terms=nails,nail+designs&country=US&end_date=...&days=730
```
**The chip set is dynamic, not fixed per keyword** — after adding "nail designs", the
5 chips refreshed to a new set (`summer nail inspo 2026`, `nails 2026`, `summer nails
2026`, `classy nails`, `nail design ideas`), recomputed against the current
comparison set. This is a free, no-extra-account-cost way to build a short list of
audience-and-trend-compatible variants for a single candidate term before spending
the Etsy private account on any of them (D-29 discipline, applied on the Pinterest
side).

### "Predict the future" — the 91-day forecast toggle ✅ 2026-08-16
Button above the chart, **ON by default** when reached via Enter-search (not via a
row click from `top_trends_filtered`, which lands with it off). Toggling adds/removes
one param on the same `/metrics/` call:
```
predicted_days=91   → dashed forecast line + shaded confidence band appended to the chart
predicted_days=0    → historical only
```
This is the doc's previously-❓ `split_forecast`/`predicted_days` feature — it works,
same endpoint as everything else on this page, single boolean-ish switch. Worth
wiring into the calendar build (D-20): a 91-day-ahead confidence band is a second,
independent forecast to sanity-check against Etsy's `chart-series` cycle (JOIN 1).

**The button itself is conditional, page layout is not** — verified 2026-08-16 on
"isopod wants" (a brand-new breakout: flat-zero interest for ~12 months, one vertical
spike in the last few weeks). No "Predict the future" button rendered at all — but
Related trends and Demographics were both still present and fully populated (65%
concentrated in one age bucket). Read as a **data-sufficiency gate on the forecast
specifically**: a term with no prior shape to extrapolate from doesn't get offered a
forecast, but every other section on the page is independent of that and renders off
whatever data exists. Don't infer "forecast missing" → "endpoint broken" for a term;
check whether the term has enough history first.

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

### Real endpoint chain, verified 2026-08-16 (deep-probe done, was ⚠️)
Four separate calls build this page, not one:
```
GET /ads/v4/trends/shopping/product_categories                              — full category TREE (see below), no params
GET /ads/v4/trends/shopping/product_categories/recommendations/{advertiser_id}/US  — personalized (ignore, seller-account-specific)
GET /ads/v4/trends/shopping/product_categories/top/US                       — THE ranked table
GET /ads/v4/trends/shopping/product_categories/metrics/US                   — sparkline + forecast per category
```

**`top/US` params** (POST-style JSON body via the `ApiResource/get` wrapper):
`event` (`OUTBOUND_CLICK`/`ENGAGEMENT`/`SAVE`) · `ranking_method: "GROWTH"` ·
`end_date` · `age_bucket: [string enum, see below]` · `gender: []` ·
`parent_product_categories: [id,...]` (the "Top vertical" filter) · `limit: 20` ·
`order_by: "PCT_CHANGE_MOM"` · `order: "DESC"`.

**`metrics/US` params**: `product_category_ids: [...]` (batched, same "one call for every
visible row" pattern as `top_trends_filtered`) · `event` · `end_date` · `days: 60` ·
`age_bucket` · `gender` · **`predicted_days: 28`** — a shorter forecast horizon than
the Search-trends detail page's 91 days. Same forecast icon shown in the `Trend`
column as the "Predict the future" button; this page's forecast is just always-on,
no toggle.

### ⚠️ Age filter uses a DIFFERENT wire format than Search trends — do not reuse the mapping
Shopping trends sends **string enums**: `ageBucket=AGE_25_34` (UI URL) →
`age_bucket: ["AGE_25_34"]` (API body). Unfiltered default is `["AGE_ALL"]`. This is
NOT the numeric `ageBuckets=4` scheme documented above for `top_trends_filtered` —
same UI concept ("Age: 25-34"), two unrelated wire representations depending on which
Pinterest subsystem you're calling. **Any code mapping age buckets must be scoped
per-endpoint, never assumed global.**

### `Top vertical` filter — only 3 verticals exist, not a general category filter
`Fashion=1181` · `Home decor=1250` · `Beauty=1042` → `parent_product_categories=[id]`.
Checkbox, multi-select, comma-joined in the URL if more than one chosen. This is the
whole vertical taxonomy exposed here — not every Pinterest category, just these three
top-level groupings.

### `Ranked by` — UI label → `event`, table headers relabel live
| UI label | `event` | UI column headers become |
|---|---|---|
| Outbound clicks | `OUTBOUND_CLICK` | "Outbound clicks growth" / "Outbound clicks volume" |
| Engagement | `ENGAGEMENT` | "Engagement growth" / "Engagement volume" |
| Pin saves | `SAVE` | "Pin saves growth" / "Pin saves volume" |

Confirms and extends the existing `OUTBOUND_CLICK`/`SAVE`/`ENGAGEMENT` values above —
now tied to their exact UI labels and confirmed the whole table re-labels itself, not
just the ranking.

## `/shopping/{category_id}/` — per-category drilldown ✅ 2026-08-16
Reached by clicking a category row, OR direct-linked with no prior navigation —
`/shopping/{category_id}/?parentProductCategory={parent_id}&country=US` renders
correctly cold. Both ids come free from the single `product_categories()` taxonomy
call (`friendly_name`, `parent_product_category_id`, `children`) — build a
`name → (id, parent_id)` lookup locally rather than fetching per-name; e.g. "Beach
towels" → `id=1039, parent=1036`, confirmed live. Resolves the doc's old "❓ not yet
deep-probed" note. Four things on this page, not three:

0. **Header** — category name, full breadcrumb (`Home decor > Bathroom accessories`
   — level-1 vertical down to this category), and a fixed **"Key metric changes in
   the past 30 days"** line showing all three events at once (Outbound clicks,
   Engagement, Pin saves, each with a ↑/↓ %) — independent of the Performance
   section's own date-range selector below it.

   **Source: `demographics/US` → `summaries`, ×100** — not a separate endpoint
   (✅ field-matched live 2026-08-16, category 1039 Beach towels):

   | UI header | API field | raw |
   |---|---|---|
   | Outbound clicks ↓24% | `summaries[0].outbound_clicks.percent_growth` | `-0.24` |
   | Engagement ↓19% | `summaries[0].engagement.percent_growth` | `-0.19` |
   | Pin saves ↓17% | `summaries[0].saves.percent_growth` | `-0.17` |

   Consequence: **if `demographics/US` 500s, the whole header silently disappears**
   rather than erroring — observed live. See the defects section below.

   **Exact definition, from the UI's own tooltip** (✅ read live 2026-08-16):
   *"Change in outbound clicks over the last 30 days, vs. the previous 30-day
   period"* — a **rolling 30-vs-previous-30** comparison, NOT year-over-year and not
   the `mom_change` field from `top_trends_filtered`. Note `lookback: 2` accompanies
   each block, consistent with "2 periods compared". Do not conflate with `mom_change`
   when joining these surfaces.

1. **Top products on Pinterest** — **two** `top_products` calls fire on page load,
   both 200:
   ```
   GET /ads/v4/trends/shopping/product_categories/top_products
       {product_category_id, region, event}                    ← the one to use
   GET /ads/v4/trends/shopping/product_categories/top_products/{advertiser_id}/{category_id}
       {region, event, limit:50}                               ← personalized, seller-account-scoped; ignore
   ```
   Row fields: `pin_id`, **`merchant_name`**, **`title`** (the real listing title),
   `images` (7 sizes, 75x75 → 1200x). Returns **35 rows** on `event=OUTBOUND_CLICK`
   (verified: category 1039 Beach towels, 2026-08-16; matches the UI's own "Showing
   35 Pins" label). `merchant_name` is present in this REST response directly — the
   `POST /_/graphql/` `v3GetPinsQuery` that also fires re-resolves the same pins and
   is redundant (see below).

   **Navigation:** the "Explore top products" button opens a modal listing all 35
   with Preview / Merchant / Product name columns and an outbound link per row —
   and fires **zero** new requests (verified 2026-08-16). It is a client-side render
   of the page-load payload, so there is nothing extra to call for the full list.

   This is real competitor/retailer intelligence — who is currently winning outbound
   clicks in a category, by name. `etsy_competitors()` filters it to
   `merchant_name == "Etsy"`; note the value is the exact string per merchant and is
   not normalized (live values include `"Amazon.com"`, `"Wander Prints ™"`,
   `"Beachwood Baby"`) — match on `"Etsy"` exactly, never a substring/prefix rule.
2. **Performance → Relative interest over time** — same `/metrics/US` machinery as
   the table page, single category. `Date range` dropdown: `90D`/`180D`/`365D`/`730D`
   → `days=` param, plus an event switcher (`ENGAGEMENT`≡"All"/`OUTBOUND_CLICK`/`SAVE`
   — note "All" is the UI label for `ENGAGEMENT` here, differs from the table page's
   own "Engagement" label for the same value). Forecast always-on, same 28-day
   horizon (dashed line + band past the vertical "today" marker).

   **Response shape** (✅ scraped 2026-08-16, cat 1039, `days=730 predicted_days=28`):
   `data.values[0]` = `{term: "1039", growth_rates: {...}, daily_values: [...]}`.
   Despite the name, `daily_values` is **weekly** — 109 points for 730 days.
   Each point: `{date, count, normalized_predicted_lower_bound,
   normalized_predicted_upper_bound}`.
   - `count` is **normalized 0–100 against the window's own peak**, not absolute
     volume — so a `count` is only comparable within one response. Changing `days`
     re-bases it (same caveat as `series_store.slice_window`).

   #### The forecast — fully mapped ✅ 2026-08-16 (cat 1039, `days=730`)
   **The chart legend names all three series** (✅ read live): `Historical volume`
   (solid) · **`Predicted median`** (dashed) · **`Prediction bounds`** (shaded band).
   So `count` on a forecast row is Pinterest's own *median* estimate, and `lo`/`hi`
   are its bounds — use that vocabulary rather than inventing our own.

   **Forecast points carry a real prediction in `count`, not a zero or a null.**
   Tail of the `predicted_days=28` response:
   ```
   2026-07-29  count 21   lo null  hi null    ← observed
   2026-08-05  count 21   lo null  hi null    ← observed
   2026-08-12  count 21   lo null  hi null    ← observed (= end_date)
   2026-08-19  count 30   lo 24    hi 36      ← FORECAST
   2026-08-26  count 31   lo 25    hi 37      ← FORECAST
   2026-09-02  count 28   lo 22    hi 33      ← FORECAST
   2026-09-09  count 24   lo 19    hi 28      ← FORECAST
   ```
   - **Split on `normalized_predicted_upper_bound !== null`** — same rule as the
     search-side `split_forecast()`. There is no `has_prediction` flag on this
     endpoint (unlike search `/metrics/`), so the bound fields are the *only* marker.
   - 🔴 **`count` on a forecast row is a PREDICTION.** Averaging or summing `count`
     across the raw array silently mixes measured and predicted values — the exact
     "plausible wrong number" this project guards against. Always split first.
   - `lo`/`hi` = the shaded confidence band; roughly ±6 around the point estimate here.
   - **Forecast length = `predicted_days / 7`**, exact, weekly cadence:

     | `predicted_days` | total points | forecast points |
     |---|---|---|
     | 0 | 105 | 0 |
     | 14 | 107 | 2 |
     | 28 | 109 | 4 |
     | 56 | 113 | 8 |
     | 91 | 118 | 13 |

   - ✅ **The forecast is APPENDED — it does not re-normalize history.** Verified by
     diffing the 105 observed points of `predicted_days=28` against a
     `predicted_days=0` call: **byte-identical, zero diffs**. Forecast peak (31)
     stays under the observed peak (100), and asking for a forecast is therefore
     safe — you can request it once and slice, rather than making two calls.

   - ✅ **UI ↔ wire verified visually** (cat 1039, 730D, 2026-08-16). Every element
     of the rendered chart maps to a scraped field with no discrepancy:

     | On screen | Scraped |
     |---|---|
     | x-axis starts "Aug 14, 2024" | `daily_values[0].date = 2024-08-14` |
     | vertical marker at "Aug 12, 2026" | `end_date` = last observed point |
     | single tall spike to 100, ~Oct/Nov 2025 | peak `count:100` @ `2025-10-22` |
     | small dashed line + shaded band right of the marker | the 4 forecast points |
     | y-axis 0–100 | `count` normalized to window peak |

     The **vertical line is the `end_date`/"today" boundary** — everything left of it
     is measured, everything right is predicted. That line is the visual equivalent
     of the null-bound split, and it is the one thing to reproduce in our own UI so
     an operator never reads a forecast as a measurement.

   - 🔴 **`growth_rates.mom_change` is NULL unless `predicted_days > 0`.** Verified
     across all five horizons above: `pd=0` → `{wow:null, mom:null, yoy:null}`;
     every `pd>0` → `mom_change: 0.25`, **constant regardless of horizon**. So the
     value is a property of the category, not of the prediction length — but it is
     only *exposed* when the forecast pipeline runs. **Requesting `predicted_days=0`
     to "keep it clean" silently throws the only growth number this endpoint has.**
     Another *absent ≠ zero* trap (N-02): null here means "not asked for", not "no
     growth". `wow_change`/`yoy_change` were null at every horizon.
3. **Demographics** — `GET /ads/v4/trends/shopping/product_categories/demographics/US`
   with `product_category_ids`, `event`, `end_date`. **Carries three blocks, not one**
   (✅ full shape captured 2026-08-16, category 1039) — this single call feeds both
   the Demographics section AND the page's 30-day header:
   ```
   data.product_category_distributions["1039"] = {
     summaries: [{ outbound_clicks|engagement|saves: {percent_growth, lookback:2,
                   total:0, percent_relative_volume:null} }],     ← the §0 header, ×100
     demographics: [{ age_distribution:   {"18-24":0.15, "25-34":0.26, "35-44":0.20,
                                           "45-49":0.08, "50-54":0.07, "55-64":0.13,
                                           "65+":0.11},
                      gender_distribution:{male:0.14, female:0.74, unspecified:0.12} }],
     related_search_trends: [ ...25 seed keywords ]                ← free, same as top/US
   }
   ```
   - age/gender keys are the **display labels** here (`"18-24"`, `"female"`) — a third
     spelling, distinct from both `ageBuckets=[2,3]` (search) and `AGE_18_24`
     (shopping request side). Response-side ≠ request-side; do not reuse a mapping.
   - distributions are **fractions summing to ~1.0**, not percentages — ×100 for display.
   - `total: 0` and `percent_relative_volume: null` are ⚠️ always-empty here; the real
     magnitude lives on `top/US`, not this call. Do not read `total` as a volume.
   - **`related_search_trends` rides along free** — 25 seeds per category without a
     second request, same list `top/US` returns.

   🔑 **`event` genuinely re-computes the demographics — this is a real intent signal,
   not a label swap.** Verified 2026-08-16 on cat 1057 (Bird supplies), same call,
   only `event` varied:

   | age band | `OUTBOUND_CLICK` | `SAVE` |
   |---|---|---|
   | 25-34 | 0.16 | **0.24** |
   | 55-64 | 0.18 | 0.15 |
   | 65+ | **0.24** | 0.16 |

   The people who **save** bird supplies skew young; the people who **click through
   to buy** skew 65+. Same category, opposite audience. This is JOIN 3 (buyers vs
   dreamers) at *demographic* resolution — nothing on Etsy can produce it, and it
   would be invisible to anyone who only ever called the default event.
   ⚠️ Corollary: a demographic quoted without naming its `event` is meaningless here.
   `gender_distribution` moved far less (female 0.78 → 0.76), so the split is
   age-driven in this category.

   ⏸️ `related_search_trends` is **event-independent** — byte-identical across all
   three events, so fetch the seeds once with whatever event you already need.

4. **"Related to {category}" — two sub-sections, ZERO new endpoints** ✅ 2026-08-16.
   Sits below Demographics; nothing here costs an extra call:

   - **"Search queries"** — *"People engaging with this product category commonly
     search for:"* — is exactly `demographics/US → related_search_trends`. Verified
     term-for-term and in-order on cat 1057 (`bird feeder`, `unique bird houses`,
     `bird cage decor`, `mom`, `parrots`, …). **25 terms in the payload; the UI
     renders 19 and hides the rest behind "+ View more"** — the API gives you the
     full set with no interaction. There is a **"Copy keywords"** button (the
     vendor's own signal that this list is meant to be exported), and each chip is a
     link out to that keyword's trend view.

   - **"Other product categories"** — *"People interested in **X** are also
     interested in these other product categories"* — 🔴 **is NOT an affinity or
     behavioural model, despite that copy. It is siblings in the taxonomy tree.**
     Verified exactly: cat 1057 Bird supplies → `parent_product_category_id: 1365`
     (Pet supplies) → that parent's `children` = [Dog supplies, Pet carriers &
     crates, Pet collars & harnesses, Cat supplies, **Bird supplies**] → the UI
     renders the 4 siblings with self excluded. Byte-for-byte the same four cards.
     **Derive it locally from the cached taxonomy; never treat it as co-interest
     data.** A competitor reading that heading would report "Pinterest says bird-
     supply buyers also want dog supplies" — the wire says only "these share a
     parent node".

### ⚠️ The drilldown's two data calls fail TRANSIENTLY on page load — always retry
**Corrected 2026-08-16 (twice).** Both `metrics/US` and `demographics/US` intermittently
return **500 on page load**, and the identical request succeeds on retry. This is a
transient/cold-start failure, **not** a bad parameter and **not** a dated regression.

❌ **A previous version of this doc claimed "`days=180` is broken / a genuine
regression". That was WRONG** — recorded here so nobody re-derives it. The evidence
that killed it:

| category | `days` | context | result |
|---|---|---|---|
| 1108 | 180 | page load | 500 |
| 1398 | 180 | page load | 500 |
| 1398 | 180 | page load, 2026-08-06 capture | **200** |
| 1039 | 180 | page load | **200** |
| 1039 | 730 | page load | 500 |
| 1108 | 90 / 365 / 730 | page load | **200** |
| **1039** | **730** | **manual retry ×6** | **200 ×6** (109 points every time) |

No `days` value is consistently broken — the same value passes and fails on different
loads, and the *decisive* test is the last row: the exact call that 500'd on page load
returned 200 on six consecutive retries. **Every `days` in the documented set works.**

**The two visible symptoms are the same bug:**
- chart renders flat, x-axis "Jan 1, 1970" (epoch-zero fallback) ⟸ `metrics/US` 500'd
- the "Key metric changes in the past 30 days" header is **missing entirely** ⟸
  `demographics/US` 500'd (it is that call's `summaries` block — see §0 above)

The UI retries `demographics/US` inconsistently and does not appear to retry
`metrics/US` at all, which is why a reload "fixes" the page. **Any client MUST wrap
both in a retry** (5 attempts, ~500 ms apart, was always sufficient in testing).
Never record a 500 here as "no data" — that is exactly the N-02 *absent ≠ zero* trap.

- **A `POST /_/graphql/` call (`v3GetPinsQuery`) also fires on this page but is NOT
  needed** — not a defect, just redundant: it re-resolves each `top_products` pin to
  merchant/domain info that the REST `top_products` response already carries directly
  (`merchant_name`, `title` present as-is — "Etsy", "Amazon.com", "Walmart", "Kroger
  Co", "Birch Lane" all confirmed on live captures). Don't build a client against the
  GraphQL call — the REST chain (`top/US` → `metrics/US` → `top_products` →
  `demographics/US`) is the complete, sufficient set for this page.

### Coverage: every call this page fires vs `pinterest/endpoints/api.py` ✅ audited 2026-08-16
**No endpoint is missing.** Full network capture of `/shopping/1039/`, data calls only
(auth/experiment/newshub noise excluded):

| Wire call | Client method | Status |
|---|---|---|
| `product_categories` | `product_categories()` | ✅ covered |
| `product_categories/top/{c}` | `top_categories()` | ✅ covered (table page) |
| `product_categories/metrics/{c}` | `category_metrics()` | ✅ covered |
| `product_categories/demographics/{c}` | `category_demographics()` | ✅ covered |
| `product_categories/top_products` | `top_products()` / `etsy_competitors()` | ✅ covered |
| `product_categories/top_products/{advertiser_id}/{cat}` | — | ⏭️ **deliberately skipped** — personalized to our own ad account, not market truth |
| `product_categories/recommendations/{advertiser_id}/{c}` | — | ⏭️ **deliberately skipped** — same reason |
| `POST /_/graphql/` `v3GetPinsQuery` | — | ⏭️ redundant (see above) |

The two skipped `{advertiser_id}` calls are the only uncovered ones, and both are
scoped to the operator's own ad account — they answer "what should *this advertiser*
look at", not "what is the market doing". Correctly out of scope.

**Re-audited 2026-08-16 after finding the "Related to {category}" section** (Search
queries + Other product categories): it adds **no new endpoint** — the first is
`demographics/US → related_search_trends`, the second is derived from the cached
taxonomy tree. Coverage is still complete. Four sections of this page are rendered
from three data calls; **the client already reaches everything the UI can show.**

### 🔴 Actionable gap in our client — no retry on `_api_resource`
`pinterest/endpoints/api.py:198` returns `None` on any non-200:
```python
if r.status_code != 200:
    print(f"[-] {inner_url} failed: {r.status_code} ...")
    return None          # ← a transient 500 becomes "no data"
```
Given the transient-500 behaviour documented above, `category_metrics()` and
`category_demographics()` **will intermittently return `None` for categories that have
perfectly good data**. Nothing downstream can distinguish that from "genuinely empty".
This is the *absent ≠ zero* failure mode (N-02) arriving through the transport layer.
**Fix: retry non-200 in `_api_resource` (5 attempts, ~500 ms apart) before returning
`None`.** Not yet implemented — flagged, not fixed, since the access layer is
documentation-only under `system-architect` rules; this one is business-logic-side
(`_api_resource` is the shared envelope, so confirm with the operator before touching).

---

## `product_categories()` — the taxonomy tree, and how direct navigation works ✅ 2026-08-16
`GET /ads/v4/trends/shopping/product_categories`, **no params**. One call returns all
383. `/shopping/?tab=all` fires exactly this one call; clicking Next/Prev through the
"1–16 of 383" pager (verified through page 2, "17–32 of 383") fires **zero** additional
requests — it slices the one object already in memory. No pagination logic needed on
our side; `product_categories()` already treats it as "fetch once, cache forever".

**Response is a TREE, not a flat id→name map** (✅ re-probed 2026-08-16 — the older
"383-entry id -> name dictionary" description undersells it). Shape is
`resource_response.data.categories`, an object keyed by category id:
```json
"1039": {"friendly_name": "Beach towels", "level": 3,
         "parent_product_category_id": "1036", "children": [],
         "l2_product_category_ids": ["1036"]}
"1003": {"friendly_name": "Accessories", "level": 2,
         "parent_product_category_id": "1181",
         "children": ["1221","1449","1246", ...21 ids]}
```
`level` (2/3/4 observed) · `parent_product_category_id` · `children[]` ·
`l2_product_category_ids[]`.

**This is what makes direct navigation possible without crawling the UI.** Every
drilldown URL is constructible from this one cached response — no search-by-name
endpoint exists or is needed:
```python
cat = categories["1039"]                       # friendly_name: "Beach towels"
url = f"/shopping/1039/?parentProductCategory={cat['parent_product_category_id']}&country=US"
# → /shopping/1039/?parentProductCategory=1036&country=US   ✅ renders cold
```
Build the `friendly_name → (id, parent_id)` index locally once from this call.

⚠️ Requires the `x-pinterest-pws-handler` header like every `/resource/ApiResource/`
call — re-confirmed live 2026-08-16 (omitting it returns `Invalid Resource Request`,
not a 200 with empty data).

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
| `demographics(terms)` | `{term_distributions: {}}` | ⚠️→✅ empty on low-volume "mom necklace"; populated on "nails" — see `/detail/` page section above |
| `metrics(terms, days)` | momentum series | ⚠️ None on "mom necklace" — inconsistent |
| `split_forecast` / `predicted_days` | 91-day forecast | ✅ 2026-08-16 — see `/detail/` page section |

---

## Never-probed surface ❓
`category_metrics`, `category_demographics`, `top_products`, `etsy_competitors`
(Pinterest's view of Etsy competitors per category — worth probing),
`editorial_content` (narrative layer, no metrics), `product_categories`. Assume nothing.
