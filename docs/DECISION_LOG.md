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

## D-30 — A diagnostic must verify it is reading the right database, and must not cry wolf

**Date:** 2026-08-14.
**Context:** `vault_status` reported zero usable profiles on all three platforms and
recommended fixing the Chrome extension. The vault was in fact full — 38 valid
profiles. Two Redis servers share port 6379 (Docker's proxy on `0.0.0.0`, a native
Windows Redis on `127.0.0.1`); `localhost` resolves to loopback first, so Python read a
stale leftover while the Go server wrote to the container. Every symptom pointed
convincingly at authentication. **This is the plausible-wrong-number failure in
infrastructure form** — nothing crashed, nothing was inconsistent, the answer was
simply about a different database.
**Chosen:** Two rules for any status/diagnostic tool here.
  1. **Confirm the source before diagnosing the contents.** `vault_status` probes
     sibling addresses on the same port and, if one holds a fuller vault, reports
     *that* instead of blaming anything downstream. "Empty" and "looking in the wrong
     place" are different findings and must never share an output.
  2. **Separate blocking from warning.** The first version treated a missing
     `user_agent` and a missing heartbeat as blocking and declared 20 working profiles
     unusable. A tool that cries wolf gets ignored, and then the real outage is missed.
     `core/test_vault_status.py` pins the classification (19 assertions).
**Rejected:** hardcoding the container IP without detection — `172.31.144.1` is a
vEthernet address that can change on reboot, which would silently recreate the bug.
**Consequence:** Generalises beyond Redis. Any "the data is missing" report must first
establish it is looking where the data is written — the same discipline as D-24, one
layer down.

---

## D-31 — Rank by winnability, not market size; and the target is SaaS-grade

**Date:** 2026-08-15.
**Context:** The operator asked whether this was being built with an SEO, analytics and
marketing head, or only an engineering one. The honest answer was the latter, and it had
a cost sitting in shipped code: `discover` ranked candidates by **search volume**. Every
number was correct and provenance-tagged, and the list was still backwards.

| Term | Volume | Supply | Demand/listing | CVR |
|---|---|---|---|---|
| `home decor` — ranked 1st | 310,467 | 2,160,627 | 0.14 | 0.00005 |
| `backpack name tag` — ranked 17th | 69,874 | 25,031 | **2.79** | **0.00279** |

19× the demand per listing, 56× the conversion rate, buried under three walls.

**Chosen:**
  * rank on **demand per listing** with CVR as the tiebreak, and **expose the ratio**
    rather than a composite score — "you cannot rank here" must be checkable
  * three named verdicts (`winnable` ≥1.0, `contested` ≥0.25, `wall` below), coarse and
    stated rather than tuned, because they separate a wall from a chance and are not a
    prediction
  * an unsized term is `unmeasured` and keeps its place, never a 0 ratio (N-02)
  * a fourth review lens — **winnable** alongside honest, profitable, timely — enforced
    by the new `etsy-seo-and-opportunity` skill
**Rejected:** a single opportunity score (ranks identically, explains nothing);
dropping unsized terms; tuning the thresholds to the current sample.
**Consequence:** `home decor` moved from 1st to 10th. Correctness and usefulness are
separate tests, and this repo had only been enforcing the first.

**Also decided: the target is a SaaS-grade product**, with one honest limit recorded in
`GOAL.md`. The quality bar (config not code, safe refusals, self-diagnosis, provenance)
is adopted now and costs nothing. But the private tier authenticates as the operator's
**own seller account** (D-29), so multi-tenancy would mean holding customers' seller
sessions and scraping Etsy as them — one ban is a customer's business, not a re-login.
**The judgement layer is sellable; the access layer is not.** Investment therefore goes
into keeping the judgement layer pure, provider-agnostic and offline-testable, and not
into making scraping prettier.

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

---

## D-32 — A filter is trusted because it passed, not because it exists

**Date:** 2026-08-19

**Context.** `locationQuery` was found to return a *broader* result set than the
search it filters. On a query with 10,011 listings, Germany returned 28,271 and
seven countries summed to **1116%** of the market they claim to partition. Every
number was real, well-formed, and meaningless as a share — and `find_gaps` had
been reading them as saturation percentages for the life of the project.

Eleven other filters fed the same analysis and had never been checked.

**Chosen.** Audit every filter, record the verdict in `config/filter_trust.json`
with its raw evidence, and make `find_gaps` **refuse** any bracket whose filter
did not pass — returning `untrusted_source`, which outranks every other rule,
including a thin bracket with proven demand.

**The result:** 9 of 12 cannot be believed.

| status | filters |
|---|---|
| trusted | `delivery_days`, `gift_wrap`, `is_personalizable` |
| ignored | `min_rating` (returns 4.8-rated listings), `best_by_etsy`, `holiday` |
| not a subset | `attr_1` (colours sum to 562%), `is_digital` |
| unstable | `is_star_seller`, `is_discounted`, `free_shipping`, `locationQuery` |

**Rejected: trusting a filter until it visibly breaks.** `unverified` is the
default status and is deliberately *not* `trusted`. Absence of evidence is exactly
what let `locationQuery` run unchallenged.

**A second finding made the first pass too harsh.** `organic_listings_count` is an
**estimate** — identical unfiltered searches returned 217,196 / 217,196 / 217,395.
`COUNT_JITTER` (2%) absorbs that drift. Reclassifying the *stored evidence* rather
than re-probing moved three filters from "broken" to the accurate "ignored", which
is why the registry keeps every raw observation.

Verdicts go stale after 90 days. Etsy changes.

---

## D-33 — Two projects, one browser, separate vaults

**Date:** 2026-08-19

**Context.** The Chrome extension, the Go cookie server, the Redis container and
`docker-compose.yml` all belong to this repo. A second project (`pinterest-apify`)
is a guest on that infrastructure, reading `cookie:pinterest:*` from the same
`db 0`. Both projects *manage* that store: our `plan_prune` iterated all three
platforms and would delete profiles they depend on; their `mark_blocked` shrinks
our pool. Not a bug in either — two owners of one mutable store.

**Chosen.** Keep the write path exactly as it is (one browser, one extension, one
Go server, writing db 0) and stop *reading* it. This project reads **db 1**;
`core/vault_mirror.py` copies one-way into it. Same server, separate logical
database, and nothing on their side changes at all.

**Rejected: routing the Go server to two databases.** It would have required
editing the writer both projects depend on, and a mistake there starves the other
project silently — which happened once during this work and was caught only by
re-reading the compose file.

**The trap it creates, and the rule that closes it.** A copy goes stale;
`HEARTBEAT_MAX_AGE` is 300s, so five minutes after a sync every profile reads
stale and the vault looks **empty** while Chrome is beaming fine cookies into
db 0. So **anything that judges db 1 must refresh it first** — `preflight` and
`vault_status` both do. `ScraperConfig.REDIS_URL` also *defaults* to db 1, so an
unloaded `.env` cannot silently re-merge the projects.

---

## D-34 — Demand inside a bracket is inferred from its listings, and refused when thin

**Date:** 2026-08-19

**Context.** D-10 requires demand to be shown *inside* a bracket before it can be
called a gap. Nothing ever supplied it, so `find_gaps` received `{}` and every
thin bracket returned `thin_but_unproven`. The 🎯 feature was structurally
incapable of a positive result for the project's whole life.

**The constraint.** Etsy reports search volume per **term**, never per bracket.
There is no "how many people searched for gift-wrapped mugs" anywhere, so this
cannot be looked up.

**Chosen.** Infer it from the listings that occupy the bracket, using the only
per-listing demand evidence the public SERP carries: review counts. Each of the
evidence's limits becomes a refusal rather than a caveat —

* reviews are **lifetime**, so they are labelled demand *evidence*, never a rate,
  and never multiplied into a projection;
* a card whose count did not parse is **excluded**, not zeroed (N-02);
* ads are excluded — a paid slot proves spending, not conversion;
* fewer than 4 organic cards yields **no median at all**: two listings with 400
  reviews each are `unmeasured`, because a median of two is arithmetic;
* an untrusted filter is **refused by name** (D-32), distinct from unmeasured —
  we did not fail to look, we declined to.

**Rejected: requiring the bracket to beat the market median.** In a market where
nobody buys, every bracket would look healthy. An absolute floor decides; the
market baseline is reported alongside so the comparison stays checkable.

---

## D-35 — An unverifiable session is deprioritised, not destroyed

**Date:** 2026-08-19

**Context.** `cookie_vault` checked freshness only `if last_updated:`, so a
profile with **no heartbeat** skipped the check entirely and was served forever —
a missing heartbeat read as a fresh one, N-02 inside the access layer. The
reference implementation in `pinterest-apify` evicts these outright.

**Chosen.** Prefer profiles with a fresh heartbeat; fall back to a heartbeat-less
one only when nothing better exists, and say so loudly. **Do not evict it.**

**Why the departure.** That project can afford eviction — its extension actively
beams the one account it needs. Here `private_seller_1` has no heartbeat and *is*
the operator's seller session; `plan_prune` preserves it deliberately as "the one
verified-working seller profile [which] predates the heartbeat field", and nothing
beams it back. Unknown freshness is not freshness, but it is also not proof of
death, and destroying the irreplaceable on a suspicion is the expensive direction
of this error (D-29).

**Also rejected: making "no heartbeat" a blocking problem in the diagnostic.** It
was tried and reverted within minutes — `test_vault_status` failed and its
docstring explained why an earlier version had made exactly that mistake, reporting
a vault of 20 working profiles as "0 usable". A diagnostic that cries wolf is worse
than none.

**Related, same commit:** `session_manager.classify()` now separates
`rate_limited` / `malformed` / `auth_expired` / `blocked`. Only the last two evict,
so neither Etsy throttling nor a bug in our own request can retire the seller
account — the old code evicted on 429.

---

## D-36 — Measure saturation from listings, and refuse the verdict the sample cannot support

**Date:** 2026-08-20

**Context.** D-32 left three trustworthy SERP filters out of twelve. The gap
analysis was designed around ten dimensions. The question was whether to find
substitutes or shrink the analysis.

**Chosen: both, honestly.** The lost dimensions — star seller, free shipping,
discounting, rating — are not gone from the *data*, only from the *filters*. Each
is a field on the SERP cards already fetched, so they are counted directly. That
is better in kind: a card count is something observed about listings we can name;
a filter count is a number about a result set that may not be a subset of this
market.

**And it is usually still not enough.** Twelve slots render server-side, about half
are ads, so the organic sample is 6–11. A share from six observations has a 95%
Wilson interval spanning both the thin (5%) and crowded (30%) thresholds, so it
cannot place the bracket on either side. Every measurement therefore carries
`low`/`high`, and `can_discriminate()` withholds any bracket whose interval
straddles a threshold — the same refusal `scoring.can_discriminate()` makes.

> **0 out of 6 does not establish an empty bracket.** The true share could still
> be 39%. D-10's original trap — reading 0% saturation as a loophole — is now
> caught by the statistics before any rule has to fire.

**Rejected: reporting the point estimate alone.** "33% offer free shipping" from
two hits in six is exactly the well-formed wrong number this project is named
after.

**Rejected: one combined classification.** Card counts are out of ~9 listings;
filter counts are out of total supply. Mixing them would report 67% saturation as
0.003%. Two classifications, two denominators, labelled.

**The unlock, found while doing this.** `organic_listing_ids` had *always* been
empty — the regex required `"result_count"` within 200 characters of the array and
the real neighbours are `bucket_id` / `user_id` / `is_async`. It failed silently
because an empty list is plausible for a page with no results. Anchoring on the
array returns 39–51 ranked ids. Fetching those pages is the affordable "measure it
per listing", and is what turns these intervals decisive. It also unblocks rank
tracking, which had been reading an empty list all along.


---

## D-37 — Buy the sample when the answer is worth requests, and label the instrument

**Date:** 2026-08-20

**Context.** D-36 recovered the lost gap dimensions by counting card fields, and
found them usually indecisive: nine organic cards cannot separate thin from
crowded. The fix is not better arithmetic, it is a bigger n — which
`organic_listing_ids` can now supply.

**Chosen.** Open listing pages in rank order and measure the same attributes at
one request each. Live on "personalized towel", 6 cards → 25 listings turned
free shipping from `33% [10–70%]`, withheld, into `64% [45–80%]`, decisive.

**Rank order, not random.** The top of the ranking is what a buyer meets and is
the population every saturation claim here is about. A random sample of all 51
would answer a different question, and answer it worse — the tail is not what
competes.

**Off by default.** `LISTING_SAMPLE = 0`. A 40-listing sample across 5 niches is
200 public requests; that is the operator's decision, not something a run does on
their behalf.

**Two things this does NOT claim.**

1. **That the small sample was wrong.** Free shipping moved 33% → 64%, but the
   card reads a *parsed field* and the page match is a *prose marker* — different
   instruments as well as different sizes. Both readings are kept, and a
   disagreement that large is itself the finding.
2. **That a bigger n resolves everything.** 5-star sits at 32%, on the crowded
   threshold, and still refuses at n=25. The interval straddles the line wherever
   it is centred. A test pins that case, because "32.5%, definitely crowded" is
   exactly the sentence this work would otherwise invite.

**Rejected: inferring discount from the listing page.** No reliable field exists
there, and the prose is ambiguous. It stays a card-only measurement — missing
beats faked.


---

## D-38 — A disagreement between sources is the output, not a problem to resolve

**Date:** 2026-08-20

**Context.** The Cockpit shows one candidate. The obvious design is a single score
combining Pinterest timing, Etsy demand and Etsy supply.

**Chosen.** Three panels, each read on its own, and the verdict **last and below
them** — physically, so a reader cannot reach the conclusion without passing the
evidence. When the sources point opposite ways, that is stated as a conflict.

Live on `christmas ornament`: Pinterest times it perfectly (list by 16 September,
peak 9 December) and Etsy says 0.018 demand per listing — unrankable. A blended
score calls that middling. It is not middling; it is two confident readings
pointing opposite ways, and their average describes neither.

**Why this specifically.** The sources fail *differently*. Pinterest can be
confident about timing for a term nobody searches; Etsy Private can report healthy
volume behind two million listings. One number hides exactly the case worth seeing.

**Two refusals in the trend, which is where a confident lie was easiest.**

* **Readings minutes apart are not history.** A term swept five times in one
  evening has five rows and no trend. "0% change over eight minutes" would be
  worse than reporting nothing.
* **A change against a degraded baseline is not a change.** `ceramic planter pot`
  reads 4,776 → 589, an 88% collapse — against a reading that had fallen back to a
  default CVR. That difference measures our instrument. Refused, with the reason.

**Rejected: hiding a sub-threshold move.** A 2% change is reported and flagged as
noise. The operator should see that nothing happened, not that nothing was looked
at — those are different facts.

**A default CVR is a blocker, not a footnote.** A term with an excellent
demand/supply ratio and a guessed conversion rate still gets a no, naming the guess
as the reason.


---

## D-39 — Discover finds the long tail, and folds the walls rather than filtering them

**Date:** 2026-08-20

**Context.** The system judged terms the operator typed. It should also FIND them,
because the winnable ground is in the long tail (D-31) and the operator cannot type
what they have not thought of.

**Chosen.** Expand every watched seed through the LLM keyword endpoint — ~120
neighbours, each carrying its own volume and supply, so one private call sizes a
hundred candidates. Rank by demand-per-listing, attach the seasonal moment, store
the whole pool.

Live proof: `custom family name necklace` (ratio 1.744, winnable) was found by
expanding `mom necklace`, which is itself a wall. The operator never typed it.

**Fold the walls, do not filter them.** A pool of 1,170 is 1,163 walls behind 7
terms worth a look. The screen leads with the 7 and folds the walls into one
counted line. That is a display choice — every candidate is stored, and the hidden
count is always shown — not a filter that would let "the pool was small" masquerade
as "nothing was discovered".

**Rejected: dropping walls at storage time.** "These 130 neighbours are all walls"
is a real answer worth keeping: it is 130 dead-ends the operator does not retype,
and a later run can show a wall becoming contested as supply shifts. Time is
first-class; a wall today is data tomorrow.

**Rejected: ranking by volume even here.** `personalized gift` has 230,715 searches
and a 0.364 ratio; `custom family name necklace` has 11,642 and 1.744. A volume
sort floats the big wall to the top of the very screen built to prevent that.


---

## D-40 — The Blueprint is on demand and live, and momentum is a first-class warning

**Date:** 2026-08-20

**Context.** Every screen reads the database and never calls the network, because
a dashboard must render instantly. The Blueprint is the exception, and the
exception is principled.

**Chosen: live, on demand.** A blueprint is built once, when the operator has
decided to list something, and it needs the CURRENT page-one tags. Stale tags would
seed a new listing with last month's competition. So `blueprint_page` fetches live
(demand + ~6 competitor listings) and is a command you run, not a page that must be
fresh on open. This does not violate the "a click never waits on a provider" rule —
there is no click; it is a deliberate generation step.

**Momentum is promoted to the top of the page.** The generator already carried
`wow_change`; the screen makes it a banner, because a winnable-looking term
collapsing week-over-week is the single most common way a high demand-per-listing
ratio misleads. Proven on the live run: `custom family name necklace` has a 1.744
ratio (Discover called it the best winnable term) and reads **-80% week-over-week**.
The ratio said go; the momentum said trap. Both are now on the same page.

**The generator's refusals reach the screen intact.** Only 2 of 13 tags had
measured support; four page-one tags exceed Etsy's 20-char limit and are shown
struck through, not copied. A thin blueprint is the honest output for a term whose
winners tag in phrases too long to reuse — and a full set copied blind would have
lost exactly those tags silently. The warnings block is rendered prominently
because it is the useful part when a candidate is weak; a strong blueprint shows
none.


---

## D-41 — One read layer; the app and a future server are two thin consumers of it

**Date:** 2026-08-20

**Context.** The operator asked for a real app — dashboard, filterable tables,
tracking, Etsy + Pinterest intelligence combined, product-type and search filters
— and, asked to choose between a no-server snapshot app and a full FastAPI + React
build, answered "all". The two must not become two codebases.

**Chosen.** Put every view's data behind ONE read layer, `etsy/ui/app_data.py`,
returning plain JSON from the database only. Presentation reads through it and
never past it. Then:

  * the snapshot app (`app_page.py`) bakes `build_snapshot()` into one
    self-contained HTML file — no server, no CDN, opens offline, refreshed daily;
  * a FastAPI server, when built, wraps the same `build_*` functions as endpoints
    and a React SPA consumes them.

Adding the server changes the read layer's callers, not the read layer — so "all"
is reachable incrementally, and neither consumer blocks the other.

**Rejected: building the FastAPI + SPA first.** It is weeks of work against the
project's no-daemon grain, and it would have delayed every interactive view behind
a server the operator does not need to run. The snapshot app delivers the dashboard,
filters, charts and combined views now; the server adds only what a snapshot cannot
— live queries and phone-from-anywhere — later.

**Rejected: a framework or a CDN.** A file opened from disk must render without a
network. Vanilla JS and inline SVG keep it one self-contained file, which is also
what lets the daily scheduler treat it like every other generated page.

**The discipline holds because the read layer holds it.** Demand and competition
are separate objects (never merged into one denominator), every number carries its
basis, and absent stays null rather than becoming zero — the client styles a
default CVR or a bound distinctly from a measurement.


---

## D-42 — The server is the read layer over HTTP; one live path, honestly gated

**Date:** 2026-08-20

**Context.** D-41 put every view behind `app_data` so a server could be added
without a rewrite. The operator asked for the server too. This is it.

**Chosen.** `etsy/server/app.py` (FastAPI) wraps each `app_data` function as an
endpoint and serves the SAME `app_page` frontend fed a fresh snapshot per request.
It adds exactly two capabilities a static file cannot have:

  * live from the database on every request, reachable from another device;
  * `POST /api/analyze/{term}` — the real pipeline for a keyword the operator did
    not have watched, measured now and stored so it joins the daily data.

Proven end-to-end: `custom dog portrait`, never seen before, judged in one call
(5,076 searches / 235,935 listings = 0.022, a wall).

**The one live path is gated, not trusted.** It syncs the db-1 mirror first (D-33)
so a stale copy does not read as an empty vault, then refuses FAST with a fix
message if the pool is genuinely empty rather than hanging (the old unbounded-wait
failure). It is a deliberate POST, never triggered by a page load. Every other
endpoint reads the database only.

**Rejected: a React SPA.** The static app is already the frontend; the server
reuses it. A separate SPA would be a second UI to keep in sync with no capability
the reused renderer lacks.

**Rejected: making the server the default.** It is a daemon, against the project's
grain, and it exposes private market data with no auth. The batch scheduler and the
static files remain the default and need no server; the server is opt-in
(`run_server.cmd`), bound to 127.0.0.1 unless `HOST` deliberately opens the LAN.

## D-43 — Rankable is not the same as bought: a second, relative gate on intent

**Date:** 2026-08-20

**Context.** Reported by the operator: *"sometimes I take a trend from Pinterest,
I go to the keyword, and I find it's dead — not winnable."* Traced, and the
mechanism is structural rather than a bug.

DISCOVER expands a seed through `get_similar_keywords`, whose ~120 edges carry
`search_volume` and `avg_total_listings` inline — which is what makes the crawl
affordable. But that endpoint returns **no CVR at any price**. So `winnability()`
was dividing searches by listings, two supply-side facts, and calling the result a
verdict. A term with real traffic and few competitors scored `winnable` on traffic
alone, however few of those searchers ever checked out. That is the standard shape
of a Pinterest-sourced trend: the interest is genuine, aspirational, and never
reaches a basket.

Worse, a CVR tiebreak *was* coded into the sort and was dead code on that path —
the field it read is never populated for an expanded edge, so it silently
contributed 0 for every candidate for the life of the feature.

**Measured, on the operator's own pool.** Of the top 6 terms the Discover screen
was showing, 5 converted below half the pool median. `custom family name necklace`
— ranked **first**, and the term the Blueprint screen was built around — sits at
**0.15x** the median of the terms measured beside it.

**Chosen.** Two gates, in cost order. `winnability` (free, wide, supply-side) runs
first; `confirm_intent` runs only on the top `INTENT_CHECK_TOP_N` survivors, costs
one `results-data` call each, and compares the term's `query_cvr` against the
**median of the terms measured in the same run**. The headline verdict is the worse
of the two, and `weak_intent` is a verdict distinct from `wall` — they fail for
opposite reasons and the operator reads them differently ("someone else owns this"
vs "nobody buys this"). Both readings are kept whole; neither is averaged (B-05).

**Rejected: an absolute units-per-week threshold — and this is the important half.**
The obvious design is `volume × query_cvr` = orders, reject below N orders/week. It
was built first, and thrown away when it was checked against observable evidence:

| | |
|---|---|
| `personalized gift` | 209,917 searches/mo × `query_cvr` 0.00018970 |
| implies | **39.8 orders/month for the entire market** |
| but its #1 listing carries | **14,733 lifetime reviews** |

One listing would need ~30 years to accumulate that, against 705,767 competitors,
and reviews are only a fraction of orders. So `volume × query_cvr` is wrong by at
least two orders of magnitude. Etsy's `query_cvr` is a rate against a denominator
it does not publish — **it is not the fraction of searches that become orders.**

**Consequence, and a pre-existing defect corrected.** `opportunity.market_demand()`
has always made exactly that claim ("Weekly units the MARKET buys", basis
`measured_market_wide`). It is wrong, and it now says so: `basis` is
`relative_only`, with `not_an_order_count: True`. The blast radius was small
because good design contained it — the figure is *displayed* beside the verdict and
only reaches `profit.verdict` when an explicit `capture_share` is supplied, so it
never silently set a go/no-go. It was a wrong number on screen, not a wrong
decision.

What survives is the **comparison**. `query_cvr` is one field from one endpoint,
defined identically for every term, so a ratio between two terms carries
information even when the constant relating it to orders does not exist. The gate
uses only that property.

**Refuses rather than guessing.** Below `MIN_POOL_FOR_INTENT` (8) measured terms
there is no median worth comparing against, and the gate returns `unmeasured` with
basis `pool_too_small` rather than judging against noise — the discipline
`score_pool`'s `PoolTooSmall` already applies (D-15). A term whose CVR never came
back is `unmeasured`, never `weak`: branding an unmeasured term dead would reject
real niches on a missing field, which is the same error as calling an aspirational
one winnable, in the other direction (N-02).

## D-44 — JOIN 2: momentum is a third axis, not a fourth gate

**Date:** 2026-08-20

**Context.** D-43 gave the pool a second axis (do these searchers buy?). Neither it
nor winnability can see whether interest in a term is **growing or dying** — Etsy's
own `wow_data` covers one week and nothing longer. Pinterest measures exactly that,
free, with no seller account at risk. `docs/market_map/analysis/combinations.md`
calls this the highest-value join in the system.

**Rejected first: the stored-topic join.** The obvious implementation joins the
momentum already in `trend_observations`. Probed before building, and it returns
nothing, ever:

| Check | Result |
|---|---|
| 84 stored Pinterest featured topics vs 1,333 discovered Etsy terms | |
| Exact content-word matches (what D-17 requires) | **0** |
| Containment matches, either direction | **0** |
| Topics sharing *any* content word | 64 of 84 |

Pinterest writes editorial phrases ("Apple-Themed Preschool Activities"); Etsy
candidates are product keywords. Identical to the vocabulary mismatch that silently
emptied the calendar for the project's whole life — a known shape, caught this time
by probing first.

**Chosen.** Ask Pinterest about **our** terms directly. `/metrics/` accepts ~50 terms
per call and the pool surviving both Etsy gates is far smaller, so the whole join
costs **one Pinterest request per run**, no matching logic, nothing to get wrong.

**Two properties of the instrument, both measured.**

*Pinterest DROPS terms it does not track — it does not return zeros.* Asked for 7
real candidates, it returned 3. A term missing from the response is `unmeasured`,
never "no momentum" (N-02). Coverage is genuinely partial and that is a fact about
the instrument.

*`100.01` is a display sentinel, not a measurement.* Pinterest caps its own UI at
"10,000%+", so any raw value at or above `100.01` is that cap. Reading it as a real
10,001% rise would make every censored term the best in the pool. `clamp_change`
already encoded this; the join reuses it rather than reimplementing it.

**Momentum does not change any verdict, and that is deliberate.** It attaches beside
the Etsy verdicts and reports disagreement (B-05, D-38). Two measured reasons:
Pinterest covers under half the pool, so gating on it would reject terms for absence
from an instrument rather than for evidence; and a fading term still has today's
demand, which makes it the operator's call rather than the system's. Precedent
exists — D-40 promoted `wow_change` to a banner, not a gate.

**Thresholds are ±10% month-over-month**, coarse and named like every other threshold
here. MoM leads because week-over-week on a single term is mostly noise: a seasonal
term can swing 30% in the week it enters its ramp. Verified against live readings —
`christmas eve box` at **+70% MoM in August** is the Christmas ramp starting, and
`macrame plant hanger` at **−7%** correctly reads *flat*, not fading, because one
month can drift that far on noise alone. The threshold was not tuned to make any
term come out a particular way.

**Degrades rather than fails.** Pinterest is the one source with no seller account at
stake, so a session failure there skips momentum and keeps every Etsy judgement.
Observed on the first full run: the Pinterest heartbeats expired mid-sweep, and the
run completed with all four surviving candidates judged and
`momentum_note` naming the cause.
