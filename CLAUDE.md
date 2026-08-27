# CLAUDE.md — working notes for this repo

Operational knowledge that is expensive to rediscover. Architecture lives in
`docs/architecture/`; this file is *how to work here without repeating mistakes we
have already made.*

---

## What this is

A decision system for one operator selling on Etsy (digital, physical **and**
personalized). It joins three sources — Pinterest (momentum, timing, demographics),
Etsy Private (real volume, CVR, prices, competitors) and Etsy Public (supply,
reviews, saturation) — and answers: **what to list, when, and whether it pays.**

**The goal (D-20):** a **calendar-first** product — 🔴 list now / 🟡 list by Sept 22 /
⚪ watching — with keyword search as a second door. Not a niche checker; every
competitor is a niche checker.

**The defining failure mode:** *a plausible wrong number, not a crash.* Almost every
guard in this codebase exists to stop one specific wrong number reaching the operator.

---

## Running things

```bash
# ALWAYS use the venv — the system Python lacks bs4, curl_cffi, dotenv
.venv/Scripts/python.exe -m etsy.engines.master_niche_finder

# Everything is a module. Run from the repo root, never `python path/to/file.py`
# (etsy/ is a real package now; the sys.path hacks were deleted)
```

**Sessions come from a Redis vault, not `.env`** (changed 2026-08-13, D-28). The
Chrome extension POSTs to a **Go** server (`cookie_server_go/main.go`, Docker) which
writes Redis; `SessionManager` pulls a *random* profile per request and injects its
cookies, its own User-Agent, its CSRF token, and its `shop_id` into the `{shop_id}`
URL template. `core/cookie_server.py` is **dead code** — nothing imports it.

**Check the vault before any live run** — an empty pool makes pipelines *hang*, not
fail (S-2):

```bash
.venv/Scripts/python.exe -m core.vault_status
```

🔒 **This project reads Redis db 1, not db 0** (separated 2026-08-19). db 0 is the
**shared** vault the extension + Go server write to, and which the `pinterest-apify`
project also reads. `core/vault_mirror.py` copies it one-way into db 1 so our
evictions, prunes and leases can never touch their sessions. **Anything that judges
db 1 must sync first** — `preflight` and `vault_status` both do; a copy older than
300s reads as an empty vault. Full detail: `docs/VAULT_SEPARATION.md`.

⚠️ **A stale mirror does NOT fail cleanly — it 401s mid-run** (diagnosed 2026-08-21).
Nothing refreshes db 1 on its own. `Scheduler.run_job` gets the refresh free because
it preflights, so the **07:00 scheduled run is fine**; a **direct/CLI run is not**.
Measured: db 0 fresh at 125s while db 1 held a copy **7,473s** old. The fresh profile
then ages past the 300s eviction line, the pool falls back to `private_seller_1` —
which has *no heartbeat and is never evicted by design* (D-35) — and that jar's
cookies are old enough to return **401**. Symptom to recognise: `vault_status` says
green, and a run minutes later dies on 401.

**So call `preflight.require(...)` in any entry point that builds a live client.**
`discover`, `filter_trust` and `master_arbitrage` now do; `calendar_engine`,
`cockpit` and `learn` are DB-only and need nothing. `core/test_preflight.py` pins
this — it greps for a live client and demands a matching preflight.

⚠️ **`git checkout <old-branch>` can DESTROY `.env`** (happened 2026-08-25). `.env`
is gitignored *now*, but it was **tracked** in old `main` (`f27d36e`) and `git rm`'d
later (`98e2d32`). Git silently overwrites **ignored** files on checkout — it only
refuses for *untracked* ones — so checking out an old commit restores the tracked
copy over the live one, and merging forward then applies the deletion. The file is
simply gone, with no warning at any step. Back it up before any branch switch that
crosses those commits. Same hazard applies to any file that was once tracked and is
now ignored.

⚠️ **Two Redis servers share port 6379** on this machine (D-30). `localhost` reaches a
stale native one; the real vault is the Docker container at the address in `.env`. If
the vault suddenly reads empty, that is the first suspect — `vault_status` detects it
and says so. Verified green 2026-08-14: 11 etsy · 1 etsy_private · 8 pinterest.

- **You may fetch live data while building** — when the vault is green. Probing the
  real API is faster and more truthful than reasoning about it (D-24).
- Full detail, defect list and the fix: **`docs/architecture/10_session_layer.md`**.

```bash
# Full verification — run before every commit
.venv/Scripts/python.exe -m core.test_graph_db          # + the other 58 suites
# 59 OFFLINE suites, 1,596 assertions, no network required.
# ⚠️ pinterest/tests/ holds 5 more that are LIVE — their own docstrings say
# "Live verification". They hit real Pinterest, their assertion counts VARY
# with session state, and they print no summary when the vault is down. Never
# fold them into the offline number; a green offline run is the release gate.
```

---

## Non-negotiable rules

### 1. Never index a raw private-API key — use the parser

Etsy returns **snake_case**; this repo historically read **camelCase**, so seven
modules fetched correct data and read `None` out of it. That is why every table held
0 rows for the whole project's life.

```python
from etsy.api.private.api import parse_results_data, parse_term_summaries, edge_term
data = parse_results_data(api.get_results_data(kw))   # ✅
vol  = data["stats"]["searchVolume"]                  # ❌ silently None forever
```

`edge_term(e)` for keyword edges — the enqueue response keys them `query`, the old
consumers read `searchTerm`.

### 2. Absent is not zero (N-02)

A badge that did not render means *unmeasured*, not *zero demand*. A review count that
did not parse means *unknown*, not *no reviews*. Use `None`, and let the caller decide
at the point of use. Columns are nullable for this reason.

### 3. Estimates carry a basis; bounds are labelled as bounds

Every derived number ships with provenance (`measured` / `derived` / `default`). The
"N bought today" badge is an **upper bound** — it only renders above a threshold, so
×30 projects the best day across a month. It is clamped against the shop's measured
daily rate where one exists.

### 4. Refuse rather than guess

- `score_pool` raises `PoolTooSmall` instead of scoring 2 candidates
- `can_discriminate()` refuses to rank when the dimensions cannot separate the pool
- `survivor_bound` reports a **bound**, never a rate, and calls a 100% share
  `uninformative` rather than "healthy"
- a failed fetch is never cached; a failed scrape is never stored as `0`

### 5. Time is append-only

`*_observations` tables have `collected_at` in the primary key. Never overwrite a
time-varying value. The cache (`core/request_cache.py`) is the opposite — it exists to
*forget*, with per-type TTLs. Different files on purpose (D-18).

### 6. Do not touch the access layer

`core/session_manager.py`, `core/cookie_vault.py`, `cookie_server_go/`,
`chrome_extension/` — read them, document them, never extend them. **No Playwright or
headless browsers, ever.** `requests` / `curl_cffi` are fine.

### 7. Rank by winnability, never by market size (D-31)

`discover` shipped sorting by search volume — every number correct, and the
recommendation still wrong:

| Term | Volume | Supply | Demand/listing | CVR |
|---|---|---|---|---|
| `home decor` (was 1st) | 310,467 | 2,160,627 | 0.14 | 0.00005 |
| `backpack name tag` (was 17th) | 69,874 | 25,031 | **2.79** | **0.00279** |

A term with 2M listings is a wall, not an opportunity. Show the **ratio**, not a score —
"you cannot rank here" has to be checkable. See the `etsy-seo-and-opportunity` skill.

### 7b. …but winnable is not the same as bought (D-43)

That ratio divides searches by listings — **both supply-side**, so a term passes on
traffic alone. The expansion endpoint returns no CVR at any price, so DISCOVER ranked
`custom family name necklace` **first** while it converts at **0.15x** the median of
the terms measured beside it. 5 of the top 6 were the same story.

`confirm_intent` is the second gate: one `results-data` call per top candidate, and the
headline verdict is the worse of the two. **It is deliberately RELATIVE.**

⚠️ **`volume × query_cvr` is NOT an order count.** It implies 39.8 orders/month
market-wide for `personalized gift`, whose #1 listing has 14,733 reviews (~30 years'
worth). `query_cvr` is a rate against a denominator Etsy does not publish. Compare it
between terms — never threshold it as units. `opportunity.market_demand()` claimed
otherwise for the project's whole life; its `basis` is now `relative_only`.

### 8. Public unless seller access is mandatory (D-29)

`etsy_private` authenticates as **the operator's own seller account** — the one
unreplaceable asset here. A burned buyer session costs a re-login; a burned seller
account costs the business.

- **Never** put a competitor's `shop_id` in a private URL. That `{shop_id}` is *who we
  are*, not *who we are asking about*.
- Private is only for what nothing else can answer: search volume, CVR, chart series,
  trending terms, LLM keywords.
- Competitor shops, listings, reviews, SERP → **public (`etsy`), always.**

---

## Hard-won facts

| Fact | Detail |
|---|---|
| **The vault is the session** | Redis, filled by the Go server from the extension. `SessionManager` rotates profiles per request, so two calls in one run may use two identities. |
| **Extension role defaults to `"auto"`** | …which matches **no** branch, so cookies land in `etsy` while `shop_id`/csrf land in `etsy_private`. The private profile therefore has **no cookies** and cannot authenticate. Current blocker (S-1). |
| **The vault is hardened (2026-08-19)** | `get_valid_account` prefers a fresh heartbeat, evicts signed-out jars (no `session-key-www` / `_auth`), claims a `SET NX` lease, and waits a **bounded** 120s. A heartbeat-less profile is deprioritised, never evicted — `private_seller_1` is the seller session and nothing beams it back. See `docs/SESSION_LAYER_FIX.md`. |
| **429 no longer burns a session** | `session_manager.classify()` separates `rate_limited` / `malformed` / `auth_expired` / `blocked`. Only the last two evict, so neither Etsy throttling nor a bug in our own request can retire the seller account. |
| **No quota** | `results-data` reports `quota_data {total:15, remaining:15}` but three consecutive distinct calls left it at 15/15 — this endpoint does not consume it (D-14). `deep_dive_limit` defaults to unlimited. |
| **401 ≠ 429** | 401 = stale session (restart cookie server). 429 = real throttle; `SessionManager.rate_limited` counts them. Nothing has ever recorded a 429. |
| **`.env` is untracked** | `git rm --cached` was applied. `registry.json` was also untracked — it held 32 live session cookies. |
| **20 competitors per call** | `results-data` returns them free. Do not scrape the public SERP to rebuild what you already have. |
| **Etsy has its own momentum** | `wow_data.value` — week-over-week %, free, in the same response. |
| **Unused, verified to exist** | `predicted_days` (Pinterest 91-day forecast), `page` (pagination), `include_trendline`. See `08_capability_map.md`. |
| **`similar_search_terms` and `market_gap_recommendations` are EMPTY** | Recorded earlier as free unread signals. Probed 2026-08-15 on `felt garland`, `mom necklace`, `christmas ornament`: all returned `total_results_count: 0` and a null gap block. The keys are in the schema; Etsy returns nothing in them. **Do not build on them.** |
| **`locationQuery` is not a filter** | It returns a *broader* result set than the search it filters. On `monogrammed waffle weave towel` (10,011 unfiltered) Germany returned 28,271 and seven countries summed to **1116%** of the market they claim to partition. Origin share is **not obtainable from the SERP** — use `sourcing.sample_origins()`, which reads each listing's declared origin and can see countries Etsy's list omits (it found a Turkish seller). `delivery_days` was checked the same way and **is** sound: monotonic, cumulative, never above total. |
| **`organic_listing_ids` was ALWAYS empty** | Parser bug fixed 2026-08-20. The regex demanded `"result_count"` within 200 chars of the array; the real neighbours are `bucket_id`/`user_id`. It returned `[]` on every page for the project's life — silently, because an empty list is plausible for a page with no results. Now 39–51 ranked ids, which also unblocks rank tracking. |
| **The UI is `etsy/data/ui/index.html`** | One entry point (`etsy.ui.home`) links the Calendar, Discover and per-term Cockpit screens, with a blockers-first digest. All generated files reading the database — no server, no read API. Refreshed daily by the calendar job. |
| **The optional server is `etsy/server/app.py`** | FastAPI over the same read layer (`app_data`) plus `POST /api/analyze/{term}` for live analysis of a typed keyword. Opt-in (`run_server.cmd`), 127.0.0.1 by default (D-42). The scheduler + static files remain the no-daemon default. |
| **The interactive app is `etsy/data/ui/app.html`** | One self-contained page over the daily snapshot: six tabs, sortable/filterable tables, search, sparklines, Etsy + Pinterest. Everything reads THROUGH `etsy/ui/app_data.py`, the one read layer a future FastAPI server would also consume (D-41). |
| **Two screens exist** | `etsy.ui.calendar_page` (home, + `.ics`) and `etsy.ui.cockpit_page` (one candidate, with page-one saturation joined in). Generated files, not a server — no read API exists, so a SPA would have nothing to call. |
| **Demand and competition are separate tables** | `keyword_observations` (private demand, market-wide) and `keyword_competition` (public page-one saturation, a ~9-listing sample with intervals). Joined only at read time in the Cockpit — never merged, or a saturation of 6 gets divided by 1.4M listings. |
| **Buy the sample when it matters** | `listing_sample.py` opens ranked listing pages at 1 request each; n=25 made free shipping decisive where 6 cards could not. `LISTING_SAMPLE` defaults to 0 — 200 requests is the operator's call (D-37). |
| **A page-one share is ~9 listings, not a market share** | `card_saturation` recovers the dimensions the filter audit took away by counting card fields, then attaches a Wilson interval and **withholds** any bracket whose bounds straddle a threshold. **0 of 6 does not establish an empty bracket** — the true share could be 39% (D-36). |
| **The calendar exists (2026-08-19)** | `python -m etsy.engines.calendar_engine`. Moments were being computed and DISCARDED — `trends_bridge` only stored a takeoff date when a featured topic shared a moment's name, and the overlap is zero. All 13 moments were dropped; `takeoff_timestamp` was NULL in every row. Also stores `peak_date`/`phase` now, without which "late vs missed" was being guessed. |
| **Gaps can finally resolve** | `bracket_demand.py` supplies D-10's missing half. Demand inside a bracket is inferred from the review counts of the listings in it, because Etsy reports volume per TERM and never per bracket (D-34). Before this, `demand_by_bracket={}` meant no bracket could EVER be a gap. |
| **9 of 12 SERP filters cannot be believed** | Audited 2026-08-19, recorded in `config/filter_trust.json`, enforced by `find_gaps`. Trusted: `delivery_days`, `gift_wrap`, `is_personalizable`. Ignored: `min_rating` (returns 4.8-rated listings), `best_by_etsy`, `holiday`. Not a subset: `attr_1` (colours sum to 562%), `is_digital`. Unstable: `is_star_seller`, `is_discounted`, `free_shipping`, `locationQuery`. Re-audit: `python -m etsy.analytics.filter_trust`. |
| **`total_results` is an ESTIMATE** | Identical unfiltered searches returned 217,196 / 217,196 / 217,395. Never test it with exact equality — see `filter_trust.COUNT_JITTER` (2%). |
| **Etsy's shop counter is QUANTISED** | A shop displaying "25,100" steps by 100, so a zero delta means "moved less than the counter can show", not "sold nothing". `record_shop_observation` returns `below_resolution` + an upper bound rather than a 0.0 rate. |
| **Printify has no production cost** | The catalog exposes shipping and handling time; there is NO price on a catalog variant, and the Premium discount cannot be read. `cost` exists only on a product object. COGS is operator-confirmed or it does not exist. |
| **Printify handling is 10 days** | On every towel provider. Lead time 12-16 days, so Etsy's 7-day delivery bracket is structurally closed to POD. |
| **`query_cvr` has no known units** | It is NOT searches→orders. `volume × query_cvr` for `personalized gift` = 39.8/mo market-wide, while its #1 listing holds 14,733 reviews. Usable only as a comparison BETWEEN terms (D-43), never as a quantity. |
| **Etsy ships its own seasonal curve, free** | `chart-series-data`'s `series` block holds a 12-month volume curve per term. Every caller read `term_summaries` and discarded it for the project's whole life (D-45). `christmas ornament` peaks Nov at **93x** its trough; `mom necklace` peaks **December**, not May. ⚠️ The last bucket is PARTIAL — judging on it manufactures a collapse. `include_trendline` is inert: True and False return identical structures. |
| **The DISCOVER front door works** | `trending-search-terms-v2` returns rising terms with real volumes and no quota cost. Only **7** taxonomy ids are populated (1, 66, 199, 323, 891, 1429, 1633) — several plausible ones (Jewelry, Clothing, Craft Supplies) return nothing. 28 candidates total. |
| **Pinterest momentum joins on the TERM, never on the stored featured topics** (D-44) | The obvious cheap join — matching Discover's pool against `trend_observations`' 84 Pinterest topics — scores **0 exact and 0 containment matches** against 1,333 Etsy terms. Editorial phrases ("Apple-Themed Preschool Activities") vs product keywords, the identical mismatch that broke the calendar. `/metrics/` asks Pinterest about the pool's OWN terms directly, one batched call. Pinterest DROPS terms it does not track (asked 7, got 3) — absent, not fading. `100.01` is Pinterest's own "10,000%+" display cap, not a real value. |
| **POD's ceiling comes from page one, not the API's price band** (D-46) | `results-data`'s median band ($11.70–$14.30 on `personalized baby blanket`) is market-wide; the 20 listings that actually rank charge a median of **$25.19** — free in the same response. Pricing the margin floor off the band computes a $5.21 ceiling (POD near-impossible); off page one, $12.69 (plausible). Never returns "profitable" — Printify's catalog has no variant price, so the output is a ceiling plus a handoff. |
| **This vault does not mirror `pinterest-apify`'s sessions** (D-47) | Measured: 7 of 9 pinterest profiles in this pool were their AdsPower jars (`ads_<user_id>`), not this project's extension captures (`profile_<random>`). Their own `identities.py::export()` pulls every profile in the shared pool with no ownership check and writes raw cookies to disk — the shared db 0 was never passive. `FOREIGN_PROFILE_PREFIXES` skips and purges anything not ours; db 0 itself is still never written by this project. Full physical separation (a second Redis, a second Go server) is the next step — see ROADMAP.md. |

---

## Doc map

| File | Answers |
|---|---|
| `docs/ONBOARDING.md` | **start here for a fresh session** — what is true, what is a trap |
| `docs/MCP.md` | **tutorial**: wiring the MCP server (17 tools) into Claude Code/Desktop/Antigravity, the tool table, troubleshooting, and where DeepSeek is allowed to touch the system |
| `docs/UI_GUIDE.md` | **tutorial**: the three UI tiers (static screens, interactive app, live server) — what each is for, how to launch it, when to reach for which |
| `ROADMAP.md` | what's still missing (single-operator scope) + design-only notes for a future listed-MCP/SaaS version — read before assuming multi-tenancy is a small change |
| `docs/architecture/09_build_plan.md` | **what we are building and in what order** |
| `docs/HOW_WE_WORK.md` | **the operating model** — the three seats, the loop, which lens fires when. Read first. |
| `docs/market_map/` | **the shared knowledge base** — `reference/` (params, payloads, verified per platform) + `analysis/` (what each is worth, and the combinations). Read before planning data work. |
| `docs/architecture/11_endpoint_reference.md` | one-page endpoint summary; `docs/market_map/` is the full version |
| `docs/architecture/10_session_layer.md` | how sessions really work now (Redis vault), the defect list, and why nothing can run today |
| `docs/architecture/08_capability_map.md` | every endpoint + parameter, used vs never called |
| `docs/architecture/07_gaps_and_risks.md` | the defect list; §ROOT CAUSE explains the empty tables |
| `docs/architecture/bias_audit.md` | the **verified** bias picture |
| `docs/DECISION_LOG.md` | why anything is the way it is (D-01…D-27) |
| `docs/GOAL.md` | the north star |
| `BIASES_AND_BLIND_SPOTS.md` | ⚠️ self-declared **unverified**; 2 of its 10 claims were wrong. Prefer `bias_audit.md`. |

Skills in `.claude/skills/`: **`etsy-pipeline-work`** (is the number *true* — read it
before touching a pipeline), **`etsy-seo-and-opportunity`** (is it the *right number to
show first* — read it before ranking or recommending anything), `system-architect`,
`bias-aware-analysis`, `ui-builder`, `git-and-comments`. They are enforced, not
advisory.

Those first two are deliberately a pair. `etsy-pipeline-work` catches a wrong number;
`etsy-seo-and-opportunity` catches a correct number shown in the wrong order. Both cost
the operator a wasted launch, and only the first looks like a bug.

The third, **`etsy-market-intelligence`**, is the analyst/marketer lens: *is this signal
worth gathering at all, from which platform, and what does a seller do with it.* Read it
before planning a data-gathering feature or judging a new endpoint's value. It carries
the value chain (discover cheap → qualify public → measure private-last), what to store
for compounding value, and the roles (operator confirms direction, engineer builds and
never fabricates a number).

**`web-surface-mapping`** is the fourth: map a tool through the operator's *logged-in
browser* — click every filter, watch every request, capture exact wire formats, and
record what each control is worth. Probing the API alone has repeatedly missed things a
single screenshot would have caught.

---

## Current state

**Working:** all three API clients · profit gate · survivor bound · gap analysis ·
scoring with discrimination check · freshness floor · tag mining · term join ·
request cache · run log · guards. 59 offline suites, 1,596 assertions (+5 live
pinterest suites that need a session).

**Added 2026-08-19:** the calendar (`etsy/engines/calendar_engine.py`) ·
demand-in-bracket (`etsy/analytics/bracket_demand.py`) · filter-trust registry with
`find_gaps` enforcement (`etsy/analytics/filter_trust.py`) · sourcing, lead time and
origin sampling (`etsy/analytics/sourcing.py`) · POD costing and both profit
inverses (`etsy/analytics/pod_costing.py`) · Printify client
(`etsy/api/printify/`) · LEARN outcome capture (`etsy/analytics/learn.py`) ·
verdict change log (`etsy/analytics/verdict_log.py`) · vault separation
(`core/vault_mirror.py`) · session-layer hardening · **the Calendar screen**
(`etsy/ui/calendar_page.py`, + `.ics` export) · saturation recovered from listings
(`etsy/analytics/card_saturation.py`) · **17 MCP tools** (`mcp_server/`) ·
the read server (`etsy/server/app.py`) · the interactive app (`etsy/ui/app_page.py`) ·
a Docker service for the read server (`docker-compose.yml`, `etsy-server`) ·
the intent gate (`etsy/analytics/discover.py::confirm_intent`, D-43) ·
Pinterest momentum as a third axis (`etsy/analytics/momentum.py`, D-44) ·
Etsy's own seasonal curve, recovered from a response every caller discarded
(`etsy/analytics/seasonality.py`, D-45) · POD price-reality and viability
(`etsy/analytics/pod_check.py`, `/pod`, D-46) · this vault no longer mirrors
`pinterest-apify`'s sessions, even from the shared database (`core/vault_mirror.py`
`FOREIGN_PROFILE_PREFIXES`, D-47).
**1,596 assertions** across 59 offline suites, plus 5 live pinterest suites.

**The clock now runs.** `run_scheduler.cmd` is registered as the Windows task
`EtsyScrapperDaily` (07:00). The first Pinterest bridge run wrote 84 trend
observations into a table that had held zero.

**Still thin:** trend, listing and shop observations are accumulating; keyword
history now covers 8 watched terms; **0 launches**, so LEARN cannot start. **Value compounds only with time** — a daily
delta needs two readings a day apart and cannot be backfilled.

**Settings confirmed 2026-08-20:** fees verified against Etsy's published schedule,
operator rate $25/hr, capacity 10 hrs/week. Profit verdicts now read `derived`, not
provisional. (Read confirmation via `settings.basis()`, NOT a `.confirmed` attribute
— there isn't one; that getattr bug reported everything provisional forever.)

**Next:** see `09_build_plan.md`.

---

## Working style that has paid off here

- **Probe the wire before theorising.** Three plausible, documented explanations for
  the empty tables were all wrong; one live call settled it in seconds (D-24).
- **Diff response keys against the keys the code reads.** That single check would have
  caught the project's biggest bug at any point in its life.
- **When a doc and the code disagree, believe the code — then check the wire.**
  Several docs describe features that were never built.
- **Write the test that proves the bug first.** Two real bugs this session were found
  by a test failing in a way I did not predict.
