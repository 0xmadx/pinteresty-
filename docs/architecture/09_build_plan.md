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
| 1 | **DISCOVER** — find candidates | ⚠️ | front door (`get_trending_terms`) never called; Pinterest wide crawl unwired |
| 2 | **MEASURE** — volume, CVR, supply, competitors, saturation | ✅ | *(fixed 2026-08-12 — see §3)*; pagination and a filter registry still missing |
| 3 | **JUDGE** — profit gate, survivor bound, gaps, ranking | ✅ | done and tested |
| 4 | **TIME** — takeoff → "list by Sept 22" | ❌ | both halves exist, not connected |
| 5 | **DECIDE** — where to list | ❌ | designed (D-11), deferred by D-21 |
| 6 | **GENERATE** — title, tags, price, flaws | ⚠️ | tags done; no demographics injection |
| 7 | **TRACK** — launches, ranks, deltas | ✅ | built, never run |
| 8 | **LEARN** — did predictions hold | ✅ | schema ready, needs 10 launches |

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

---

## 4. Build order

### Phase 0 — Settings and the clock

Everything here is worth more the earlier it happens, because it is the input to
everything else or it accumulates over time.

| # | Build | Why |
|---|---|---|
| 1 | **Settings** — config file + CLI first, web page later | D-23. Every profit verdict depends on these and they are currently defaults. A config file gets real numbers into `profit.py` today rather than after a UI exists. |
| 2 | **Competitor outcome tracker** — shop inventory + per-listing review velocity | D-26. **Worthless if started late** — it needs weeks of history. Also the only unbiased outcome dataset available (partially solves B-04). |
| 3 | **Scheduler** — daily shop delta, 3×/week ranks, weekly Pinterest bridge | Every signal is a time-series. Value compounds only with time, and the clock has not started. |
| 4 | **Seed 2–3 shops + one bridge run** | The daily delta is the only genuinely measured sales number; momentum is `None` until the bridge runs. Track **some mid-tier shops, not only stars** — tracking winners only re-creates survivorship bias. |

#### Settings has two tiers (D-25)

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
| 7 | **TIME loop** — `moments` → Etsy `holiday` filter → `list_by` | The calendar's engine. Both halves exist. |
| 8 | **DISCOVER front door** — `get_trending_terms` + Pinterest wide | Landing page needs candidates without a keyword typed. |
| 9 | **Forecast** — `predicted_days=56` + the missing `split_forecast()` | The ⚪ WATCHING row. Pinterest ships a 91-day forecast nobody uses. |
| 10 | **Demand-in-bracket** | 🎯 "gap found" can never fire without it. |
| 11 | **Filter registry** — product-type gated, gates the *request* | Stops asking digital products about shipping; replaces 150 lines of pasted calls. |

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
| O-3 | Which signals survive a move to official APIs | operator |
| O-6 | Etsy public parameter names (`page`, `min`/`max`, `attr_2/3`) — read them off Etsy's filter UI rather than guessing | operator |
| — | Real fee schedule, COGS, hourly rate | operator → Settings (Phase 0) |
| — | 2–3 competitor shops to track | operator |
| — | Sign out of Etsy: session keys are in git history (`registry.json`) | operator |
| — | One live Pinterest run to confirm the cache migration | operator |
