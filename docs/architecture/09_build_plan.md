# 09 — Build Plan

What we are building, in what order, and why. Decided with the operator 2026-08-12;
the four choices that shaped it are recorded as D-20…D-23 in `DECISION_LOG.md`.

---

## 1. The product

> **A weekly calendar that says what to list, when to list it, and whether it will
> make money — with a keyword search as the second door.**

Not a niche checker. Every competitor is a niche checker; the calendar is the part
nobody else can build, because it needs Pinterest's takeoff dates joined to Etsy's
real demand and a profit model that can say no.

**Scope decisions:**

| Question | Decision |
|---|---|
| Home screen | **Calendar first**, keyword search always in the top bar (D-20) |
| Channels | **Etsy only for now**, but the data model and docs stay channel-aware so Shopify/Pinterest selling is not a rewrite (D-21) |
| Product types | **All three** — digital, physical, personalized (D-22) |
| Fees / costs | **Settings page ships first**; nothing is hardcoded (D-23) |

Because all three product types are in play, **product-type detection is mandatory,
not a nicety**: the gap dimensions that are even *askable* differ per type (a download
has no delivery window), and the profit model's margin floor and capacity ceiling
differ too. The system cannot assume, and the operator should not have to say it every
time.

---

## 2. The loop

```
   ┌────────────────────────────────────────────────────────────┐
   │                                                             ▼
1 DISCOVER → 2 MEASURE → 3 JUDGE → 4 TIME → 5 DECIDE → 6 GENERATE → 7 TRACK → 8 LEARN
   free        free       local     free     local       free        free      local
```

| # | Stage | Status | Gap |
|---|---|---|---|
| 1 | **DISCOVER** — find candidates | ✅ | `discover.py` front door works; Pinterest wide crawl still unwired |
| 2 | **MEASURE** — volume, CVR, supply, competitors, saturation | ✅ | daily `keyword_sweep` running; pagination still missing |
| 3 | **JUDGE** — profit gate, survivor bound, gaps, ranking | ✅ | gaps can now resolve POSITIVELY (D-34); only 3 filter dimensions are trustworthy (D-32) |
| 4 | **TIME** — takeoff → "list by Sept 22" | ✅ | **done 2026-08-19** — `calendar_engine.py`. Moments were being computed and discarded; see §3b |
| 5 | **DECIDE** — where to list | ❌ | designed (D-11), deferred by D-21 |
| 6 | **GENERATE** — title, tags, price, flaws | ⚠️ | tags done; no demographics injection |
| 7 | **TRACK** — launches, ranks, deltas | ✅ | daily scheduler running since 2026-08-19 |
| 8 | **LEARN** — did predictions hold | ⚠️ | outcome capture built (sales/revenue, not just rank); **0 launches recorded** |

**Every stage is now built.** What remains is a UI, the dimensions the filter audit
took away, and time — the LEARN loop cannot start until launches exist, and no
amount of building substitutes for that.

---

## 3. The finding that reset everything

On 2026-08-12 the private API was called live for the first time. Every table in the
system held 0 rows, and three explanations had been offered: the quota, a broken
import, and missing scheduling. **All three were wrong.**

Etsy returns **snake_case**. Every consumer read **camelCase**:

| API returns | Code read | Got |
|---|---|---|
| `search_volume` | `searchVolume` | `None` |
| `avg_total_listings` | `avgTotalListings` | `None` |
| `query_cvr` | `cvr` (an ordinal bucket) | `0` |
| `term_summaries` | `termSummaries` | `[]` |
| `competitive_research_listing_cards` | `competitiveResearchListingCards` | `[]` |

Seven modules — the entire private tier — fetched correct data and read empty values
out of it. Fixed by centralising the shape in `parse_results_data` /
`parse_term_summaries` / `normalise_listing_card`, which accept both spellings so it
cannot drift again.

**The lesson, and it is the reason this doc exists:** every prior explanation was
plausible and reasoned from documents. One live call settled it in seconds. *Probe the
real response before theorising about why data is missing.*

Three fields nobody had ever read came with it: `wow_data` (Etsy's **own**
week-over-week momentum), `similar_search_terms`, and `market_gap_recommendations`
(Etsy's own gap analysis).

> **Correction, 2026-08-15.** Two of those three are dead. Probed on `felt garland`,
> `mom necklace` and `christmas ornament`, `similar_search_terms` returned
> `total_results_count: 0` every time and `market_gap_recommendations` was `null`. The
> keys exist in the response schema; Etsy returns nothing in them. Only `wow_data`
> carries a real value.
>
> This is D-24 applied to a claim *this document* made. "Present in the response" was
> read as "populated", and the difference was never checked — the same shortcut that
> made the camelCase bug survive three explanations. The 🎯 gap feature must be built
> from measured supply and demand, not handed over by Etsy.

---

## 3b. The second finding that reset the calendar (2026-08-19)

The TIME loop was recorded above as "both halves exist, not connected". The halves
*were* connected — **the join discarded everything.**

`trends_bridge` iterated the 86 **featured topics** and attached a takeoff date
only when a topic happened to share a moment's name. Measured live: 86 topics, 13
moments, and the overlap is **zero** — topics are "Senior Spirit Jeans and Pants",
moments are "christmas". So all 13 moments were fetched, their launch plans
computed in full, and dropped. `takeoff_timestamp` was NULL in all 84 stored rows.

`christmas` sat in that discarded set carrying `list_by 2026-09-16` — the exact row
this product exists to show, calculated correctly and deleted.

**The peak was being dropped too**, and it is what separates LATE from MISSED. And
while it was missing, `classify` still answered "late, not missed" — a claim *about
the peak*, made without one, in the optimistic direction. It put Independence Day
(April) on the list-now row in August. There is now an `UNTIMED` state: deadline
gone, peak unmeasured, cannot tell.

This is D-24 again, in a third costume. The doc said "not connected" and nobody
checked whether the connection existed and leaked.

---

## 4. Build order

### Phase 0a — Turn the vault green (blocks everything below)

Added 2026-08-14 after verifying the session layer against the running system, and
**closed the same day**. The access layer was rebuilt onto Redis (D-28); the vault
appeared empty, but Python was reading a *different Redis on the same port* (D-30).
Repointed, the vault is green and the private tier is verified live.

Still true and worth remembering: `get_valid_account` waits in an unbounded loop, so a
genuinely empty pool **hangs** a run rather than failing it.

| # | Do | Owner |
|---|---|---|
| 0 | `python -m core.vault_status` — the one-second check | ✅ built |
| 1 | Point `REDIS_URL` at the container vault, not the shadowed `localhost` (D-30) | ✅ done |
| 2 | **Vault green + live private call verified** — `mom necklace` → 12,867 / 351,677 / 20 cards | ✅ **2026-08-14** |
| 3 | Stop the stray native Redis so `localhost` is stable across reboots | operator |
| 4 | Re-beam profiles from an extension build that sends `user_agent` (S-9 — the UA fix exists in code, not in the data) | operator |
| 5 | Set the extension profile **role** explicitly — 13 of 16 private profiles still have tokens but no cookies (S-1) | operator |

Full diagnosis, defect list S-1…S-8, and the public/private boundary:
**`10_session_layer.md`**. The defects there are **operator-owned** — the access layer
is read-only to agents.

✅ **Live data is available again.** Phase 0 and Phase 1 can now be built *and
verified* rather than built blind.

### Phase 0 — Settings and the clock

Everything here is worth more the earlier it happens, because it is the input to
everything else or it accumulates over time.

| # | Build | Why |
|---|---|---|
| 1 | ~~**Settings** — config file + CLI~~ | ✅ **done 2026-08-14** — `core/settings_store.py`, `config/settings.json`, 28 assertions. See below. |
| 2 | ~~**Competitor outcome tracker**~~ | ✅ **done 2026-08-15** — `competitor_tracker.py`, 31 assertions (`ea425a1`, `e6b17b5`) |
| 3 | ~~**Scheduler**~~ | ✅ **done 2026-08-15** — `core/scheduler.py`, 22 assertions |
| 4 | **Seed shops + one bridge run** | ⚠️ **partly done** — bridge now runs weekly and writes 99 rows (86 topics + 13 **moments**). 2 shops seeded, both **stars**; a mid-tier shop is still missing (B-01). |
| 5 | ~~**The clock actually running**~~ | ✅ **done 2026-08-19** — `run_scheduler.cmd` registered as the Windows task `EtsyScrapperDaily`, 07:00. Five jobs: shop_sweep, keyword_sweep, calendar (daily), rank_check (56h), pinterest_bridge (weekly). |

#### What the wire taught us building item 2

Two findings no document could have supplied, both caught only by probing:

* **Shop pages carry no per-listing review counts.** Zero `clg-static-review-stars`
  on a shop grid, so the outcome signal costs one request *per listing* and cannot be
  batched out of the inventory sweep. `sweep_shop` is two-tier for this reason.
* **`Product.aggregateRating.reviewCount` is not always the listing's.** On some pages
  it holds the **shop's** total — measured, 7 of 12 shopflowerlane listings returned
  4580 against a shop showing 4.6k. Recorded as-is, each would have looked like a
  listing that gained the shop's entire review history overnight: seven fabricated
  runaway winners inside the one dataset built to be unbiased. Counts at or above 90%
  of the shop total are now refused.

#### Scheduler design decisions

* **Due-ness is measured from the last *successful* run, and persisted.** "Next run =
  now + 24h" silently drops every window the machine was asleep for, and afterwards the
  absence is indistinguishable from a day the shop did not change.
* **Refused ≠ failed.** A missing session means *open Chrome*; a failure means the site
  or the code broke. Collapsing them sends the operator hunting a bug that is not there.
* **One job failing never stops the others** — losing the Pinterest bridge is no reason
  to skip the shop delta.
* **No daemon.** `--once` runs what is due and exits, for Task Scheduler or cron.

```bash
.venv/Scripts/python.exe -m core.scheduler --list
.venv/Scripts/python.exe -m core.scheduler --once
```

#### Settings has two tiers (D-26)

```
GLOBAL  (set once)              PER-PRODUCT PROFILE  (named, pick one per candidate)
  etsy fee rates                  "Digital printable"   COGS 0     ship 0     labour 0
  hourly rate                     "Ceramic mug"         COGS 8.50  ship 4.20  labour 3 min
  hours available / week          "Custom name sign"    COGS 12    ship 6     labour 45 min
```

`profit.verdict()` already takes exactly the right-hand shape as `product_profile`, so
this is storage plus a picker. For personalized goods the labour minutes drive the
**weekly capacity ceiling**, which is usually what actually binds — so the profile
changes the verdict, it is not decoration.

⚠️ **No LLM estimates these numbers.** Classification (product type, occasion) and
extraction (a price off a supplier page the operator pastes) only. A confidently wrong
COGS flows straight into a go/no-go.

#### Settings carry provenance — the part that was not in the original plan

Building it exposed a gap the plan had missed. `verdict()` returns the **same shape**
whether its fees came from the operator or from `profit.py`'s placeholders:
arithmetically identical, worth completely different amounts of trust. A `go` resting
on guessed fees was indistinguishable from a real one — this system's defining failure
sitting directly under the go/no-go.

So settings record **which fields a human confirmed**, and that provenance rides into
every verdict:

```python
v = profit.verdict(price=24.0, demand_units_per_week=12,
                   **settings.verdict_kwargs("Ceramic mug"))
v["go"]           # True
v["provisional"]  # True  ← six verdict-critical values are still defaults
```

Confirming is an *act*, not a value change: re-confirming a default at its current
value counts, because the missing thing was a human checking it, not a different
number. Confirmation moves the trust label and never the arithmetic — pinned by test.

Two refusals worth noting, both `refuse rather than guess`:

* an **unknown profile name raises** — silently defaulting to a zero-cost profile
  would make every unmatched candidate a guaranteed `go`
* a **personalized profile without `labor_minutes` is rejected** — those minutes *are*
  the weekly capacity ceiling, and `0` silently promises unlimited output by hand

```bash
.venv/Scripts/python.exe -m core.settings_store show
.venv/Scripts/python.exe -m core.settings_store set operator.hourly_rate 30
.venv/Scripts/python.exe -m core.settings_store profile add "Ceramic mug" \
    --type physical --cogs 8.50 --shipping 4.20 --labour 3
```

### Phase 1 — Fill the tables

| # | Build | Why |
|---|---|---|
| 5 | **Product-type detection** | Mandatory now that all three types are in scope (D-22). One `is_digital` request answers it; an LLM classifier is the fallback for ambiguous cases. |
| 6 | **A real crawl** on 3–5 seed keywords | Proves the repaired private tier end to end and gives the UI something to render. |
| 7 | **Pagination** (`page`) | Parser already reads `total_pages`; nothing requests page 2. 4× the data for one parameter. ⚠️ the parameter *name* is unverified — see O-6. |

**What the competitor tracker needs (item 2), since it is new:**

| Piece | Status |
|---|---|
| Shop totals + daily sales delta | ✅ `shop_observations` |
| **A shop's listing inventory** | ❌ `ShopScraper` only fetches totals |
| **Per-listing review velocity** | ⚠️ `reviews_api` returns dates; nothing tracks them over time |
| **Match their listings → your watched niches** | ⚠️ `term_join.py` already does the matching; nothing calls it for this |

The valuable output is *"they listed it 3 weeks ago and it has 12 reviews already"* —
not *"they listed something"*.

### Phase 2 — The spine

| # | Build | Why |
|---|---|---|
| 7 | ~~**TIME loop**~~ | ✅ **done 2026-08-19** — `calendar_engine.py`, 30 assertions. NOT via the `holiday` filter, which the audit found Etsy silently ignores (D-32); the join is moment → takeoff → `list_by`, with watched terms and their measured demand attached. |
| 8 | ~~**DISCOVER front door**~~ | ✅ **done 2026-08-15** — `discover.py`, 18 assertions. 28 candidates, no keyword typed. Two findings below. |
| 9 | **Forecast** — `predicted_days=56` + the missing `split_forecast()` | The ⚪ WATCHING row. Pinterest ships a 91-day forecast nobody uses. |
| 10 | ~~**Demand-in-bracket**~~ | ✅ **done 2026-08-19** — `bracket_demand.py`, 31 assertions. Inferred from the review counts of the listings occupying the bracket, because Etsy reports volume per TERM and never per bracket (D-34). |
| 11 | **Filter registry** — product-type gated, gates the *request* | ⚠️ **superseded in scope by D-32.** A trust registry now exists and gates the *verdict*; 9 of 12 filters cannot be believed. The remaining work is gating the *request* by product type, which is now mostly moot — there are only 3 usable dimensions left to ask about. |

#### What DISCOVER turned up

**Only 7 of 15 probed taxonomy ids are populated** — 1, 66, 199, 323, 891, 1429, 1633.
Jewelry, Clothing and Craft Supplies return nothing, so the id list is a parameter
rather than a constant, and two of my guesses about which id was which category were
wrong.

**The list is Etsy's picks, not the top of the market.** Etsy chose these by criteria
it does not publish, so every candidate carries `basis="etsy_curated"`. Treating it as
"what is trending" rather than "what Etsy is promoting" would inherit someone else's
agenda as market truth — B-01 applied to candidate generation instead of survivors.

⚠️ **The seasonal join produced nothing, and that is honest.** None of the 28 trending
terms matched any of Pinterest's 13 moments. "back to school" (211k) and "fall png"
(44k) are plainly seasonal, but Pinterest's calendar is **holiday-centric** — there is
no back-to-school or autumn moment in it. The join returns `evergreen` rather than
reaching for the nearest holiday, which would attach a September deadline to a term
that does not have one.

**Open:** the moment source is the limit here, not the join. Either a second seasonal
source is needed, or moments must be derived from the terms' own series (a
back-to-school curve is visible in the data even when nobody names the moment).

### Phase 2b — winnability, and the SEO half of being right (D-31)

Added 2026-08-15. The system was enforcing *is this number true* and not *is this the
number to show first*. `discover` ranked by volume and put a 2.16M-listing term above
the only winnable one on the screen.

| # | Build | Status |
|---|---|---|
| — | **Winnability ranking** — demand/listing + CVR, ratio exposed not scored | ✅ done, 30 assertions |
| — | `etsy-seo-and-opportunity` skill — the fourth review lens | ✅ done |
| a | **Rank feasibility per listing** — can *this shop* reach page one, given its authority? | ⬜ |
| b | **Funnel-stage labelling** — impressions vs clicks vs orders on every metric | ⬜ |
| c | **CTR-side signals** — price position, photo count, review count. The biggest lever, and the one measured least | ⬜ |
| d | **Long-tail expansion** — from a wall term to its winnable children | ⬜ |

**Why (c) matters most of the remaining four:** tags earn an *impression*; the photo and
the price earn the *click*. Everything this repo generates today (titles, 13 tags) acts
at the impression stage, so a listing with a click problem gets confident, useless
advice.

### Phase 2c — what the filter audit took away (added 2026-08-19)

D-32 left three trustworthy dimensions: `delivery_days`, `gift_wrap`,
`is_personalizable`. The gap analysis was designed around ten. This is the honest
consequence and it needs a decision, not a workaround.

| # | Build | Status |
|---|---|---|
| a | **Substitute measurements from listing pages** — origin, colour and rating read per listing rather than from SERP counts, the way `sample_origins` already replaced `locationQuery` | ⬜ |
| b | **Or: accept a three-axis gap analysis and say so** in the output, rather than showing a thin dimension list as if it were the whole picture | ⬜ |
| c | **Re-audit on a schedule** — verdicts go stale after 90 days; Etsy changes | ⬜ |

**(a) is the better answer where it is affordable.** Per-listing measurement costs
one request per listing and returns the truth; a SERP count costs one request and
returns a number that may not be a share of anything. The towel work proved the
pattern: `sample_origins` found a Turkish seller that Etsy's country filter cannot
even express.

### Phase 3 — Pinterest's unused half

| # | Build | Why |
|---|---|---|
| 12 | **`OUTBOUND_CLICK` vs `SAVE`** | Purchase intent vs aspiration. No Etsy equivalent at any price. |
| 13 | **Demographics → tags** | Audience language in listings. No Etsy equivalent. |
| 14 | **383-category DAG** | Pinterest's own clustering; replaces LLM guessing. |
| 15 | **Community-relative momentum** | Rising faster than its community = real trend; rising with it = the season. |

### Phase 4 — Screens

| # | Screen | Notes |
|---|---|---|
| 16 | **Settings** | already Phase 0 — the data side |
| 17 | **Calendar** (home) | 🔴 list now · 🟡 list by · ⚪ watching |
| 18 | **Cockpit** | three source cards → verdict → gap → plan |
| 19 | **Blueprint** | title, 13 tags, price band, flaws to solve |
| 20 | **Performance** | last — needs launch history to exist |

### Deferred by decision

| Item | Why deferred |
|---|---|
| **Where-to-list (D-11)** | D-21 — Etsy-only for now. Keep the data model channel-aware. |
| **Source contracts (D-05)** | Step 7 of `02_design_approach.md` was skipped; the join went straight to the database. Revisit if a second marketplace is added. |
| **M-6 free/metered calibration** | Never built, and pointless without a quota (D-14). Delete the claim. |

---

## 5. What makes it defensible

Not the data — anyone can scrape. The **three refusals**:

1. **It says no.** The profit gate rejects real demand when the operator would not make
   money. No competitor does this; they would rather show a big number.
2. **It admits blindness.** "These are survivors." "This is an estimate." "This ranking
   carries no information."
3. **It checks itself.** Predictions are logged, outcomes tracked, and control launches
   (`is_control`) test what it *rejected* — so it can discover it was wrong.

---

## 6. Open, and who owns it

| # | Item | Owner |
|---|---|---|
| **S-1** | **Set the extension profile role — the vault is red and nothing can fetch** | **operator, first** |
| S-5 | Rotate the hardcoded `super_secret_key_123` before any non-localhost deploy | operator |
| O-3 | Which signals survive a move to official APIs | operator |
| O-6 | Etsy public parameter names (`page`, `min`/`max`, `attr_2/3`) — read them off Etsy's filter UI rather than guessing | operator |
| — | Real fee schedule, COGS, hourly rate | operator → Settings (Phase 0) |
| — | 2–3 competitor shops to track | operator |
| — | Sign out of Etsy: session keys are in git history (`registry.json`) | operator |
| — | One live Pinterest run to confirm the cache migration | operator |
