# Pure Pinterest — eight standalone products

`trends.pinterest.com` treated as its own data source. Nothing here imports from `public/`,
`private/` or `core/`, and nothing produces an Etsy-shaped record — contrast with
[`../pipelines/`](../pipelines/README.md), which is the Etsy-facing pillar. Every claim below is
pinned by [`../tests/test_products.py`](../tests/test_products.py) (54 live checks); the full
write-up with measured numbers lives in [README §9](../README.md#9-pure-pinterest--the-eight-standalone-products) —
this file is the function-level reference for working *in* this folder.

```bash
.venv/Scripts/python.exe pinterest/products/cli.py                 # list all eight
.venv/Scripts/python.exe pinterest/products/cli.py keywords "halloween nails" --depth 2
.venv/Scripts/python.exe pinterest/products/cli.py calendar US --ics
.venv/Scripts/python.exe pinterest/products/cli.py targeting
.venv/Scripts/python.exe pinterest/products/cli.py market "runner rugs"
.venv/Scripts/python.exe pinterest/products/cli.py history --weeks 12
.venv/Scripts/python.exe pinterest/products/cli.py audience "grill recipes" "prom hair"
.venv/Scripts/python.exe pinterest/products/cli.py moodboard --html
.venv/Scripts/python.exe pinterest/products/cli.py alerts --refresh
```

Every module is also runnable directly (`python pinterest/products/keyword_research.py <seed>`) —
[`cli.py`](cli.py) just makes the eight discoverable as one thing.

---

## 1 · [`keyword_research.py`](keyword_research.py) — content research for any niche

| Function | What it does |
|---|---|
| `long_tail(api, query, country="US", min_level=0)` | `prefix_match` children ranked by `velocity()`. One request. |
| `neighbours(api, seed, country="US", only_novel=False)` | `related_terms` co-searches; `only_novel=True` keeps only terms sharing no word with the seed. |
| `expand(api, seed, country="US", depth=1, only_novel=False)` | Recursive `long_tail` + `neighbours` — 2 requests per node, series ride along free. |
| `sweep(api, preset="growing", interests=None, country="US", limit=TOP_TRENDS_LIMIT_MAX)` | Discovery table per interest. `interests=None` = all 24, `interests=[]` = none. `limit` defaults to the server max of **100**, not the UI's 50. |
| `cross_interest(rows)` | Terms ranking inside more than one interest — invisible from any single table. |

Rows are `{"term", "source", "level", "velocity", "noisy", "peak", "weeks", ...}`. `noisy=True`
flags a series whose last 8 weeks never exceed 25 on the 0–100 scale — velocities off a 1-unit
move on a near-zero series read as +900% and are not to be trusted.

**Measured:** a depth-1 expansion costs **zero** `/metrics/` calls (prefix/related responses
carry the series already). `sweep()` at `limit=100` across all 24 interests: **1208 unique terms**
vs 734 at the UI's default 50, for the same 24 requests.

## 2 · [`content_calendar.py`](content_calendar.py) — dated publishing plan

| Function | What it does |
|---|---|
| `plan(api, country="US", lead_weeks=6, with_terms=False, now=None)` | Every moment as a dated plan, soonest deadline first. |
| `upcoming(rows, weeks=12)` | Rows whose `list_by` falls inside the horizon; tolerates dateless rows. |
| `to_ics(rows, path=None)` | Writes a real `.ics` — two all-day events per dated moment. |

A row's `list_by` is `takeoff − lead_weeks`. `basis` is `"takeoff"` when Pinterest supplied real
dates, or `"occurrence"` when it didn't — see the region table below. Dateless rows carry
`status="no ramp data"` rather than being dropped, because a silently empty calendar for a whole
region reads exactly like "nothing is coming up".

**Region coverage** (re-verified against the live UI, 2026-08-07 — not just the API):

| Regions | What you get |
|---|---|
| `US` `CA` `BR` `MX` `IT` `ES` `FR` `DE` `CO` `AR` | full `takeoff_ms` + `peak_ms` |
| `DE+AT+CH` `AU+NZ` `MX+AR+CO+CL` | exactly **one** moment gets `peak_ms`; `takeoff_ms` stays null everywhere |
| `GB+IE` `NL+BE+LU` `SE+DK+FI+NO` `IT+ES+PT+GR+MT` | names only, every date field null |
| `JP` | empty list |
| `AU` `NL` `IE` `GB` `ZZ` | 400 — no standalone code for any of these |

The live `/moments/<name>/` page — the only place Pinterest's own UI shows this timing — is
**US-only**; switching its region selector redirects away instead of rendering. The gap is
upstream of this codebase, confirmed via the Pinterest UI itself, not inferred from the API alone.

**Measured:** every approaching US moment drifts **exactly 0 days** against last year — Pinterest's
"prediction" is last year's date + 365.

## 3 · [`ad_targeting.py`](ad_targeting.py) — Pinterest Ads research

| Function | What it does |
|---|---|
| `interest_board(api, country="US", preset="growing", interests=None)` | Median MoM/YoY/seasonality per interest — one call per interest, ranked. |
| `demo_split(api, terms, country="US")` | Dominant age band + gender per term, both Ads-enum (`AGE_25_34`) and flat-REST (`[4]`) spellings. |
| `hidden_demo_curve(api, category_id, country="US", bands=None, days=180, event="OUTBOUND_CLICK")` | Shopping curve sliced by age band — a filter the UI never sends. |
| `brief(api, country="US", preset="growing", top_interests=5)` | Top interests + the audience behind each one's top terms, in one call. |

**Confirmed directly against Pinterest Ads Manager (2026-08-07, manual campaign setup →
Interests and Keywords):** all 24 `constants.INTERESTS` ids are the exact ids Ads Manager uses
for interest targeting — name, spelling and id match exactly (Home Decor `935249274030`,
Women's Fashion `948967005229`). Ads Manager additionally exposes a second layer Trends never
surfaces: each of the 24 has 3–28 sub-interests with their own distinct ids (Home Decor has 19,
e.g. `924783655335` Ceiling).

**Measured:** category 1002 (Accent tables) is shrinking overall (0.94 half-over-half, peaked
February) while its 18-24 slice is growing (1.14, peaked July) — opposite conclusions, invisible
in the product because the UI always sends empty `age_bucket`/`gender` arrays.

## 4 · [`market_intel.py`](market_intel.py) — merchant share + the taxonomy

`class Taxonomy(api, country="US")` wraps the 383-entry category map:

| Method | What it does |
|---|---|
| `.name(cid)` / `.path(cid)` | Friendly name / root-to-leaf path. |
| `.children(cid, deep=False)` | Direct or full-subtree children. Falls back to a **reverse index** built from `parent_product_category_id` — the 14 level-1 verticals are referenced as parents but aren't entries in the map, so they have no `children` key of their own and were unwalkable from the top before this. |
| `.leaves()` | Every category with no children (282 of 383). |
| `.search(text)` / `.classify(title, top=3)` | Substring name search / scored free-text classification. |

Module functions: `merchant_share(api, category_id, ...)` (share-of-shelf by `merchant_name`,
one request), `landscape(api, category_ids, ...)` (cross-category merchant presence),
`demand_table(api, country="US", event="OUTBOUND_CLICK")` (growth + relative volume + intent
ratio for every category, one request).

**Measured:** Runner rugs = Amazon 38% / Walmart 33% / Etsy 14%. Fashion resolves to 109
descendants via the reverse index, Home decor 218, Beauty 79 (overlapping — a node can hang off
more than one L2 parent).

## 5 · [`history.py`](history.py) — the archive Pinterest doesn't offer

`class HistoryDB(db_path=DB_PATH)` — SQLite at `pinterest/data/history.db`.

| Method | What it does |
|---|---|
| `.write(week, country, preset, rows, interest="")` | `INSERT OR REPLACE` — idempotent, since the cache makes re-running a week free and therefore likely. |
| `.weeks(country="US", preset=None)` / `.table(week, ...)` | Archived weeks / one week's full table. |
| `.rank_history(term, ...)` | Where a term sat, week by week — the series Pinterest itself cannot return (its `/metrics/` gives volume, never rank). |
| `.longevity(country="US", preset="growing", min_weeks=2)` | Terms by how many distinct weeks they held a table slot — separates a real trend from a one-week spike. |

`week_before(end_date, weeks)` steps back in whole weeks (Pinterest's weeks are Monday-anchored).
`backfill(api, weeks=8, country="US", presets=("growing","seasonal"), db=None, limit=None)` walks
`endDate` backwards, one request per week per preset, trusting the response's own `endDate` over
the one requested (the server snaps to its nearest complete week). `limit` deliberately defaults
to `None` (50) rather than the 100-row ceiling — an archive is only useful if its weeks are
comparable, and mixing row counts would make `entered`/`exited` fire on the boundary instead of on
real movement. Pass `limit=100` to start a deeper archive, then keep every week at 100.

**Measured:** six US weeks archived → 426 distinct terms across 600 table slots — a term holds
the growing table for about 1.4 weeks.

## 6 · [`audience.py`](audience.py) — who searches a term

| Function | What it does |
|---|---|
| `profile(api, terms, country="US")` | `/demographics/` batch — mean age, dominant band, `under_35`/`over_55` shares. |
| `baseline(rows)` | Median share per band across a batch — the yardstick, resistant to one outlier term. |
| `skew(rows, against=None)` | Each term's shares as a multiple of the baseline. 1.0 = typical for this batch. |
| `category_profile(api, category_ids, ...)` | The shopping-side equivalent, keyed by category id, plus that category's own related search terms. |

Note: age-band shares are rounded to 2dp server-side and sum to 1.00–1.15, not exactly 1 — do not
treat them as exact percentages. `profile()`'s `mean_age` divides by the observed total rather
than assuming 1.0.

**Measured:** gender is nearly flat across unrelated terms (79–93% female); age is where the
signal is (24–68% on the 18-24 band). `deltarune` sits at 47% female against an 84% batch
baseline — the term that looks unremarkable on gender alone is the most distinctive on it.

## 7 · [`moodboard.py`](moodboard.py) — visual trend briefs

| Function | What it does |
|---|---|
| `board(api, interest="All", country="US")` | 5 topics from `featured_topics()` — description, MoM growth, full series, pins, palette, related terms. One request. |
| `palette(topic, top=6)` | Dominant colour families from the pins' precomputed `color` field — a count, not image processing. |
| `editorial(api, country="US")` | Pinterest's own **written** trend stories via `editorial_content()` — real copy, pins, and keywords for **US + GB+IE + CA in one response**. No growth number, no series; complements `board()` rather than duplicating it. |
| `all_boards(api, country="US", with_editorial=True)` | Every dropdown interest (15 requests) plus the editorial set — 16 total, cached thereafter. |
| `to_html(boards, path=None, title=...)` | Self-contained visual HTML page — hotlinked `i.pinimg.com` images, no external assets. |

**Found:** `/ads/v4/trends/editorial/content/` sat in the original captures marked "Unwired"
since day one — now wired. The region path segment is ignored (all three regions return
identical titles); the per-region split lives inside each story's `keywords` dict instead.

## 8 · [`alerts.py`](alerts.py) — week-over-week momentum feed

| Function | What it does |
|---|---|
| `diff(previous, current, rules=None)` | Two archived weeks (from `history.HistoryDB.table()`) → typed events, most severe first. |
| `latest_diff(db, ...)` | Diff the two most recent archived weeks; `[]` if fewer than two are stored. |
| `timeline(db, ...)` | Every consecutive week pair — the backtest for a rule change before it notifies anyone. |
| `watchlist(db, terms, ...)` | Rank history for specific named terms. |

Event kinds: `entered` / `exited` / `climbed` / `fell` / `spike` / `seasonality_cross`, each with
a `severity` used to sort. `RULES["mom_quantile"]` (default 0.9) sets the spike bar as a
**quantile of the week's own table**, not a fixed number — a fixed 200% MoM cutoff fired on 41 of
50 rows of the growing table, because growth is that preset's own selection criterion, making an
absolute threshold tautological there.

---

## Verification

```bash
.venv/Scripts/python.exe pinterest/tests/test_products.py     # 54 live checks
```

Every number quoted above is one of those checks, not a remembered figure — this class of product
fails by returning a plausible-looking wrong answer rather than an error, so nothing here is
asserted from memory. A separate pass exercised every public function against degenerate input
(empty lists, `None`, unknown terms/ids, empty regions); it caught three real defects, all now
fixed and regression-tested — see [README §9](../README.md#9-pure-pinterest--the-eight-standalone-products)
for the table.
