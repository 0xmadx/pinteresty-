# Pinterest Trends — what the captures actually show, and how we use it

> New here? [`MASTER.md`](MASTER.md) is the one-page index across this whole file tree —
> [`endpoints/`](endpoints/README.md), [`pipelines/`](pipelines/README.md) and
> [`products/`](products/README.md) each also have their own README.

Read of all 8 DevTools exports in `endpoints/` (~1 MB of request/response transcript) plus the three
pipeline outputs in `data/`. This is the "what's really there" document; the endpoint reference lives in
[`endpoints/overviews.md`](endpoints/overviews.md).

**Read this before writing pipeline code.** Three things in here change what we should build.

> ### Verification status
> Every claim below was run against the live API on **2026-08-06** by
> [`tests/test_live_endpoints.py`](tests/test_live_endpoints.py) — **44 checks, 29 requests, all green**.
> Re-run it before trusting this doc after any gap:
> ```bash
> .venv/Scripts/python.exe pinterest/tests/test_live_endpoints.py
> ```
> It exits non-zero and names the broken claim, so it doubles as the canary for Pinterest changing
> anything under us. Three of the claims in earlier drafts were **wrong and are now corrected**: the
> `lookbackWindow` window sizes, the sort order on presets 1–2, and the `count` field on forecast weeks.
>
> Shopping is pinned by [`tests/test_shopping_endpoints.py`](tests/test_shopping_endpoints.py)
> (**50 checks, 58 requests**) and Spotlight/Moments by
> [`tests/test_spotlight_moments.py`](tests/test_spotlight_moments.py) (**39 checks, 51 requests**).
> **206 live checks across five suites** — the fourth,
> [`tests/test_local_derivations.py`](tests/test_local_derivations.py) (**17 checks**), pins the
> local math that replaces requests outright (see §7.3); the fifth,
> [`tests/test_products.py`](tests/test_products.py) (**54 checks**), pins the eight standalone
> products in [`products/`](products/) (see §9).
>
> **Capture coverage** is audited separately by
> [`tests/audit_capture_coverage.py`](tests/audit_capture_coverage.py), which inventories every request
> URL, query param, payload key and `endpoint_name` across all 8 capture files (69 distinct requests) and
> lists anything these docs don't mention. Re-run it whenever a capture is added.
>
> One capture file — `scrapfly-history-www.pinterest.com-2026-08-06.json` (29 KB) — was present at the
> start of this work and has since been deleted. It contributed nothing to these docs.

---

## 1. The pattern — every surface is the same three-step waterfall

Pinterest Trends is three dashboards on one API. Each fires the identical shape of request chain, and the
DevTools timings show it is **serial, not parallel** — each step waits for the ids the previous step
returned:

```
        ┌─ 1. DISCOVER ─────────┐   ┌─ 2. DEEP DIVE ──────────┐   ┌─ 3. EXPAND ───────────┐
Search  │ /top_trends_filtered/ │ → │ /metrics/ (50 terms)    │ → │ /related_terms/       │
        │  → ranked term list   │   │ /demographics/          │   │ /prefix_match/        │
        ├───────────────────────┤   ├─────────────────────────┤   ├───────────────────────┤
Shopping│ product_categories/   │ → │ .../metrics/US          │ → │ .../top_products      │
        │   top/US → cat ids    │   │ .../demographics/US     │   │ + GraphQL attribution │
        ├───────────────────────┤   ├─────────────────────────┤   ├───────────────────────┤
Spotlight│ topics/featured/US/  │ → │ (time_series inline)    │ → │ related_search_trends │
        │  <EVENT> per interest │   │                         │   │  inline               │
        └───────────────────────┘   └─────────────────────────┘   └───────────────────────┘
```

**Step 1 returns ids/terms. Step 2 turns them into curves. Step 3 turns them into more terms.** Step 3
feeding back into step 1 is the crawl loop — that's the whole graph.

Two consequences for our code:

- **Batch step 2.** `/metrics/` accepts all 50 terms in one comma-separated call, and the captures show it
  used that way (50 terms × 52 weeks in a single 400 ms request). Never loop one term at a time.
- **Cap concurrency at ~5.** Multiple captures show 388–454 ms *stalls* from the browser's 6-connection
  HTTP/1.1 limit. Same ceiling applies to us.

### The Growing-trends flow, call by call (confirmed live)

```
GET  /latest_available_date/          → {"date": "2026-07-27"}   ← feeds endDate everywhere
GET  /top_trends_filtered/?lookbackWindow=3&trendsPreset=3&…     → {"values": [ …50 items… ]}
GET  /metrics/?terms=<all 50, comma-sep>&days=90&aggregation=2
       &normalize_against_group=false&predicted_days=0           → sparklines for the table
POST /term_images/                                               → thumbnails
```

The **Seasonal tab is the same four calls** with `trendsPreset=4` and `days=365` on the metrics call —
seasonal sparklines exist to show the yearly recurrence, so they need the full year.

Then clicking a row navigates to
`/detail/?country=US&terms=<term>&dateRange=365D&genderDetailsPage=&aggregationLevel=2`
and fires **exactly three** calls:

```
GET /metrics/?terms=<term>&days=365&aggregation=2
      &normalize_against_group=true&predicted_days=91    ← the forecast request
GET /related_terms/?requestTerm=<term>&lookback=365&aggregation=2
GET /demographics/?terms=<term>&days=365
```

**Watch `normalize_against_group`.** The table sparklines use `false` (each term scaled to its own peak);
the detail chart uses `true` (scaled against the group). Mixing the two in one score compares curves that
were normalized against different denominators.

**`predicted_days=91`** is the forecast request — it populates `predictedUpperBoundNormalizedCount` /
`predictedLowerBoundNormalizedCount` only when `has_prediction` is true, which is often false. Read
`has_prediction` before touching those fields.

---

## 2. Navigation — the UI state IS the payload

Every `ApiResource` call carries a `source_url` that is the browser's own URL, and it encodes the complete
filter state with **pipe separators** (`%257C` = double-encoded `|`):

```
/shopping?country=US&tab=trending&product_categories=1181|1250|1042&page=1
         &sortBy=RELATIVE_VOLUME&sortOrder=DESC
         &ageBucket=AGE_18_24|AGE_25_34|…|AGE_65_PLUS&gender=…
```

Other observed navigation shapes:

| Route | State it carries |
|---|---|
| `/?country=US&topicInterestIds=948967005229\|924581335376\|903733943146` | Spotlight home, filtered to interests |
| `/search?country=US&trendsPreset=3` | Search dashboard, preset selected |
| `/detail/?country=US&terms=washington&trendsPreset=3&dateRange=…&ageDetailsPage=…&genderDetailsPage=…` | A single term's detail page |
| `/shopping/1398/?parentProductCategory=1250&country=US` | One category drill-down |

`source_url` appears to be telemetry/context rather than a filter — the real filter lives in
`options.data`. But **mismatched pairs are the most likely way to get flagged**, so mirror the UI: build
`source_url` from the same values you put in the payload. `page=1` in the shopping route also confirms that
surface paginates, which we have never exercised.

---

## 3. Options and enums — the full vocabulary

> **Status: confirmed against live traffic on the logged-in session.** The enum mappings below replace the
> guesses in the first pass of this document. Where the transcripts and the live teardown disagreed, the
> live teardown wins.

### The four tabs are `trendsPreset` — and only `trendsPreset`

| Tab | `trendsPreset` | `lookbackWindow` the UI sends |
|---|---|---|
| Growing trends | `3` | `3` |
| Seasonal | `4` | `2` |
| Top monthly | `1` | `2` |
| Top yearly | `2` | `5` |

⚠️ **`lookbackWindow` does not change the data.** Presets 3 and 4 were run across windows 1, 2, 3 and 5 and
returned byte-identical rows every time. It only drives the UI copy ("within the last 30 days…").
**`trendsPreset` alone selects the ranking logic** — pin `lookbackWindow` to anything and vary the preset.
*(Earlier drafts of this doc treated it as a 30/90/365-day data window. It isn't one.)*

### What the presets actually select — sort order and the `seasonality_score` floor

All four presets return **50 rows unfiltered** — but see the trap below — of the same object shape, with a
top-level `endDate` alongside `values`. They differ in **two** ways, both measured live:

| Preset | Tab | Sorted descending by | `seasonality_score` range |
|---|---|---|---|
| `1` | Top monthly | `reverseRank` / `searchCount` | 0.112 – 0.987 |
| `2` | Top yearly | `reverseRank` / `searchCount` | 0.112 – 0.996 |
| `3` | Growing | **`mom_change.index`** | 0.312 – 0.970 |
| `4` | Seasonal | **`mom_change.index`** | **0.830 – 0.995** |

⚠️ **Only presets 3 and 4 are velocity-sorted.** 1 and 2 are volume-sorted — their `mom_change.index`
sequences are unordered (`[33, 35, 39, 44…]`, `[30, 38, 42, 33…]`). Anything that assumes rank order means
momentum will be wrong on half the tabs.

So **Seasonal ≈ velocity-sorted AND seasonality ≥ ~0.83** — things that spike at the same time every year.
The threshold is directly reusable: filter any preset's output on `seasonality_score` and we reproduce the
Seasonal tab ourselves, and more usefully, score terms harvested from `related_terms` that never appeared
in a tab at all.

**Use `>= 0.82`, not `>= 0.83`.** The measured floor is `0.829886` — a `0.83` cut drops the boundary row.

⚠️ **A `moments=` filter can return far fewer than 50 rows.** Measured on preset 4: unfiltered 50,
`halloween` 50, `christmas` **30**, `summer` **27**, `oktoberfest` (DE+AT+CH) **14**. Never assume the table
is full, and never treat a short result as an error.

And **`moments=` is validated against the region's own vocabulary** — `moments=oktoberfest&country=US`
returns **400**, not an empty set, exactly like a typo would. The per-region list comes from
`moment/available`; see §5.1.

Ranking really is velocity-driven on 3/4: the top seasonal row was `cute august nails` at
`searchCount: 3` — near-zero volume, `mom_change.value: 75`. **`reverseRank: 50` is the top of the list**,
confirmed across all four presets.

**`aggregation`** — `2` = weekly buckets (dates come back one week apart).
**`days`** — `90` on the Growing table's sparklines, **`365` on Seasonal's** (the point there is showing the
yearly recurrence); `365` on detail pages; `60` · `180` on shopping metrics.
**`rankingMethod`** — `3` seen with preset 3. **Ranks by velocity, not volume** — one capture shows
"back to school outfits 2026-2027" at rank #1 with a *lower* `searchCount` than the term below it.
**`event`** (shopping) — `OUTBOUND_CLICK` · `SAVE` · `ENGAGEMENT`.
**`ranking_method`** (shopping) — `GROWTH`; **`order_by`** — `RELATIVE_VOLUME`; **`order`** — `DESC`.

### Demographics — two spellings, two encodings

| Where | Param names | Encoding |
|---|---|---|
| `/top_trends_filtered/` | `ageBuckets`, `gender` (**plural**) | numeric, comma-separated |
| `/metrics/` | `age_bucket`, `gender` (**singular**) | numeric, comma-separated |
| `/ads/v4/...` shopping | `age_bucket[]`, `gender[]` | string enums (`AGE_18_24`, `MALE`, …) |

**Gender:** `0` = male · `1` = female · `2` = unspecified.
**Age:** `18-24` = **`2,3`** (the UI sends *two* buckets for this one band) · `25-34` = `4` ·
`35-44` = `5` · `45-49` = `6` · `50-54` = `7` · `55-64` = `8` · `65+` = `9`.

That double bucket is why `ageBuckets=4,5,6,7,8,9,2,3` has eight indices for seven visible bands — the
open question from the first pass, now closed.

### Static vocabularies — hardcode these

**`moments`** (13, lowercase slugs): `christmas` `easter` `fathers day` `halloween` `hanukkah`
`independence day` `memorial day` `mothers day` `new years eve` `st patricks day` `summer` `thanksgiving`
`valentines day`

**`l1interests`** — all 24, confirmed:

| Interest | ID | Interest | ID |
|---|---|---|---|
| Animals | `925056443165` | Health | `898620064290` |
| Architecture | `918105274631` | Home Decor | `935249274030` |
| Art | `961238559656` | Men's Fashion | `924581335376` |
| Beauty | `935541271955` | Parenting | `920236059316` |
| Children's Fashion | `903733943146` | Quotes | `948192800438` |
| Design | `902065567321` | Sport | `919812032692` |
| DIY and Crafts | `934876475639` | Travel | `908182459161` |
| Education | `922134410098` | Vehicles | `918093243960` |
| Electronics | `960887632144` | Wedding | `903260720461` |
| Entertainment | `953061268473` | Women's Fashion | `948967005229` |
| Event Planning | `941870572865` | Finance | `913207199297` |
| Food and Drinks | `918530398158` | Gardening | `909983286710` |

**Hardcode this table.** `/v3/trends/partner/<userId>/available_interests/` is the authoritative source,
but replaying it through the `ApiResource` wrapper **returns 403** — and the list is static in the UI
anyway. Not worth fighting.

**`country`** also accepts the grouped values from the region dropdown, not just `US`:
`GB+IE`, `DE+AT+CH`, `MX+AR+CO+CL`.

**`keywordsToInclude`** — a *restrictive AND* filter, not a hint. A capture passing junk strings returned
`{"values":[],…}`; live, `keywordsToInclude=nails` returned 50/50 rows containing "nails". Filter logic
overall: **OR within a group, AND across groups.**

⚠️ **`shouldMock` — never send `true`.** It appears in the captured curls on `/metrics/` and
`/related_terms/`, always as `false`. Setting it to `true` returns **52 points of zeros** and silently
ignores `days`, with a 200 status. Omitting it behaves identically to `false`, so the safe move is to never
send it at all. Anyone copy-pasting a curl with `shouldMock=true` gets fabricated data that looks real.

---

## 4. Nodes and links

**Node types**

| Node | Key | Carries |
|---|---|---|
| `term` | the string | `searchCount`, `normalizedCount`, `reverseRank`, `seasonality_score`, `wow/mom/yoy_change{value,index}`, 52-week `counts[]`, age/gender distribution |
| `product_category` | numeric id (383 total) | `parent_product_categories[]`, `related_search_trends[]`, `summary{saves,engagement,outbound_clicks}{percent_growth, percent_relative_volume}` |
| `topic` | 19-digit id | `name`, `description`, `pct_growth_mom`, `time_series[]`, `related_search_trends[]`, `interests[]`, `pins[]` |
| `interest` | 12-digit id (24 L1) | the community root |
| `moment` | name | `takeoff_timestamp_millis`, `peak_timestamp_millis`, `peak_length_in_days`, phase label |
| `product` | `pin_id` | `merchant_name`, `title`, 7 image sizes |

**Link types**

| From → To | Source | What it means |
|---|---|---|
| term → term | `/related_terms/` | co-search correlation — *topically* similar, need not share a word (`washington` → `pnw aesthetic`) |
| term → term | `/prefix_match/` | string-prefix children (`washington` → `washington dc`) |
| category → term | `related_search_trends` | taxonomy ↔ keyword bridge |
| topic → term | `related_search_trends` | editorial ↔ keyword bridge |
| topic → interest | `interests[]` | community membership (topics carry 2–4 interests each) |
| category → category | `parent_product_categories[]` | **a DAG, not a tree** — `1108` has parents `1104` and `1350` |
| category → product | `top_products` | trending category → actual listings |
| product → merchant | GraphQL `V3GetPinsQuery` | pin → Etsy/Amazon/Walmart attribution |

The distinction between the two term→term edges matters: prefix match finds words that *start with* the
seed; related terms finds terms that are topically similar without containing it. **Only the second one
discovers niches we couldn't have guessed** — `washington` → `pnw aesthetic`, or `animal katseye` →
`silly cat`, `cat drooling`.

`/related_terms/` returns a small set (5 rows in the confirmed captures), so it is a *precision* edge
source, not a volume one. Breadth has to come from crawling many seeds, not from expanding one deeply.

**Change-value semantics:** in `wow_change` / `mom_change` / `yoy_change`, `value` is the fractional change
(0.1 = +10%) and **`100.01` is the UI's "10,000%+" cap sentinel** — clamp it, never average it. `index` is
the 1–50 rank the UI draws its bars from.

---

## 5. The three findings that change the plan

### 5.1 The moments calendar is a ready-made launch-timing engine

`/ads/v4/trends/moment/available/US` returns, for all 13 holidays, parallel arrays of:

```json
{"moments": ["thanksgiving", "valentines day", …],
 "peaks":            [{"takeoff_timestamp_millis": "1788220800000",
                       "peak_timestamp_millis":    "1795478400000",
                       "peak_length_in_days": 105}, …],
 "historical_peaks": [ …same shape, last year… ],
 "moment_next_occurrence_timestamps": ["1795651200000", …],
 "phase_labels":     ["approaching", "ended", "cooldown", …]}
```

All five arrays are **index-parallel to `moments[]` in the order the API returns it**. Verified: all five
have length 13 for US. Zip them on index; never re-sort one without the others — grouped regions come back
alphabetised while single regions do not, so the ordering is not even stable across regions.

**The vocabulary is per region, and this endpoint is the authority for it.** It tells you exactly which
`moments=` values `/top_trends_filtered/` will accept there, because **an out-of-region moment is a 400,
not an empty result**.

⚠️ **Region coverage is narrower than the first pass claimed, and the timestamps are narrower still.**
Re-measured on 2026-07-27/08-07, cross-checked two ways — the raw API (this repo) and the live
`trends.pinterest.com` UI itself via a separate browser session — and they agree exactly:

| Regions | Result |
|---|---|
| `US` `CA` `BR` `MX` `IT` `ES` `FR` `DE` `CO` `AR` (single country) | moments **and** full takeoff+peak timestamps |
| `DE+AT+CH` `AU+NZ` `MX+AR+CO+CL` (grouped) | **one** moment per region gets `peak_ms` (never `takeoff_ms`); every other moment is fully null |
| `GB+IE` `NL+BE+LU` `SE+DK+FI+NO` `IT+ES+PT+GR+MT` (grouped) | moment names only — **every field in `peaks` and `historical_peaks` is null** |
| `JP` | 200 with an empty list |
| `AU` `NL` `IE` `GB` `ZZ` | **400** — no standalone code exists for any of these; there is no single-country UK view to fall back on |

So "only `ZZ` is rejected" was wrong, and most grouped regions hand back a calendar with no dates in it at
all. **There is no way to get UK timings, full stop**: `GB` and `IE` both 400 individually, and `GB+IE`
carries zero populated timestamps of 11 moments (confirmed twice, no flake). `next_occurrence_ms` cannot
substitute — measured against the moments that have both, the takeoff→occurrence gap ranges 16–468 days,
because that field sometimes points at next year's date while takeoff points at this cycle's.

**The UI confirms this is Pinterest's own limitation, not a client bug.** The term detail page
(`/detail/?terms=...`) never shows timing in *any* region — that information lives entirely on a separate
`/moments/<name>/` page. That page is **US-only right now**: switching its region selector to any other
country pops a "some features may not be available" warning and ejects to the Trends home page rather
than rendering. So even Pinterest's own product has nothing to show for GB+IE — the gap is upstream of us.

| Region | moments | flavour |
|---|---|---|
| US | 13 | `independence day`, `memorial day`, `hanukkah`, `thanksgiving` |
| CA | 12 | `canada day`, `superbowl`, `diwali`, `lunar new year` |
| GB+IE | 11 | `prom`, `st patricks day` |
| DE / DE+AT+CH | 12 | `oktoberfest`, `karneval`, `spring`, `ramadan` |
| MX+AR+CO+CL | 10 | `pride`, `colombia moda` |
| JP and several others | 0 | reachable, empty |

`moments=oktoberfest&country=US` → **400**. `moments=canada day&country=CA` → **200 with 0 rows** (valid,
just out of season). Those two failure modes look identical if you only check the row count.

The Etsy playbook's central timing rule — *list 6–8 weeks before the ramp* — is currently a guess derived
by eyeballing a 365-day chart. **Pinterest publishes the takeoff date directly.** `takeoff_timestamp_millis`
minus 6 weeks is the listing date, computed rather than estimated, with `historical_peaks` to validate the
prediction against last year and `phase_labels` to tell us live whether we're already late.

Zero quota, one request, covers every seasonal niche at once. This is the single highest-value endpoint in
the folder and nothing currently calls it.

### 5.2 `top_products` hands us Etsy competitors, by name

`/ads/v4/trends/shopping/product_categories/top_products` returns the actual pins driving outbound clicks
in a category — and `merchant_name` is `"Etsy"` for a large share of them:

```json
{"pin_id": "4600567878237622656", "merchant_name": "Etsy",
 "title": "Leopard Print Runner Rug, Beige Black Hallway Carpet 3x12 3x14 custome size",
 "images": {"75x75": …, "236x": …, …, "1200x": …}}
```

A follow-up GraphQL POST to `/_/graphql/` (`V3GetPinsQuery`) resolves each `entityId` to its merchant and
link domain. So the chain is: **trending category → the Etsy listings winning its traffic → their exact
titles → straight into our existing title/tag gap analysis.** That is competitor discovery filtered by
proven purchase intent, which the Etsy SERP alone cannot give us — the SERP shows who ranks, this shows who
gets clicked.

⚠️ **But Etsy's share is sparse and varies wildly by category.** Measured across 8 categories:

| Category | products | Etsy | dominant merchants |
|---|---|---|---|
| Body jewelry (1062) | 38 | **7** | Amazon, UrbanBodyJewelry, Etsy |
| Runner rugs (1398) | 21 | **4** | Walmart, Amazon, Etsy |
| Candle holders (1086) | 28 | 1 | Amazon, Walmart, SheIn |
| Beads & jewelry supplies (1040) | 29 | 1 | Amazon, Target, Walmart |
| Area rugs · Bath mats · Cake decorating · Candles | 22–30 | **0** | Amazon, Walmart, Target, SheIn |

Big-box dominates most categories. So this is a **prospecting filter, not a firehose**: sweep the 383
categories once, keep the ones where Etsy actually places, and treat those as the niches where handmade
competes on Pinterest at all. A category with zero Etsy pins is itself a signal — the traffic there goes to
mass retail regardless of how the term trends.

Also note the result count is **21–38, not the `limit: 20` the payload suggests** — `limit` and `offset`
are both ignored on `top_products`; you get whatever the backend holds (US/1010 → 23, CA → 50,
GB+IE → 49). And **only `OUTBOUND_CLICK` returns rows** — `SAVE` and `ENGAGEMENT` return 200 with zero
products, so there is no "what gets saved" competitor list, only "what gets clicked".

### 5.3 `endDate` back-dates cleanly — we can build history

**Confirmed live:** `endDate=2025-12-01` returns `endDate: 2025-11-28` — it **snaps backward to the nearest
data week** — with `christmas nails`, `holiday nails`, `charcuterie board`, `december nails` on top. An
earlier capture at `endDate=2026-07-07` likewise returned a coherent 4th-of-July set (slowly — 1.4 s,
consistent with a cold-storage read).

**Pinterest will replay any historical week on demand.** Etsy gives us only the present, so our
longitudinal value has to accumulate week by week; Pinterest's can be **backfilled in an afternoon**. A
year of weekly snapshots is one loop over 52 `endDate` values — and because the response echoes the snapped
`endDate`, we key the archive off the returned value, never the requested one.

That makes a genuinely unusual dataset possible: *last* year's seasonal ramp for a niche, at weekly
resolution, which is exactly what validates a launch date before we commit to it.

---

## 6. Constraints and gotchas

- **Counts are normalized indices, never absolute.** `normalize_against_group=true` scales terms against
  each other; `searchCount` tops out at 100; shopping `summary.total` is literally always `0`. Pinterest
  gives shape and rank. Magnitude comes only from Etsy `results-data`.
- **The forecast is a two-step, and per-term.** `has_prediction` in the `/metrics/` response is the gate —
  it drives the "crystal ball" icon in the UI (not a separate endpoint; the icon just links to the detail
  page). Where it's `true`, re-requesting with `predicted_days=91` **grows the array from 53 to 66 weekly
  points**, with `predictedUpperBoundNormalizedCount` / `predictedLowerBoundNormalizedCount` filled on the
  13 trailing weeks — the first bounded point is dated the week *after* `endDate`, so the split between
  observed and forecast is exact.
- ⚠️ **`count` on forecast weeks is the prediction, not zero.** Measured: bounded points came back
  `[38, 61, 53, 26, 8, 2, …]`, not `[0, 0, …]`. Anything that reads "current volume" off the last point of
  a `predicted_days=91` response gets a **forecast presented as a measurement**. Branch on
  `predictedUpperBoundNormalizedCount is not None` to find the boundary, or just request
  `predicted_days=0` whenever you want observed data only.
- **URL length is a real ceiling.** The filtered trends URL already runs ~900+ chars and the ApiResource
  `data` param is URL-encoded JSON. Adding filters risks **414 Request-URI Too Large**. The captures
  repeatedly flag this. Cap `l1interests` and `terms` batches per request rather than sending everything.
- **`client_context` is response bloat and contains account PII** — 63 keys including owner name, email and
  billing status. **Strip to `resource_response.data` at ingest** and never commit a raw dump that keeps it.
  (`data/*_pipeline_output.json` currently keeps it — those should be re-dumped stripped.)
- **`cache-control: private, no-cache` on everything.** No CDN cache to lean on; our own cache layer is the
  only thing between us and a fresh 400–800 ms round trip. TTFB is 300–800 ms typical, 1.4 s for back-dated
  reads.
- ⚠️ **`x-pinterest-pws-handler` is mandatory on every `/resource/ApiResource/get/` call.** Without it the
  whole family returns `403 Invalid Resource Request` — moments, shopping, spotlight, all of it. **The
  value is never validated**: `trends/bogus-does-not-exist.js` returns 200. `x-pinterest-source-url` alone
  does nothing. The flat REST endpoints need no `x-pinterest-*` headers at all. This single header is the
  difference between "the shopping and spotlight pillars work" and "they don't", and it is not obvious
  from the captures, where the browser always sent everything.
- **No quota anywhere.** No `quota_data`, no counter, no cap in any of the 257 captured requests, and
  nothing appeared across 29 live calls either. The only budget is politeness.
- **There is no export endpoint.** The Export button is a plain `<button>` with no href; the page ships a
  papaparse bundle and builds the CSV client-side from data already fetched. Nothing to call — we
  reconstruct it from `/top_trends_filtered/` + `/metrics/` ourselves, which we're doing anyway.

---

## 7. How we use it

### 7.1 Where each Pinterest signal lands in the Etsy scoring model

`Opportunity = (Demand × Momentum × Intent) / (Supply × SERP Strength)`

| Variable | Source | Field | Cost |
|---|---|---|---|
| Demand (absolute) | Etsy `results-data` | `searchVolume` | **metered** |
| Momentum | Pinterest `top_trends_filtered` | `mom_change.value`, `yoy_change.value` | free |
| Timing | Pinterest `moment/available` | `takeoff_timestamp_millis` | free |
| Seasonality | Pinterest `top_trends_filtered` | `seasonality_score` | free |
| Intent | Pinterest shopping | `OUTBOUND_CLICK` growth ÷ `SAVE` growth | free |
| Audience | Pinterest `demographics` | age + gender split | free — **no Etsy equivalent** |
| Supply | Etsy public SERP | `organic_listings_count` | free |
| SERP strength | Etsy public SERP | card review counts | free |

The **click/save ratio is the sharpest new signal**: a category with high saves and low outbound clicks is
aspiration — people pin it and never buy. High clicks relative to saves is purchase intent. Pinterest gives
us both curves for the same category, and nothing on the Etsy side separates browsing from buying.

Two measured facts sharpen this further:

- **The category set itself differs by event** — 44 categories rank on `OUTBOUND_CLICK`, 35 on
  `ENGAGEMENT`, only **18** on `SAVE`. A category that ranks on clicks but not on saves is bought without
  being dreamed about; the reverse is a mood board. The set difference is the signal, before any ratio.
- **Shopping curves can be sliced by demographic even though the UI never does it.** `age_bucket` and
  `gender` are accepted and applied on the category `/metrics/` call, so "is this category's growth coming
  from 18-24s or 55-64s?" is answerable per category — and it pairs directly with the Etsy price band,
  since those two audiences do not pay the same money.

### 7.2 The funnel

1. **Seed** from `moment/available` (what's approaching) + `top_trends_filtered` (what's rising now).
   Sweep the seed step rather than calling it once: **4 tab presets × 24 interests** is 96 free requests
   returning up to 50 terms each, and the same table sliced by `moments=` or by age/gender gives more
   again. `keywordsToInclude` narrows a sweep to our own niche vocabulary. This is where corpus breadth
   comes from — `related_terms` only returns ~5 rows per call, so it refines rather than scales.
2. **Expand** free and wide — `related_terms` + `prefix_match`, depth 3, batching `/metrics/` 50 terms at a
   time. Etsy's crawl runs depth 1 because it burns quota; this one has no such limit.
3. **Score** on momentum × seasonality × click/save ratio, filtered to demographics that match the buyer.
4. **Spend Etsy's 15 quota units** on the top ~15 survivors only. This is the entire point of the pillar.
5. **Cross-check competitors** with `top_products` → Etsy listing titles → existing tag/title gap analysis.
6. **Time the launch** from `takeoff_timestamp_millis` − 6 weeks instead of guessing.

---

## 7.3 Doing it locally — what replaces a request

Verified by [`tests/test_local_derivations.py`](tests/test_local_derivations.py)
(**17 checks**), which re-derives each value locally and diffs it against the response the
endpoint would have returned. This matters more than a normal test: a broken derivation
returns a *plausible number*, not an error.

**The big one — `related_terms` and `prefix_match` already contain the series.** Both hand
back a full weekly `counts[]` for every term they suggest, and the crawler was discarding it
and then buying the same numbers back from `/metrics/`:

| Source | Points | Versus `/metrics/?days=365` | Free per call |
|---|---|---|---|
| `related_terms` | 53 | **byte-identical** | 5 exact series |
| `prefix_match` | 52 | `metrics[1:]`, renormalized to its own 52-week peak — **≤2 units apart** on a 0–100 scale | 10 approx series |

So **every expansion step yields 15 free series**. [`endpoints/series_store.py`](endpoints/series_store.py)
harvests them automatically inside `related_terms()`/`prefix_match()`, keyed per term, with
provenance ranked so an approximate prefix row never overwrites an exact one. Replaying only
the *existing* cache recovered **126 terms with zero requests**; 22 of the 32 terms
`/metrics/` had already been called for were among them.

Measured against a live frontier: **at depth 1, 161 of 170 queued terms (95%) can be served a
90-day curve with no request at all.** Seeds are the exception — a discovery-table row has
never appeared in an expansion response, so it genuinely has to be fetched.

**One `/top/` call covers all three events.** A row fetched with `event=OUTBOUND_CLICK` still
carries the `saves` and `engagement` summary blocks. `event` only decides which categories
*rank* (44 on clicks, 35 on engagement, 18 on saves). **The click/save intent ratio therefore
costs one request, not three.**

**`order_by` is a local sort.** Both `percent_growth` and `percent_relative_volume` ship in
every row. `resort()` reproduces `PCT_CHANGE_MOM` *and* `RELATIVE_VOLUME` exactly — the
tie-break is **ascending category id**, and without it the local order diverges at the first
tie (~4 tied pairs in a 44-row response).

**Shorter windows slice out of longer ones** — but this is *renormalization*, not truncation:
the API scales every window to 100 at its own peak, so a naive tail is off by the ratio
between the two peaks. `slice_window()` reproduces the API exactly for 13 of 14 terms.
The failure mode is specific and the store refuses it rather than guessing: when a term's
recent weeks round to `0` inside the 365-day series, precision was destroyed by the *source*
rounding before any slicing happened.

**Launch dates are subtraction.** `takeoff_ms` is a timestamp; the "list 6–8 weeks before the
ramp" rule is `calendar()`, not an endpoint.

### ⚠️ What is NOT derivable — do not compute these

- **`seasonality_score`.** Probed 12 terms against their 53-week series: neither coefficient
  of variation nor top-8-week concentration tracks it monotonically (score `0.9909` at
  cv `2.462`, but score `0.9558` at cv `3.661`). It uses history we are not given. Read it
  off `/top_trends_filtered/`.
- **`growth_rates`.** The API's wow/mom/yoy do not reproduce from point-to-point deltas on
  the returned counts — measured `api wow=5` where the naive calculation gives `456`. They
  ship *inside* the `/metrics/` response, so **store them rather than recompute them**
  (which is why the crawler now requests `days=365`: same one call, widest window, and
  growth rates ride along).
- **Demographics, forecasts, `top_products`.** No local shortcut exists.

---

## 8. Build order

Ordered by what unblocks the most:

- [x] **Constants module** — [`endpoints/constants.py`](endpoints/constants.py). The 24 interest ids, 13
      moments, age/gender enums, tab presets, the 0.82 seasonal floor and the change-cap clamp.
      `available_interests` is reachable but returns `{"results": null, ...}` on this account, so
      hardcoding is the only path.
- [x] **`/latest_available_date/`** — `api.latest_available_date()`, memoised per instance and defaulted
      into every other call. No hardcoded dates anywhere.
- [x] **`moment/available`** — `api.moments_calendar()`, which zips the five index-parallel arrays into
      one dict per moment so they cannot drift apart.
- [x] **`pinterest/endpoints/api.py`** — cache-first `PinterestTrendsAPI` matching the shape of
      `EtsyPrivateAPI`/`EtsyPublicAPI`. Strips `client_context`, asserts `endpoint_name`, never sends
      `shouldMock`, sends `x-pinterest-pws-handler` on every ApiResource call. Smoke-tested cold to warm:
      **16.5s -> 1.11s**.
- [x] **`top_products`** — plus `api.etsy_competitors()` for the merchant filter.
- [x] **Graph schema** — `edges` table, `source`/`node_type` columns, and the `get_node` bug fixed
      (see [`endpoints/overviews.md` §7](endpoints/overviews.md)). Migration is additive; the 5
      pre-existing Etsy nodes and 59 frontier rows survived and were backfilled `source='etsy'`.
- [x] **`pin_graph_pipeline.py`** — BFS on the frontier contract `ssr_graph_pipeline.py` already uses.
      Seeds from `top_trends()`, expands via `related_terms` + `prefix_match`, batches `/metrics/` at
      50 terms/call. Verified live: 17 nodes, 153 edges (99 prefix / 54 related), 241 queued.
- [x] **Reconcile with `core/`** — `pinterest/pipelines/scrape_*.py` are all ported onto
      `PinterestTrendsAPI`. `core/trends.py` and `core/api_resource.py` (the older async, uncached
      versions — the latter also missing the mandatory `x-pinterest-pws-handler`, so it 403'd) are
      deleted; nothing imported them. `client.py`, `cookie_server.py`, `extract_cookie.py` and
      `scraper_test.py` stay — cookie sync and manual capture tooling, not superseded.
- [x] **Series store + local math** — [`endpoints/series_store.py`](endpoints/series_store.py)
      and [`endpoints/local_math.py`](endpoints/local_math.py). Harvests the free series out of
      every related/prefix response, serves `/metrics/` subsets and shorter windows locally,
      and replaces the three-event and two-ordering shopping calls with arithmetic. See §7.3
      for the measurements and for the three values that must **not** be derived.
- [x] **The eight standalone products** — [`products/`](products/), pinned by
      [`tests/test_products.py`](tests/test_products.py) (54 checks). See §9.
- [ ] **Strip + re-dump** `data/*_pipeline_output.json` to `resource_response.data` only, with
      `_explanation.md` beside each. They currently retain `client_context` (account PII).

### Open questions

**Closed by the live teardown:**
- ~~Numeric vs string enum mapping~~ — resolved; `18-24` sends two buckets (`2,3`), which is why there were
  eight indices for seven bands.
- ~~How fresh is "now"?~~ — resolved; `/latest_available_date/` tells us directly. Never hardcode a date.
- ~~Is the interest list fetchable?~~ — resolved; the wrapper 403s on replay, so hardcode the 24 ids.

**Also closed by the live run:**
- ~~Does the ApiResource family work headless?~~ — yes, with `x-pinterest-pws-handler`. Shopping dictionary
  returns 383 categories; spotlight returns topics. Both pillars are unblocked.
- ~~Do presets sort consistently?~~ — no. 3/4 velocity, 1/2 volume.

- ~~Does `top_products` cap at 20?~~ — no, it returned 21–38 depending on category. The `limit` in the
  payload governs the category ranking call, not this one.
- ~~Does `numTermsToReturn` go above 50?~~ — **yes, up to 100.** 101/120/150/199 all 400, so 100 is the
  hard ceiling. Verified on presets 1/3/4 and with an `l1interests` filter, and **the first 50 rows are
  byte-identical to the default call**, so raising it only ever appends rows 51–100 and never re-ranks.
  The seasonal score floor still holds in the tail (min 0.8281 in rows 51–100, above the 0.82 cut).
  It is a ceiling, not a guarantee — an interest-filtered table returns however many terms qualify
  (Beauty 100, Wedding 34, Finance 1). Across all 24 interests: **1208 unique terms at limit=100 vs 734
  at the default 50 — +65% breadth for the same 24 requests.** Wired as `api.top_trends(limit=...)`;
  `keyword_research.sweep()` defaults to 100, `history.backfill()` deliberately does not (see §9).

**Still open:**
- **Is `related_terms` weighted?** It returns `counts[]` per term but no edge weight, and only **5 rows**
  (measured). Proposal: weight the edge by correlation between the two terms' 52-week series — computable
  from data we already fetch.
- **Shopping pagination** — `page=1` in the navigation state, never exercised. How deep does the category
  ranking go past `limit`?
- **Which of the 383 categories have Etsy presence?** One sweep of `etsy_competitors()` answers it and
  produces the shortlist of niches where handmade competes on Pinterest at all. ~383 cached calls, no quota.
- **What `affinity` is.** Present on every term node, `null` in **every** row of a live 50-row table as
  well as in every capture. Assume it is dead until proven otherwise.

---

## 9. Pure Pinterest — the eight standalone products

Everything above treats Pinterest as the free funnel that decides where Etsy quota gets spent.
This section is the other reading: `trends.pinterest.com` as its own data source, with nothing
routed back to Etsy. The code lives in [`products/`](products/) — no import from `etsy/api/public/`,
`etsy/api/private/` or `core/`, and no Etsy-shaped record anywhere in it.

```bash
.venv/Scripts/python.exe pinterest/products/cli.py            # list all eight
```

| # | Module | What it answers | Cost |
|---|---|---|---|
| 1 | [`keyword_research.py`](products/keyword_research.py) | what to write/pin/bid on, any niche | 1–2 req per term |
| 2 | [`content_calendar.py`](products/content_calendar.py) | when interest takes off, when to publish | 1 req per region |
| 3 | [`ad_targeting.py`](products/ad_targeting.py) | which Ads interest × age × gender is moving | 24 req, then cached |
| 4 | [`market_intel.py`](products/market_intel.py) | who owns the clicks; the 383-node taxonomy | 1 req per category |
| 5 | [`history.py`](products/history.py) | the weekly archive Pinterest has no export for | 1 req per week per preset |
| 6 | [`audience.py`](products/audience.py) | who searches a term, by age and gender | 1 req per batch |
| 7 | [`moodboard.py`](products/moodboard.py) | what a trend looks like — pins, colours, palette | 1 req per interest |
| 8 | [`alerts.py`](products/alerts.py) | what changed since last week, as a typed feed | 0 — reads the archive |

### What each one found that the Pinterest UI does not show

**1 · Keyword research.** `prefix_match` and `related_terms` do different jobs and both attach a
full weekly series to every suggestion, so a depth-1 corpus of ~40 terms costs zero `/metrics/`
calls. `sweep()` re-runs the discovery table inside each of the 24 interests and asks for the
server's real maximum of 100 rows rather than the UI's 50: **1208 unique terms from 24 requests,
against 734 at the default** — the single biggest free win in this whole section, and it was
sitting behind a parameter the UI never varies. `cross_interest()` then finds the 165 terms that
rank inside more than one interest, which no single table can show. Rows whose recent series never
exceeds 25 are flagged `noisy`: on a 0–100 normalized scale a term sitting at 1–3 all year
produces velocities like +900% off a one-unit move.

**2 · Content calendar.** The launch date is `takeoff_ms` − 6 weeks, and `to_ics()` emits a real
calendar file. The drift check is the finding: **every approaching US moment drifts exactly 0 days
against last year**, i.e. Pinterest's "prediction" is last year's date plus 365. Worth knowing
before treating it as a forecast. For moments already past this cycle Pinterest echoes the same
timestamp into both the current and historical blocks, so `drift` is `None` rather than a fake
−365 (this was a real bug in `local_math.launch_plan`, now fixed). The second finding corrects
§3 above: **most grouped regions return every moment with `takeoff_ms` null** (GB+IE, NL+BE+LU,
SE+DK+FI+NO, IT+ES+PT+GR+MT are fully undated; DE+AT+CH, AU+NZ, MX+AR+CO+CL get exactly one
peak-only moment each), so `GB+IE` produced a completely empty calendar. Those rows are now
emitted as `basis="occurrence"` / `"no ramp data"` rather than dropped, because an empty calendar
reads exactly like "nothing is coming up". Confirmed against the live UI, not just the API: the
`/moments/<name>/` detail page — the only place Pinterest itself shows takeoff/peak timing — is
US-only, and switching its region selector redirects away rather than rendering. Pinterest's own
product has nothing to show for the UK either; the gap is upstream of this codebase.

**3 · Ad targeting.** The `/ads/v4/` path and the `trends/index.js` handler are advertiser-scoped,
so the 24 `l1interests` ids **are** campaign targeting ids and the age/gender enums **are** the
targeting bands. This was inferred from the URL shape and is now **confirmed directly against
Ads Manager** (2026-08-07, manual campaign setup → Ad group → Interests and Keywords → Add
interests): all 24 names and all 24 numeric ids match `constants.INTERESTS` exactly, including
spelling, capitalisation and split (Home Decor `935249274030`, Women's Fashion `948967005229`).
Ads Manager also exposes a **second layer Trends never surfaces**: each of the 24 has 3–28
sub-interests with their own distinct 12-digit ids (Home Decor alone has 19, e.g. `924783655335`
Ceiling, `936029585073` Door) — a deeper targeting tree that only exists on the Ads side.

`hidden_demo_curve()` uses the filter the UI never sends: on category 1002 (Accent tables), 180
days to 2026-07-27, the category overall is shrinking (second half ÷ first half = 0.94, peaked in
February) while **18-24 is growing (1.14) and peaked in July**. Same category, opposite
conclusion, invisible in the product.

**4 · Market intelligence.** `top_products` carries `merchant_name` on every pin, so share-of-shelf
is a count: Runner rugs is Amazon 38% / Walmart 33% / Etsy 14%. The 383-entry taxonomy is a DAG
(`level`, `parent`, `children`, `l2_product_category_ids`), which makes it a usable product
classifier on its own — `Taxonomy.classify()` scores a free-text title against it and returns the
full root-to-leaf path. Walking *down* needs a reverse index: the 14 level-1 verticals are named as
parents but are not entries in the map, so they have no `children` key and the DAG was unwalkable
from the top. Rebuilt from the child side, Fashion resolves to 109 descendants, Home decor 218,
Beauty 79 — overlapping, because a node can hang off more than one L2 parent.

**5 · Historical archive.** `endDate` back-dates cleanly and the response reports the week it
actually snapped to, so a loop reconstructs history Pinterest offers no export for. Six US weeks
archived: **426 distinct terms across 600 table slots — a term holds the growing table for about
1.4 weeks.** That churn is the whole argument for keeping an archive; a weekly snapshot misses
most of what happens. This is the one place that deliberately does *not* take the 100-row table by
default: an archive is only useful if its weeks are comparable, and mixing 50-row and 100-row weeks
would make `entered`/`exited` fire on the boundary rather than on real movement. Pass `limit=100`
to start a deeper archive, then keep every week at 100.

**6 · Audience.** Raw shares are misleading because Pinterest's audience is ~85% female on
everything — the spread across five test terms was 79–93% on gender but 24–68% on the 18-24 band.
`skew()` divides by the batch median so what surfaces is the term that is unusually male or
unusually old *relative to its peers*: `deltarune` at 47% female against an 84% baseline,
`retirement party` at 2.2× on 55-64. Note the shares are rounded to 2dp server-side and sum to
1.00–1.15, so they are not exact percentages.

**7 · Moodboards.** `topics/featured` is the densest response on the surface — one request returns
five topics with description, MoM growth, full series, related terms, pins, **and a precomputed
dominant colour per pin**. A palette is therefore a count, not image processing. `to_html()`
writes a self-contained visual brief; colours are bucketed to a coarse RGB grid so near-identical
pins collapse into ~6 named swatches instead of 24 unique hexes.

It also wires **`/ads/v4/trends/editorial/content/`, which sat in the captures unused since day
one** — six of Pinterest's own written trend stories ("Can't Stop Cross-Stitching", "The Summer of
Jorts"), each with real editorial copy, pins, and the story's keywords for **US, GB+IE and CA in
the same response**. The region path segment is ignored, so that is one request for three markets.
It carries no growth number or series at all, so nothing can be ranked on it — `featured_topics`
says how fast, editorial says what to write.

**8 · Momentum alerts.** A single table is a leaderboard; two are a monitoring product. The diff
emits typed events (`entered` / `exited` / `climbed` / `fell` / `spike` / `seasonality_cross`)
ordered by severity. The spike threshold is a **quantile of the week's own table, not a fixed
number**: a fixed 200% MoM cutoff fired on 41 of 50 rows of the growing table, which is
tautological — growth is that preset's selection criterion. The quantile self-calibrates and holds
output to ~30–45 events a week across both presets. `timeline()` backtests any rule change against
the whole archive before it is wired to anything that notifies a human.

### Verification

```bash
.venv/Scripts/python.exe pinterest/tests/test_products.py     # 54 live checks
```

Every measurement quoted above is one of those checks, not a remembered number. The suite fails by
name if Pinterest changes a shape underneath it — which matters more here than usual, because most
of these products fail by returning a plausible number rather than an error.

A separate pass exercised every public function against degenerate input (empty lists, `None`,
unknown terms, unknown ids, single-row batches, empty regions). Nothing crashed, but three things
were **silently wrong**, which is the failure mode that matters here — all three are fixed and each
now has a regression check:

| Defect | Symptom | Fix |
|---|---|---|
| `plan("GB+IE")` returned `[]` | a whole region's calendar looked like "nothing coming up" | dateless rows emitted with `basis="occurrence"` |
| `sweep(interests=[])` swept all 24 | an empty filter fired 24 live requests | `None` means all, `[]` means none |
| `children("1181")` returned `[]` | the taxonomy could not be walked down from a vertical | reverse index built from `parent_product_category_id` |
