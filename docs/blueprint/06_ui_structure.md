# 06 — UI / Web Structure

A single-page app over the read-only API. Decision-first, not data-first: the user
gets verdicts and plans, and drills into the layers only when they want to. The
structure below is the cockpit from earlier, formalized.

---

## Information architecture

```
┌─ TOP BAR ──────────────────────────────────────────────────────┐
│  logo   [ keyword search ]  or  [ paste listing URL ]   ⌾ country │  global re-scope
├──────────┬──────────────────────────────────────────────────────┤
│ OUTWARD  │                                                        │
│ Discover │   the main content area — changes per view             │
│ Radar    │                                                        │
│ Calendar │                                                        │
│ Market   │                                                        │
│ X-ray    │                                                        │
│ ─────────│                                                        │
│ INWARD   │                                                        │
│ My Shops │                                                        │
│ Listings │                                                        │
│ Perform. │                                                        │
│ ─────────│                                                        │
│ Settings │                                                        │
└──────────┴──────────────────────────────────────────────────────┘
```

**Two clusters.** Outward views analyze the market (FIND/JUDGE). Inward views
analyze *your* shops (OPERATE/LEARN). Country is a **global selector** that
re-scopes every view, not a view itself.

---

## The views

| View | Mode | Shows | Reads from Gold |
|---|---|---|---|
| **Discover** | FIND | ranked candidate pool; score + confidence + drivers; filter/sort | `scores`, `candidates` |
| **Cockpit** (a candidate) | JUDGE | the decision screen: 3 sources → verdict → profit + gap → where-to-list → launch plan | `candidates`, `scores`, `launch_plans` |
| **Radar** | FIND | this week's momentum feed; typed alerts; the archive | `alerts`, `trends` |
| **Calendar** | FIND | dated launch plan; list-by dates; .ics export | `launch_plans` |
| **Market** | JUDGE | SERP filter profiles; shop leaderboards; concentration; merchant share | `listings`, `shops` |
| **X-ray** | JUDGE | one listing fully analyzed; the 13-candidate-keyword breakdown | `listings`, `candidates` |
| **My Shops** | OPERATE | your shops' health; Star Seller metrics; portfolio mix + capacity | `shops`, own `listings` |
| **My Listings** | OPERATE | rank tracking (organic vs absolute); own-CVR vs niche; tag effectiveness | `rank_observations`, `launches` |
| **Performance** | LEARN | prediction vs actual; estimate error ratio; weight tuning | `launches` |
| **Settings** | — | costs, labor-hours, fee rates, CAC ranges, source config | config |

> **Settings is load-bearing**, not decoration — the profit model can't run without
> your costs, labor-hours, and fee rates. Treat it as a first-class view.

## Two layers of language — market surface over honest engine

The engine speaks in percentiles, guards, and provenance. The **user** speaks in
sales, trends, and profit. The UI translates — without lying.

| Surface (what the user reads) | Engine (what's underneath) |
|---|---|
| "🔥 310 sales in the last 7 days across top 10" | daily delta + ratio estimator (survivor-flagged) |
| "📈 Trend detected 6 weeks before peak — list by Sept 12" | Pinterest momentum → history archive timing |
| "💰 $8.40 profit per unit after fees" | profit calculator, per product type |
| "🎯 Gap: fast shipping + personalized — 3 competitors" | 7-dimension gap finder + empty-bracket check |

**The rule:** market language on the surface, honest signal underneath. The
translation never hides a caveat — an estimate still reads as an estimate, a
low-confidence score still says so, survivor-only data is still labeled. Friendly
copy is not permission to drop the guards. (See `BIASES_AND_BLIND_SPOTS.md` Tier 4
for the exact honest-limitation phrasings that must stay visible.)

---

## Component tree (React)

```
<App>
  <TopBar>
    <SearchInput />           // keyword mode
    <UrlInput />              // X-ray mode
    <CountrySelector />       // global re-scope
  </TopBar>
  <SideNav clusters={[outward, inward]} />
  <Router>
    <DiscoverView>
      <CandidateTable sortable filterable />   // the ranked pool
      <FilterPanel />
    </DiscoverView>
    <CockpitView candidateId>
      <SourceCards />          // Pinterest / Private / Public — the 3 questions
      // ⚠️ SOURCE SEPARATION (bias B-05): each card shows its OWN verdict —
      //    strong/weak + confidence — BEFORE the combined VerdictBanner renders.
      //    When sources disagree, the banner says so ("Pinterest strong / Etsy
      //    weak → may not convert") instead of showing a clean blended number.
      //    Three cards must always be visible above one verdict. Never collapse.
      <VerdictBanner />        // per product type, with confidence + sources_agree
      <ProfitPanel /> <GapPanel />
      <WhereToListBar />       // Etsy / Shopify / Pinterest / compare
      <LaunchPlanPanel />      // timing · tags · title · flaws
      <ConfidenceFlags />      // WHY a score is low-confidence — always visible
    </CockpitView>
    <RadarView><AlertFeed /><MomentumChart /></RadarView>
    <MarketView><ShopLeaderboard /><FilterSaturation /><MerchantShare /></MarketView>
    <PerformanceView><PredVsActual /><ErrorRatio /><WeightTuner /></PerformanceView>
    ... 
  </Router>
</App>
```

Shared primitives: `<FreshnessBadge/>` (shows every value's age — the freshness
rule made visible), `<ConfidenceTag/>`, `<ProvenanceDot/>` (measured vs derived),
`<Sparkline/>`.

> **Three UI primitives enforce the invariants visually:** freshness badge,
> confidence tag, provenance dot. If a number is stale, derived, or low-confidence,
> the user *sees* it. The honesty rules aren't just in the data — they're on screen.

---

## The API contract (read-only over Gold)

Every endpoint reads Gold and nothing else. None fetch, none write.

```
GET /candidates?type=&country=&sort=score&limit=          → ranked pool
GET /candidates/{keyword}                                  → full cockpit payload
GET /candidates/{keyword}/gap                              → dimension saturation
GET /candidates/{keyword}/where-to-list                    → platform comparison
GET /launch-plans?upcoming=                                → calendar rows
GET /launch-plans/{keyword}.ics                            → calendar export
GET /alerts?week=                                          → momentum feed
GET /market/shops?category=&country=&sort=                 → leaderboard
GET /market/filters?keyword=                               → SERP saturation profile
GET /my/listings/{id}/ranks?keyword=&country=              → rank history (medians)
GET /my/performance                                        → pred vs actual, error ratio
GET /settings   /  PUT /settings                           → the only write (config)

POST /jobs/discover     (optional, manual trigger)         → enqueues a batch run,
                                                             returns immediately;
                                                             the JOB writes, not the API
```

> The only write path from the UI is Settings and (optionally) *enqueueing* a batch
> job. The API never itself fetches or computes — it hands work to the ingestion
> process and returns. This keeps a user click from ever waiting on a provider call.

---

## State & data fetching

- **TanStack Query** (React Query) for server state — caching, staleness, refetch
  mirror the backend's own freshness model on the client.
- No global state library needed at this size; URL + query cache is enough.
- Every rendered value carries its `collected_at` → the `<FreshnessBadge/>`.

---

## Progressive build

1. **Discover + Cockpit** first — the core loop (find → decide) is the product.
2. **Settings** second — the profit model needs its inputs.
3. **Radar + Calendar** — trend and timing.
4. **Market + X-ray** — competitive depth.
5. **My Shops / Listings / Performance** — the inward half, once rank data has
   accumulated.

Build outward-then-inward, because inward views need history the system hasn't
collected yet on day one.

---

## SaaS readiness

The UI barely changes for multi-tenant: add auth, scope every API call to a
`tenant_id`, and the same component tree serves everyone. Because the API is already
a clean read layer over Gold, multi-tenancy is a filter on queries, not a rewrite.
See `07_saas_evolution.md`.
