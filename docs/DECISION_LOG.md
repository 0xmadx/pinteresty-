# DECISION LOG

Every significant design decision, why it was made, and what was rejected. When
someone (or future-you) asks "why is it like this?", the answer is here.

Format: **D-nn — Decision** · Context · Chosen · Rejected · Consequence.

---

## D-01 — Profit, not revenue, is the central metric

**Context:** The original architecture had no cost input anywhere. It estimated
revenue and treated a big number as a win.
**Chosen:** A profit model per product type — fees, COGS, shipping, labor — feeding
the score as a weighted variable with per-type margin floors.
**Rejected:** Ranking by revenue or by demand alone.
**Consequence:** Verdicts change. In the three-way demo, the *highest-revenue*
option was a no-go on margin. Profit reorders the rankings, which is the point.

## D-02 — Percentile normalization instead of multiplying raw values

**Context:** `(Demand × Momentum × Intent) / (Supply × SERP)` multiplied Etsy
absolute counts (thousands) by Pinterest 0–100 indices. Whichever variable had the
biggest raw range silently dominated.
**Chosen:** Convert every variable to its percentile rank within the pool, then
take a weighted sum.
**Rejected:** Z-scores (distributions are skewed and full of sentinels);
min-max scaling (one outlier destroys it).
**Consequence:** Scores became comparable and *interpretable* — you can read why a
candidate ranked where it did. Also introduced the need for `pool_id`/`pool_size`,
since a percentile is meaningless without its pool.

## D-03 — Product type is a front-door router, not an end filter

**Context:** The original spec scored once and then evaluated three ways.
**Chosen:** The operator picks digital/physical/personalized up front; that
selection routes profit model, margin floor, applicable dimensions, discovery
pillar, and timing.
**Rejected:** Scoring once and filtering after.
**Consequence:** One honest pipeline per type. "Compare all three" survives as a
separate mode for deciding *how* to make something already chosen.

## D-04 — Time is append-only; predictions snapshot their inputs

**Context:** If a keyword's demand is overwritten by fresher data, evaluating an
old prediction against the new value tests a prediction that was never made.
**Chosen:** Time-varying tables append-only with `collected_at`; `launches` stores
the literal feature values used, never foreign keys.
**Rejected:** Upsert-in-place with a "current state" table only.
**Consequence:** LEARN becomes honest, and `launches` doubles as a future ML
training set. **This cannot be retrofitted** — it must be right from the first row.
⚠️ `trends_store.py` currently violates this and needs fixing.

## D-05 — The source is an implementation detail behind an adapter

**Context:** The operator prototypes on one data source but intends to move to
official/commercial APIs later.
**Chosen:** A normalized record contract; every provider implements the same
interface; `field_provenance` marks per-field availability.
**Rejected:** Coupling business logic directly to any provider's response shape.
**Consequence:** Switching providers is writing one class and editing config.
Also forces the honest finding that **official APIs expose less** — some signals
come back `None`, which the confidence gate already handles.

## D-06 — Guards live at exactly one boundary (Bronze→Silver)

**Context:** Sentinels, noisy series, and freshness could be handled anywhere.
**Chosen:** One transform applies all guards: clamp sentinels, set `noisy`, stamp
`collected_at`, strip PII.
**Rejected:** Guarding at point of use (scattered, unauditable).
**Consequence:** One place to audit and fix. Also means anything reading Silver can
trust it — and that pandas vectorization is safe *because* the data was cleaned
before it reached a DataFrame.

## D-07 — Embedded stack; nothing distributed

**Context:** "Multidimensional, layers, nodes, big data" suggested heavy tooling.
**Chosen:** SQLite (writes), DuckDB (analytical reads), pandas/numpy (compute),
FastAPI (serving), Docker (reproducibility, one container).
**Rejected:** Kafka, Spark, Kubernetes, Postgres, Redis, graph/time-series DBs.
**Consequence:** Dimensionality is a property of the *data model*; volume is what
justifies distribution, and the volume is megabytes. Docker is used for
reproducibility, not scale. All rejected tools have a named trigger condition in
`07_saas_evolution.md`.

## D-08 — Ingestion and serving are separate processes

**Context:** A dashboard could fetch on demand.
**Chosen:** Batch jobs write; a read-only API serves Gold. They meet only at the
database.
**Rejected:** API-triggered fetching.
**Consequence:** A user click can never wait on (or fail because of) a provider
call. Also the seam that lets serving scale independently later.

## D-09 — Count functions, not descriptions

**Context:** "~45 tools" came from counting tool *descriptions* across docs; the
same capability appears under several names.
**Chosen:** De-duplicate; map each documented tool to its implementing function;
mark functionless docs aspirational.
**Rejected:** Trusting the doc-derived count.
**Consequence:** ~45 → likely ~28–32. Compositions (`master_*` scripts) counted as
pipelines, not tools. See `CAPABILITY_COUNT_DEDUP.md`.

## D-10 — The empty-bracket trap gates the gap-finder

**Context:** Slicing a market 7 ways always produces empty cells; the original
design read 0% saturation as a loophole.
**Chosen:** Demand must be shown to hold *inside* the bracket; dimension sets are
selected by product type.
**Rejected:** Treating any 0% bracket as opportunity.
**Consequence:** Prevents confident nonsense — e.g. shipping-speed arbitrage on a
digital product returns a guaranteed-empty bracket that means nothing.

## D-11 — Where-to-list is decided by demand *type*, not fees alone

**Context:** Shopify keeps ~97% vs Etsy's ~85%, which naively always favors Shopify.
**Chosen:** Decide on whether demand is **searched-for** (→ Etsy's free traffic) or
**discovered** (→ Shopify/Pinterest), with CAC modeled as a *range*.
**Rejected:** Picking the platform on fee percentage.
**Consequence:** Shopify wins only if traffic is cheap. Paid CAC often exceeds
Etsy's fees, flipping the answer. Also reframed as a *sequence*: validate on Etsy,
scale winners on Shopify.

## D-12 — Don't auto-tune weights below ~10 launches

**Context:** LEARN can fit weights from outcomes.
**Chosen:** Report raw comparisons under ~10 launches; only automate tuning above
it.
**Rejected:** Fitting immediately.
**Consequence:** Avoids a model that explains five past outcomes perfectly and
predicts nothing.

## D-13 — Build 3 UI pages, not 10

**Context:** The UI design specifies 10 page types.
**Chosen:** Ship Discover + Cockpit + Settings; add the rest as data and need
appear. Inward views (My Shops, Performance) *can't* exist until history accrues.
**Rejected:** Building all ten up front.
**Consequence:** A usable product much sooner, and no empty screens.

---

## D-14 — The private API is not rationed (supersedes the quota assumption)

**Context:** D-01…D-13 and the whole engine were designed around a documented
"15 analyses per period" (`REPO_STRUCTURE_AND_CONFIG.md:115`,
`overviews.md:10`). Nothing in the system ever detected a limit: no counter, no
quota header, no recorded 429 — and `SessionManager` answered 401/403/429 alike by
waiting for a fresh cookie, so a throttle was indistinguishable from a stale session.
The two code comments claiming a cost contradicted each other, and the one asserting
it sat in a module that cannot import.
**Chosen:** Treat the endpoint as unrationed. The operator tested it directly and
found no limit; `deep_dive_limit` defaults to None (analyse every candidate).
**Rejected:** Keeping `deep_dive_limit=3` on the strength of the docs alone.
**Consequence:** This changes the architecture's shape, not just a constant. The old
design was *crawl wide on free sources, spend metered narrowly*; it is now *crawl
wide everywhere*. 47 of 50 candidates were previously discarded by a demand/supply
score that D-15 shows carries no information. The detection stays — `rate_limited`
counts 429s and every run reports its call count — so if a limit exists it announces
itself instead of being silently absorbed, which is how the belief survived unexamined.

## D-15 — Refuse to rank when the dimensions cannot discriminate

**Context:** Percentile ranks of two rank-correlated inputs are p and (1-p); with one
inverted the weighted sum is exactly 0.500 for every candidate at any pool size. Etsy
demand and supply have that shape by nature — popular keywords carry more listings —
so the "opportunity score" was uninformative in the normal case, not an edge case.
**Chosen:** `can_discriminate()` asks *before* scoring whether a ranking could carry
information. When it cannot, the step emits a labelled **filter** with a stated rule
and no score at all.
**Rejected:** Annotating a flat result afterwards. By then the caller holds an ordered
list and reads it as a judgement.
**Consequence:** A number is never printed where none is earned. The real fix is more
dimensions (D-16), not a better formula.

## D-16 — Momentum, intent and audience come from Pinterest, free

**Context:** `overviews.md` §6 specifies the scoring model and its sources. Three of
its variables — momentum, purchase intent, audience fit — have no Etsy equivalent at
any price, and are free on Pinterest. None reached the scorer, which is *why* the pool
had only the two correlated dimensions of D-15.
**Chosen:** Join Pinterest into Etsy scoring as a first-class dimension.
**Consequence:** The join, not the formula, was the missing piece. Adding momentum
turns a flat 0.500 pool into a 0.250–0.675 spread on the same candidates.

## D-17 — The term join is strict, never fuzzy

**Context:** Pinterest writes "Mom Necklaces", Etsy asks "mom necklace"; an exact
match misses and the candidate is scored with one dimension fewer, silently.
**Chosen:** Normalise both sides (lowercase, singularise, strip stopwords) and require
**exact content-word set equality**. Word order may differ; content may not.
**Rejected:** Edit distance, partial overlap, best-guess scoring.
**Consequence:** On short retail phrases one word *is* the niche — "cat collar" vs
"dog collar", "wedding" vs "birthday". A fuzzy match would import another niche's
momentum under the right label, which is the plausible-wrong-number failure this
system exists to prevent. A miss costs one absent dimension; a wrong match costs a
wrong recommendation. Singularisation is conservative for the same reason: "dress"
must not stem to "dres" and break every future match.

## D-18 — Cache and store are different concerns, in different files

**Context:** Five clients each kept their own JSON file cache with **no expiry**, so a
weekly trend series harvested once was served as current forever.
**Chosen:** One `RequestCache` (SQLite, per-type TTLs). It exists to **forget** — the
latest copy replaces the old. The observation tables exist to **remember** — every
reading with its `collected_at`, forever.
**Rejected:** Redis (solves cross-process coordination that does not exist here at
single-operator scale), and sharing tables between the two.
**Consequence:** TTL is an explicit bet per data type — live data is never cached
(`TTL_LIVE=0`), weekly series expire weekly. A failed fetch is never cached, so a
transient error is not frozen into truth.

## D-19 — Report bounds, not rates, where only survivors are visible

**Context:** `BIASES_AND_BLIND_SPOTS.md` B-01 proposes a survivor rate from total
supply ÷ listings with reviews. That is not computable from a SERP: it renders ~12
cards against a supply in the tens of thousands, and those 12 are the best-ranked.
**Chosen:** Report an upper **bound** with an asymmetric verdict — a low reviewed
share among top listings is real evidence of a graveyard; a high share is
`uninformative`, never "healthy".
**Consequence:** The same discipline applies to badge-derived sales (an upper bound,
clamped against the measured shop rate) and to any value observed only above a
threshold.

## D-20 — Calendar is the home screen; search is the second door

**Context:** The system could open with a keyword box (like every competitor) or with
a timed list of what to launch. O-7, decided by the operator 2026-08-12.
**Chosen:** **Calendar first** — 🔴 list now / 🟡 list by Sept 22 / ⚪ watching — with
keyword search always available in the top bar.
**Rejected:** Search-only. It is the commodity product; eRank and Everbee already do it.
**Consequence:** Timing becomes the spine, so the TIME loop (Pinterest `moments` → Etsy
`holiday` filter → `list_by`) moves from "nice to have" to the engine of the landing
page. The forecast layer (`predicted_days`) becomes load-bearing rather than decorative,
because ⚪ WATCHING is the row no competitor can produce.

## D-21 — Etsy only for now, but stay channel-aware

**Context:** D-11 designs a where-to-list decision (Etsy vs Shopify/Pinterest) on
searched-for vs discovered demand. Building it is real work.
**Chosen:** Ship **Etsy-only**, and keep the data model and docs channel-aware so adding
a second channel is not a rewrite.
**Rejected:** Building where-to-list now (scope), and hardcoding Etsy assumptions
everywhere (would force a rewrite later).
**Consequence:** D-11 stays designed and unbuilt. Anything that stores a decision or a
launch should carry a channel field even while only one value is ever written.

## D-22 — All three product types are in scope, so type must be DETECTED

**Context:** The operator sells digital, physical and personalized.
**Chosen:** Support all three, and **detect the type** rather than requiring the operator
to declare it per run.
**Consequence:** This is not a preference, it changes correctness. The gap dimensions
that can even be *asked* differ by type (a download has no delivery window — D-10), the
margin floor differs (0.70 / 0.35 / 0.50), and for personalized goods the binding
constraint is the weekly capacity ceiling rather than demand. A wrong or assumed type
produces confident wrong verdicts in all three subsystems. One `is_digital` request
answers it, so detection is cheap; assuming is not.

## D-23 — Settings ships before anything else

**Context:** `profit.py` ships default fee values (6.5% transaction, 3% + $0.25
processing, $25/hr, 15 h/week) from `REPO_STRUCTURE_AND_CONFIG.md`. Every profit verdict
— and therefore the whole calendar and cockpit — depends on them.
**Chosen:** Build the **Settings page first**, so fees, COGS, hourly rate, hours/week and
tracked shops are operator-owned data, never hardcoded.
**Rejected:** Shipping the calendar on default constants and confirming later. A verdict
computed from an unverified fee schedule is exactly the plausible-wrong-number this
system exists to prevent, and it would be wrong in the most expensive place.
**Consequence:** Settings moves ahead of the Calendar in the UI build order, matching
what the `ui-builder` skill already required.

## D-24 — Probe the live response before theorising about missing data

**Context:** Every table held 0 rows. Three explanations were offered and argued over —
an API quota, a broken `src.services.executor` import, and missing scheduling. All were
plausible, all were reasoned from documents, and **all were wrong**. Etsy returns
snake_case; every consumer read camelCase, so seven modules fetched correct data and
read empty values out of it.
**Chosen:** When data is missing, **call the endpoint and read the actual response
first**. Treat doc-derived explanations as hypotheses until a live payload confirms them.
**Consequence:** The field-name mismatch had survived the entire architecture pass, a
bias audit and several rounds of review, because every reviewer reasoned about the code
rather than the wire. `parse_results_data` now centralises the shape and accepts both
spellings. See `09_build_plan.md` §3.

## D-25 — Competitor tracking measures OUTCOMES, not listings

**Context:** The operator proposed a competitor-shop window: track shops, see what they
list, relate it to watched niches.
**Chosen:** Track **per-listing review velocity** — *what they listed that then sold* —
not a feed of what they listed.
**Rejected:** A listing feed. Listings are cheap and most fail; a feed tells you what a
competitor **guessed**, and copying guesses is copying noise.
**Consequence, and it is bigger than the feature looks:** a competitor's launches are
chosen **independently of our model**, so their outcomes are an unbiased sample. Our own
`launches` table can only ever contain niches the model already liked, which is B-04 —
the model cannot discover it was wrong to reject something. Watching competitors
partially fixes that for free, and the sample grows weekly instead of one launch at a
time.
Reviews are the only competitor signal that cannot be faked, and review **dates** are
already fetched, so velocity per listing is measurable today.
**Two guards:** track some **mid-tier** shops, not only stars, or this reproduces B-01
survivorship at the shop level. And shop-level sales deltas cannot attribute a jump to a
specific listing — per-listing review velocity is what attributes it.
**Timing:** must start collecting **early**. It is the one item that is worthless if
started late, so it goes ahead of features that can be added any time.

## D-26 — COGS is per-product; Settings has two tiers

**Context:** D-23 put Settings first, but a single COGS figure is wrong — cost differs
per item, and the operator sells all three types (D-22).
**Chosen:** Split Settings.
  * **Global**, set once: Etsy fee rates, hourly rate, hours available per week.
  * **Per-product profiles**, named and reusable: COGS, shipping cost, labour minutes —
    e.g. `"Digital printable"` (0/0/0), `"Ceramic mug"` ($8.50/$4.20/3 min),
    `"Custom name sign"` ($12/$6/45 min).
**Rejected:** One global COGS. It would be wrong for every product except one.
**Consequence:** No redesign needed — `profit.verdict()` already accepts exactly these
as `product_profile`. Judging a candidate means choosing a profile. For personalized
goods the labour minutes drive the weekly capacity ceiling, which is usually the binding
constraint rather than demand.
**Form:** a **config file plus CLI first**, web page later. The UI is Phase 4 and this
unblocks real profit numbers immediately.

## D-27 — The LLM classifies and extracts; it never invents a number

**Context:** The operator has Gemini available and asked whether an LLM could supply COGS.
**Chosen:** LLM use is limited to **classification** and **extraction from a real
source**:
  * product-type detection (digital / physical / personalized) — **required by D-22**
  * occasion/holiday detection from a keyword
  * pulling a price out of a supplier page the operator pastes
**Rejected:** Asking an LLM to estimate COGS, demand, or any figure it cannot read from
a source.
**Consequence:** An invented cost flows straight into a go/no-go verdict — the
plausible-wrong-number failure this system exists to prevent, in the most expensive
place. Anything an LLM produces is tagged as derived and is overridable, exactly like a
defaulted CVR.
**Provider:** `core/llm_client.py` already wraps DeepSeek and works. Adding Gemini is a
second provider in that file, not an MCP. (An MCP would give *Claude Code* access to
Gemini during development — a different purpose from the app calling it at runtime.)

---

## D-28 — Sessions live in a Redis vault, not `.env` (supersedes the cookie-server model)

**Date:** 2026-08-13 (Gemini), verified against the running system 2026-08-14.
**Context:** `EtsyPrivateAPI.__init__` scraped the dashboard for `operator_shop_id` and
hardcoded it, while `SessionManager` rotated profiles per request. Profile A's
`shop_id` sent with Profile B's cookies is an instant 403. `VaultGuardian` then
rejected profiles lacking a `shop_id` — a circular dependency the system could not
start from.
**Chosen:** Authentication as a service, held in Redis.
  * the Chrome extension POSTs cookies + `x-csrf-token` + `shop_id` + **`user_agent`**
    to `cookie_server_go/main.go`
  * private URLs carry a literal `{shop_id}` template, filled from *the profile that
    was actually drawn* immediately before the request
  * the profile's **own** User-Agent is applied to the curl_cffi session, so the UA,
    the TLS fingerprint and the cookies describe one consistent browser
  * dashboard scraping and `auto_discover_shop_id()` are deleted
**Rejected:** hardcoding a shop_id; deriving it in Python; a buyer/seller extension
split plus a proxy router (**paused**, not cancelled); IP-rotation logic in Python —
IP alignment is infrastructure (residential proxy or one VPS), not a Python feature.
**Consequence:** `core/cookie_server.py` is dead code and `.env` no longer carries
cookies. Every doc describing the old model is superseded by `10_session_layer.md`.
Two new failure modes that did not exist before: a request's identity is
**non-deterministic**, and an empty pool **blocks forever** rather than raising (S-2).

---

## D-29 — Public unless seller access is mandatory; never a competitor's shop_id

**Date:** 2026-08-13 (Gemini), adopted 2026-08-14.
**Context:** `etsy_private` authenticates as the operator's **own** seller account.
Buyer sessions are replaceable; the seller account is the business.
**Chosen:** A hard split.
  * `etsy_private` only for what nothing else can answer — search volume, CVR, chart
    series, trending terms, LLM keywords
  * `etsy` (buyer) for **everything** else — competitor shops, listings, reviews, SERP
  * a competitor's `shop_id` **never** enters a private URL: that placeholder is *who
    we are authenticated as*, not *who we are asking about*
**Rejected:** using the private tier wherever it happens to be convenient, or reusing
the seller session for competitor research because it is already open.
**Consequence:** the competitor tracker (D-25) is a **public**-tier build, which is
also why it can run at whatever frequency the scheduler wants. It also means the two
tiers need two Chrome profiles — the extension's role is a single global, so one
profile cannot serve both.

---

## Open decisions (not yet made)

| # | Question | Blocked on |
|---|---|---|
| ~~O-1~~ | ~~`scoring.py` or `scoring_engine.py`~~ | ✅ closed — neither existed; both written |
| O-2 | Append-only table vs separate history table for `trends`? | ✅ closed — append-only with `collected_at` in the PK |
| O-3 | Which signals survive the move to official APIs? | the signal-survival matrix |
| ~~O-4~~ | ~~Real tool count~~ | ✅ closed — 31 operator tools, 23 functional |
| ~~O-5~~ | ~~The three source-doc contradictions~~ | ✅ closed — see `WHATS_ACTUALLY_THERE.md` |
| **O-6** | Which Etsy public parameters exist beyond the 13 in use (`page`, `min`/`max`, `attr_2/3`)? | reading Etsy's own filter UI — guessing is what this project keeps getting burned by |
| ~~O-7~~ | ~~Calendar or search box as the home screen?~~ | ✅ closed — **calendar first, search as second door** (D-20) |
