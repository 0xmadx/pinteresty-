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

## D-45 — Etsy's own seasonal curve was being fetched and discarded

**Date:** 2026-08-20

**Context.** The calendar's timing comes entirely from Pinterest moments — one
source, unchecked. `combinations.md` §JOIN 1 asks for two independent seasonal
sources so they can confirm or contradict each other. Looking for the second one, it
turned out to be already paid for.

**The finding.** `chart-series-data` returns a `series` block carrying a **12-month
search-volume curve per term**. Every caller in this repo — `master_niche_finder`,
`private_comparison`, `private_recursive_spider`, `private_scoring_pipeline` — reads
`term_summaries` and throws `series` away. The system has been buying Etsy's own
seasonality on every batch call it has ever made and discarding it.

Measured live:

| Term | Peak | Trough | Swing |
|---|---|---|---|
| `christmas ornament` | Nov 163,930 | Feb 1,758 | **93.2x** |
| `felt garland` | Nov 6,784 | Aug 2,012 | 3.4x |
| `mom necklace` | **Dec** 16,683 | Jun 5,698 | 2.9x |

`mom necklace` peaking in December rather than May is the sort of thing only a
measured curve says — by search volume it is a Christmas gift before it is a
Mother's Day one, and the name implies the opposite.

**Rejected: `include_trendline: true`.** `08_capability_map.md` recorded this flag as
"we decline a free seasonality curve". Probed both ways on `christmas ornament`:
True and False return **byte-identical key structures**. The flag does nothing on
this endpoint. The curve was never behind it — it was in `series` the whole time,
and the note pointed at the wrong thing.

**Two guards, both from measurement.**

*The last bucket is partial.* Etsy sends `is_last_bucket_partial: true` and the final
point is the current month counted so far. A naive peak/trough scan reads it as a
collapse — `felt garland`'s apparent trough WAS that artifact. `profile()` drops it
from every judgement and reports it separately, labelled. The test pins the contrast:
the same curve reads `evergreen` with the flag honoured and a "5.6x seasonal
collapse" without it.

*A flat curve is not a season.* Every curve has a maximum, so without a floor each
evergreen term acquires a peak month, a deadline, and a place on the calendar.
`SEASONAL_RATIO = 2.0` separates the two, and `peak_month()` returns None for an
evergreen term — a hole the tests caught after the first implementation gated only on
`basis == "measured"`, which evergreen profiles satisfy.

**Terms Etsy cannot size are OMITTED, not zeroed.** Asked for four, the response
carried three. A missing term gets no entry, and `record_seasonality` refuses to
store a non-measured profile — a row in `keyword_seasonality` means "we read this
term's year", and storing a refusal would put an unmeasured term into the one table
built to be joined against Pinterest's calendar.

**`compare()` reports disagreement rather than resolving it** (B-05, D-38), with
three states: agree, disagree, and `None` for "only one source has a peak". `None` is
deliberately not `False` — one source cannot confirm itself, and that is different
from two sources conflicting.

**Cost:** one batched call per sweep for the entire watch list.

## D-46 — POD viability is priced off page one, never the market-wide band

**Date:** 2026-08-25

**Context.** Checking print-on-demand viability by hand, twice, with throwaway
scripts — the sign a workflow belongs in the codebase.

**The finding.** `results-data`'s `search_term_median_price` is not what the
listings that actually rank charge. On `personalized baby blanket`:

| | |
|---|---|
| API median band | $11.70 – $14.30 |
| page one, actually | $11.65 min, **$25.19 median**, $70.21 max (n=20) |

Both numbers are right and measure different populations: the band is market-wide
across all 104,368 listings, page one is the ~20 that rank. Winners charge
roughly double the market median. Since the margin floor is applied to a price,
anchoring to the band alone computes a COGS ceiling of $5.21 — near-impossible for
POD — where the real, page-one-anchored ceiling is $12.69, plausible.

**Chosen.** `etsy/analytics/pod_check.py` (`/pod <term>`) reports both
populations side by side, never merged, with the ratio between them. The
competitor cards needed for the real figure ride along free in the same
`results-data` response, so this costs no extra call.

**Never returns "profitable".** Printify's catalog exposes no price on a variant,
so the output is a ceiling plus a handoff to the operator to price it in the
Printify UI. A test asserts the string "profitable" appears nowhere in the
result.

**Lead time is reported as the frequently-decisive number**, not a footnote: a
10-day Printify handling floor closes Etsy's 7-day bracket outright, so the
operator competes on everything except speed. Unknown handling reads
`unmeasured`, never "cannot ship fast" — `can_ship_fast` returns `None` for
unknown data, and `None` must not collapse to `False`.

## D-47 — This vault does not mirror another project's sessions, even from the shared database

**Date:** 2026-08-25

**Context.** `Desktop\pinterest-apify` shares Redis db 0 with this project — its
own choice, made for convenience, not because either project needs the other's
data. It runs AdsPower / remote browsers behind per-profile proxies and writes
what it captures into the same keyspace this project's Chrome extension writes
to. Measured: **7 of the 9 pinterest profiles in this project's pool belonged to
it**, meaning this system had been doing Pinterest work on sessions it never
captured — different browsers, different proxies, different exit IPs. A ban
earned by their traffic would land in our pool, and D-33's one-way mirror did
nothing to prevent it, because it only stops THEIR evictions shrinking OUR pool —
it never asked whose profile a given entry actually was.

**Worse, confirmed the same day:** `pinterest-apify` has its own export path
(`browsers/identities.py::export()`) that pulls **every** profile in
`valid_profiles:pinterest` — no ownership filter — and writes the raw cookies to
a local JSON file on its own disk. This project's `profile_ldu6ypke8` and
`profile_p5ewxsodn` were found sitting exported there. The database being shared
was never a passive fact; something on the other side actively reads and
persists whatever lands in it, ours included.

**Chosen.** `core/vault_mirror.py` adds `FOREIGN_PROFILE_PREFIXES` —
`("ads_",)`, the AdsPower naming pinterest-apify uses, distinct from this
project's `profile_<random>` (`chrome_extension/background.js:52`). A foreign
profile is skipped on the way IN, and any already copied by an earlier sync are
purged on every run — enforcing only on entry would leave pre-rule copies in the
pool forever, since `sync()` never deletes from the destination on its own.
Ownership beats freshness: a foreign jar is excluded even when its heartbeat is
newer than anything we hold, because the question is whose it is, not how recent.

**db 0 is still never written by this project** — the purge and the skip both
touch db 1 only. Verified after the change: their 7 `ads_*` jars remain present
in db 0 and in their own valid pool; their tooling is unaffected.

**Not chosen (yet): full physical separation** — a second Redis and a second Go
server that pinterest-apify never touches at all, ending the shared database
rather than filtering it. The identities.json finding is the argument for it: a
data-layer filter on our side cannot stop the other project from reading and
persisting our live cookies, only a genuinely separate database can. Planned as
the next step, tracked in ROADMAP.md.

## D-48 — MCP's `discover` tool now goes through `app_data`, closing a D-41 violation

**Date:** 2026-08-26

**Context.** An API-design audit (prompted by the operator asking whether the read
server's endpoints were actually used) traced every consumer of
`etsy/server/app.py`'s HTTP routes and found none — nothing in this codebase calls
them; not the static app (`app_page.py` is fully server-rendered, zero `fetch`
calls), not MCP. That finding on its own wasn't a defect: the server's job was
always "available for live/remote access," not "primary interface," and building
versioning/auth/RFC-7807 scaffolding for an API with zero real callers would have
been the same category of premature complexity already rejected once this session
(the parallel "React SPA + job queue + desktop shell" proposal).

**What the audit found that WAS a real defect.** Tracing MCP's own tools turned up
`discover()` querying `MarketDatabase().latest_discovered()` directly — a second,
independent implementation of "what counts as discovered," bypassing
`etsy/ui/app_data.py` entirely. D-41's whole premise is ONE read layer that "the
app and a future server" are two thin consumers of; MCP had quietly become an
unaccounted third consumer with its own copy of the query logic. `cockpit` was
safe (both HTTP and MCP call the same `etsy.engines.cockpit.build()`), but
`discover` could silently drift from what the web UI shows for the identical pool
— exactly the two-implementations-disagree failure this system is built to
prevent, just moved into its own tooling instead of the data.

**Chosen.** `discover()` now calls `app_data.build_discovered()`. Verified
before merging: `MarketDatabase(db_path="market_intelligence.db")`'s default
matches `app_data.DB_PATH` exactly, and `build_discovered()` is a strict,
field-whitelisted projection over the identical `latest_discovered()` call — no
behavioural difference, only an unused `collected_at` column dropped and
`momentum`/`cvr` now reaching the tool the same way the web UI already got them.

**Tested at the level that actually matters.** A behavioural test cannot
distinguish "went through app_data" from "queried the database directly" here —
the outputs are nearly identical either way, since `app_data.build_discovered` is
a thin wrapper. The property that matters is which CODE PATH runs, so
`mcp_server/test_server.py` asserts on the source directly (same pattern as
`core/test_preflight.py`'s D-33 sync check): `discover()`'s body must import
`app_data.build_discovered` and must not construct `MarketDatabase()` itself.

## D-49 — The db-0/db-1 mirror is retired; this project reads one database

**Date:** 2026-08-26

**Context.** D-33 built `core/vault_mirror.py` because `pinterest-apify` shared
Redis db 0 with this project — a mirror into a private db 1 meant our evictions
and prunes could never reach their sessions, or theirs ours. D-47 hardened that
mirror further, filtering their AdsPower profiles out on the way in. Both were
solving a real problem at the time. That problem is now gone: `pinterest-apify`
has moved to its own, fully separate Redis (`pinterest-redis`, port 6380) and no
longer touches db 0 at all — the physical separation D-47 marked "not chosen yet"
was completed outside this session, on the other project's side. With no shared
database left, the mirror was defending against a risk that no longer exists,
at real ongoing cost: a second copy that only refreshes when something remembers
to call `sync_if_stale()`, and — confirmed live below — silently drifts stale
between calls. That drift is what actually bit this project three separate
times this session (`CLAUDE.md`'s "3-day incident pattern": `vault_status` green,
a live run 401s minutes later), always traced back to db 1 holding a copy older
than db 0's real state.

**Chosen.** Deleted `core/vault_mirror.py` and its test file outright, rather
than leaving it dormant — dead code that constructs Redis connections is a
liability even unused, and the project already prunes hard for exactly this
reason (see `git log` around branch cleanup, same session). Removed every call
site: the `sync_if_stale()` call in each of the three live API client
constructors (`etsy/api/private/api.py`, `etsy/api/public/api.py`,
`pinterest/endpoints/api.py`), `core/preflight.py::require()`'s sync-before-judge
block, `core/vault_status.py::main()`'s `separation_check()` and its own sync
block, `mcp_server/server.py::_sync_mirror()` and its two call sites, and the two
`vault_mirror` imports in `etsy/server/app.py` (`/api/analyze`, `/api/health`).
`core/settings.py`'s `REDIS_URL` default moved from
`redis://localhost:6379/1` to `redis://localhost:6379/0` — the only vault now —
and `.env`, `.env.example` and `docker-compose.yml`'s three `REDIS_URL` lines
(go-api was already on db 0; python-scraper and etsy-server moved to match) were
updated the same way, with the `VAULT_SOURCE_URL` variable deleted everywhere it
appeared.

**`core/test_preflight.py`'s D-33 sync-coverage sweep — the one D-48 just
described — no longer tests a real property**, since nothing syncs any more.
Replaced it with a narrower regression: a tree-wide sweep asserting no module
still imports `vault_mirror` or calls `sync_if_stale()`/`_sync_mirror()`, so a
reintroduced reference fails loudly in the offline suite rather than raising
`ModuleNotFoundError` the first time some code path actually executes it. (The
first version of this check also matched the plain-English mention of
`vault_mirror.py` inside `core/settings.py`'s own historical comment — tightened
to match import/call syntax specifically, since a prose mention of a retired
module's name is exactly the kind of historical marker this log and `CLAUDE.md`
keep on purpose.)

**Verified live, not just offline.** Before this change, `vault_status` against
the mirrored db 1 reported **0 usable `etsy`, 0 usable `pinterest`** — profiles
last-heartbeat 938,240s and 1,105,609s ago (10+ days), because nothing had
called `sync()` recently enough to refresh them. Pointing `REDIS_URL` straight
at db 0 (no code change, same run) reported **1 usable `etsy`, 2 usable
`etsy_private`, 1 usable `pinterest` — vault is green**, and `core.preflight`
passed cleanly against the same database with zero mirror code in the path. All
57 offline suites (unchanged count — `core/test_vault_mirror.py` deleted,
`core/test_preflight.py` rewritten in place) pass.

**Docs updated the same day:** `docs/VAULT_SEPARATION.md`, `CLAUDE.md`,
`README.md`, `docs/ONBOARDING.md`, `docs/UI_GUIDE.md`, `docs/MCP.md` and
`ROADMAP.md` no longer describe the mirror as current. One round-trip was
needed: `docs/VAULT_SEPARATION.md`'s historical diagram and guarantees table
used present-tense labels ("pinterest-apify reads this, unchanged") even
though the surrounding section was already marked historical — read in
isolation (quoted without the section header) it looked like a claim about
today. Reworded to lead with current state and date the historical flow
explicitly, after the operator quoted exactly that block back as "is still
like this."

**db 1 itself was flushed the same day, not just stopped-reading.** Retiring
the code path left db 1's last-synced contents sitting inert in Redis —
verified directly: `db0` held 10 keys, `db1` held 11, the extra one being a
stale `cookie:pinterest:profile_ldu6ypke8` that no longer existed in db 0
(evicted from there by ordinary hygiene, a duplicate/stale session) but that
nothing had ever removed from the unread db 1 copy — the mirror only wrote
forward, it never pruned on its own. This is the concrete version of the
"mirror spreads sessions rather than containing them" risk: one live-looking
Pinterest session jar existed in a place nothing was watching. Backed up to
`data/vault_backup_<timestamp>-db1-retirement.json` (gitignored, same
convention as `vault_status --prune`'s backups) and `FLUSHDB`'d. Verified
after: `vault_status` and `core.preflight` report the identical usable
sessions as before the flush — proof db 1 was contributing nothing live,
exactly as expected once no code reads it.

## D-50 — `deep_dive_keyword` wires the BFS-crawl-plus-arbitrage engine into MCP

**Date:** 2026-08-27

**Context.** The operator pointed at `master_spider.py` — a top-level script, not
part of any package — and asked why it had no MCP tool. It doesn't, but the more
useful finding was what it actually is: a thin `ThreadPoolExecutor` wrapper that
runs `MasterNicheFinder`'s BFS keyword-crawl across several seeds concurrently,
last substantively touched in this project's very first infrastructure commit —
before `core/preflight.py` existed. It still uses its own unbounded polling wait
(`wait_for_minimum_profiles`: `while True: ... time.sleep(5)`), the exact hanging
failure mode `mcp_server/server.py`'s own design rules single out as "the worst
failure mode for an agent." It also only wraps the plain BFS crawl, not the
richer `etsy/engines/master_arbitrage.py::HybridArbitrageEngine`, which wraps
that same crawl AND adds the public-API gap/sourcing/arbitrage pass —
`README.md` already documents *that* as the real "full sweep on a seed keyword"
tool.

So the real gap was broader than the one file named: **no MCP tool did a BFS
crawl at all.** `analyze_keyword`, the closest existing tool, is one private
call plus one public call — no recursion into related keywords, no scoring, no
survivorship.

**Chosen.** Added `deep_dive_keyword(seed, product_type, max_depth, max_nodes,
cogs, shipping_cost, labor_minutes)`, wrapping `HybridArbitrageEngine` — not
`master_spider.py`. Reasoning: an MCP client can already call a single-keyword
tool repeatedly if it wants several, so `master_spider.py`'s only real
differentiator (thread-pool concurrency across seeds) was the least valuable
part to expose, and its unpreflighted wait was a defect to route around, not
carry forward. `max_depth=1, max_nodes=5` defaults match the engine author's
own `__main__` demo scale, keeping an unbounded-cost call from being the
out-of-the-box behavior. Preflights on `("etsy", "etsy_private")` before
starting, same as every other live tool here — this one more than any other,
given a run can take several minutes once started.

**A real bug found in the process, not invented for MCP's sake.**
`HybridArbitrageEngine.run()` had no `return` statement on its success path —
only ever called from its own CLI (`if __name__ == "__main__"`), which never
used the return value, just read the JSON file the method wrote to disk. Any
programmatic caller, MCP included, would have received `None` on a fully
successful run and `None` on a "nothing cleared the profit gate" run
indistinguishably. Added `return final_payload` (plus the report path) at the
end — additive only, no existing behavior changes, since nothing previously
read the return value.

**Cost is real and stated plainly, not hidden behind a uniform "live" tag.**
The engine spends roughly 41+ public requests per niche that clears the profit
gate, with deliberate `time.sleep(1)` pacing between many of them — several
minutes per call is normal, not a bug. `docs/MCP.md`'s tool table tags it
`live, expensive` rather than the plain `live` every other network-touching
tool gets, and its docstring says explicitly: call `analyze_keyword` or
`discover` first, reach for this once a seed already looks worth the cost.

**Verified:** `deep_dive_keyword`'s body preflights on both platforms before
constructing the engine (checked directly, same source-inspection pattern
`mcp_server/test_server.py` already used for D-41/D-48); all 57 offline
suites still pass. Not verified live — a real run costs real requests and
several minutes, and the point of this session's ask was the wiring, not a
fresh keyword analysis.

## D-51 — `daily_stats`: a free daily volume series sitting unread in `results-data`, plus an endpoint-doc audit that found three false "not built" claims

**Date:** 2026-08-27

**Context.** The operator had just been shown `pinterest-apify`'s `docs/wire/` —
a reverse-engineered, dated, endpoint-by-endpoint reference with a coverage audit
and a traps list — and asked directly: is this project's own endpoint
documentation missing that much too? It was, but not in the way "go document more"
implies. `docs/market_map/reference/pinterest.md` had already been rewritten to
exactly that standard **two days earlier** (2026-08-25). `etsy_private.md`,
`etsy_public.md`, both `analysis/` files, and both `docs/architecture/` summary
docs were still frozen at 2026-08-16 or 2026-08-12 — 11 to 15 days behind a
project that shipped D-43 through D-50 in that window.

**Three claims these docs made were not just old, they were actively false**,
each disproved by work already landed this session:
- `11_endpoint_reference.md`: *"the points series is not parsed yet"* — false
  since D-45 built `parse_chart_series` to read exactly that.
- `08_capability_map.md`: *"Momentum ❌ / Intent ❌ ... none wired"* — false since
  D-44 (momentum) and D-43 (intent, though a CVR-based gate, not literally the
  Pinterest `OUTBOUND_CLICK`/`SAVE` split this claim meant).
- `08_capability_map.md` route table: *"the calendar — both halves exist [not
  connected]"* and *"`get_trending_terms` — built, unwired"* — both connected
  since 2026-08-19.
- `etsy_public.md` / `11_endpoint_reference.md`: *"`organic_listing_ids` is
  always empty"* — false since the 2026-08-20 parser fix; now 39–51 ranked ids.
- `combinations.md`'s summary table was the worst offender: 3 of its 4 "❌ not
  yet built" rows were built within days of the date it was written.

**A genuinely new finding, not just a staleness fix.** Live-probing
`get_results_data` for this refresh (per the `etsy-pipeline-work` skill's Rule 1 —
diff the response keys against what the code reads) surfaced a top-level
`daily_stats` field: a day-by-day search-volume series with a rolling 7-day
average, riding on the SAME call `get_results_data` already makes on every
measured keyword — free, no extra request. Nothing in this codebase parses it.
This is the same shape as D-45's discovery (`chart-series`'s `series` block,
paid for and discarded) and D-14's (the quota that was never consumed) — a
signal already being paid for and thrown away. Different from `chart-series`:
`daily_stats` is daily resolution over roughly the trailing three weeks, not
monthly over a year, which is a materially sharper instrument for a
calendar-first product whose whole premise is "list by day N." **Found, not
built** — flagged in `market_map/reference/etsy_private.md` and left for the
operator to decide whether it's worth wiring in, matching how `get_trending_terms`
was flagged before D-43 rather than built unasked.

**Chosen.** Rewrote `market_map/reference/etsy_private.md` and `etsy_public.md`
to the same standard as the Pinterest doc (dated, live-reverified, exact payload
shapes) rather than patching individual lines. Added `market_map/reference/printify.md`
— a full third API client (`etsy/api/printify/`, added 2026-08-19, central to D-46)
had never had a reference doc at all. Corrected `analysis/etsy.md` and
`analysis/combinations.md`'s summary table and funnel diagram in place, keeping
the correction visible (struck framing, not silent edits) rather than rewriting
history — same convention as every prior correction in this log. Added staleness
banners to both `docs/architecture/` summary docs pointing at `market_map/` as
current, and fixed their worst individual false claims inline rather than leaving
a banner to do all the work.

**`etsy_public.md` also now cites `config/filter_trust.json` as the live source of
truth for the 12 known SERP filters** instead of restating a 2026-08-16 snapshot
— the registry is already re-auditable (`python -m etsy.analytics.filter_trust`)
and a static table next to it would just be one more thing to go stale.

**Confirmed still genuinely open, not newly found:** Etsy public pagination
(page 2+ is never requested — still the single biggest structural gap per both
the old and new capability map), Pinterest `OUTBOUND_CLICK` vs `SAVE` joined into
the intent gate, and demographics-into-tags (JOIN 4). Listed as open in both
places now, not silently dropped.

**Verified:** `get_results_data`'s live response re-probed 2026-08-27 (not just
re-dated) — `similar_search_terms`/`market_gap_recommendations` confirmed still
empty/null, `daily_stats` confirmed present with real data. All 57 offline suites
pass (docs-only change, no code touched).

## D-52 — The UI is deleted. MCP is the interface.

**Date:** 2026-09-01. **Supersedes D-42** (the read server). **D-41 survives** and
matters more, not less — see below.

**Context.** The operator asked for the MCP surface to be opened up and the UI
removed, saying plainly what they were struggling with: *"finding winning products
and searching large data."* They work through an agent, not a browser.

**The evidence was one-sided.** Three independent measurements, none of them
opinions about taste:

| | |
|---|---|
| Every UI file's git history | created 2026-08-19/20, **never touched again** — 12 days of zero iteration in a repo edited daily |
| `etsy/server/app.py` callers | **zero**, anywhere in the codebase (traced 2026-08-26 during an API audit) |
| MCP's reach into the system | **~34 of 455 public callables — 7.5%**; Pinterest's 97 callables at **0%** |

So the maintained surface and the used surface were inverted: 3,483 lines and 202
test assertions rendering HTML for one person who reads the system by asking an
agent, while the agent could reach a fourteenth of it.

**Chosen.** Deleted the 7 page renderers, `etsy/server/`, `run_server.cmd`, the
`etsy-server` Docker service, `docs/UI_GUIDE.md`, and the generated
`etsy/data/ui/`. Kept `etsy/ui/app_data.py` — the one read layer (D-41), now with
MCP as its *only* consumer, which is why D-41 is reinforced rather than
superseded: there is no second screen left to notice a wrong number.

**The dependency that was easy to miss.** `market_page.py` looked like pure
presentation — its name, its docstring, and 215 of its 239 lines were the Market
screen. But `gather()` (24 lines) was a DB-only read function called by **both**
`app_data.build_shops()` and the MCP `tracked_market` tool. Deleting the file
wholesale would have broken a live tool. Moved into `app_data.py` as
`gather_shops()`, and given the first test coverage it has ever had.

**A real test bug found while extracting.** `test_app.py` seeded two
`record_trend` rows without an explicit `collected_at`, letting each take the wall
clock — and `build_pinterest` returns only rows matching `MAX(collected_at)`. When
the two inserts straddled a second boundary the moment disappeared and the suite
died on an `IndexError`; it passed on rerun, which is the worst way for a test to
fail. Production was never affected (`trends_bridge` passes one shared timestamp
per run — verified: 97 rows share it). Fixed with an explicit stamp. This is
exactly the trap `etsy-pipeline-work` names: never mix a wall clock with fixed
data in one test.

**Two capability losses, both deliberate.** (1) `POST /api/analyze/{term}` measured
a keyword *and stored it*; the MCP `analyze_keyword` measures without storing
(verified). Read-only is the MCP invariant, so "measure and persist" belongs to the
scheduler — add the term to the watch list and the daily sweep picks it up.
(2) `blueprint_page.gather()` composed live demand + tag consensus into a listing
draft and has no MCP equivalent; it is to be ported to an `analyze` operation
rather than lost.

**The scheduler kept both UI-touching jobs.** `job_discover` and `job_calendar`
each do real data work and only rendered at the tail — `job_calendar` still
recomputes moments and writes `verdict_log` rows daily, which is what makes
"christmas flipped to list-now on the 16th" answerable at all. Only the last few
lines of each were removed.

**Verified:** 50 offline suites, **1,347 assertions**, 0 failures (was 57/1,531;
−202 from the 8 deleted suites, +18 from the new `test_app_data.py`). A real MCP
stdio round trip passes 19/19, and `tracked_market` was invoked directly through
the rewired path (2 shops returned) rather than merely imported. `job_calendar()`
was run for real and returned 5 moments with `list_now: [halloween, thanksgiving]`.

## D-53 — `mcp_server/` becomes a package, so the surface can grow

**Date:** 2026-09-01. Pure refactor — **zero behaviour change, proven** (below).

**Context.** MCP is now the interface (D-52) and reaches ~7.5% of the codebase.
Opening that up means adding many tools; the tools lived in **one 699-line
`server.py`**, flat, grouped only by five comment banners — and one banner had
already drifted (six tools sat under `# --- settings ---`, describing one of
them). Expanding that file was not viable.

**Chosen.** Split into a package that registers on import:

```
_plumbing.py          the shared `mcp` instance + _ok/_fail/_guarded/_preflight
tools_system.py       (3) can this run, did it run, what is it assuming
tools_opportunity.py  (5) is there room here
tools_economics.py    (3) does it pay
tools_decide.py       (4) what should I list, and when
tools_learning.py     (3) did it work
server.py             (69 lines) wiring + main() — no tool definitions
```

The `mcp` instance lives in `_plumbing.py` rather than `server.py` specifically
to avoid the circular import that the obvious arrangement produces: tool modules
need the instance to decorate against, and `server.py` needs the tool modules to
exist. `server.py` imports them for the **side effect** of registration, marked
`# noqa: F401` — deleting one of those imports silently removes its tools from a
server that still starts and answers perfectly well, which is why
`check_package_layout()` now asserts each module is imported.

**The tools were moved mechanically, not retyped.** A script split on
`@mcp.tool()` boundaries and asserted every extracted tool was assigned to
exactly one module (18 extracted, 18 assigned, no duplicates) — hand-transcribing
600 lines of docstring-heavy code is how a caveat gets silently dropped.

**Proof of no behaviour change.** The published tool surface was reconstructed
from `git show HEAD:mcp_server/server.py`, loaded in a subprocess, and diffed
against the new package's `list_tools()`:

```
tools before: 18      tools after: 18
MISSING: none    ADDED: none    SCHEMA CHANGED: none
published schema size: 12928 chars (~3232 tokens)  — identical
```

**`functools.wraps` is re-flagged at the top of `_plumbing.py`**, because the
split multiplies the chance someone adds a decorator: a bare `*a, **kw` wrapper
republishes the schema bug that once broke all 13 then-existing tools at call
time while `list_tools()` looked perfectly healthy.

**Two source-inspection tests were made layout-independent.**
`check_one_read_layer` (D-48) and `check_deep_dive_wiring` (D-50) opened
`server.py` by path and broke on the move despite nothing about their subject
changing — a test that fails on a file rename is testing the layout, not the
property. They now locate a tool's source anywhere in the package and report
which module it was found in.

**Verified:** the MCP suite goes 19 → **26 assertions** (+7 layout checks), a
real stdio round trip still registers all 18 and successfully CALLS four of them,
and no tool leaks `a`/`kw` into its schema.

## D-54 — stdout was a live protocol hazard, and `moment/metrics` was the missing endpoint

**Date:** 2026-09-01. Two findings from auditing the Pinterest layer before
opening the MCP surface to it.

### The blocker: a printing tool corrupts JSON-RPC

**The server speaks JSON-RPC over stdout, and the layers its tools call print
freely.** Ten `print()` calls sit under the Pinterest path alone —
`api.py`'s cache-hit line and three failure lines, `metrics`' local-serve line,
and `core/cookie_vault.py`'s "waiting for the extension" message, which fires
*exactly* when a session is missing and a tool is most likely to be invoked.
`mcp_server/` had **no stdout redirection anywhere** (grep-confirmed), so the
first Pinterest tool call would have corrupted the stream.

This is a nastier class than a wrong number: the failure is a **dead
connection**, so no `basis` field, refusal or guard downstream can express it.

**Fixed in `_guarded`**, not per-tool — `contextlib.redirect_stdout(sys.stderr)`
around every tool body. A tool author cannot forget it, and a library that starts
printing tomorrow is covered retroactively. stderr is the right destination: the
operator still sees the message in the client's server log.
`check_stdout_is_protected()` asserts it on both the success and the raising
path, since a guard that only holds when nothing goes wrong is not a guard.

### The gap: `moment/metrics`, the only sub-weekly series in the API

Diffing this project's actual call paths against the `pinterest-apify` wire
reference (a 20-endpoint index the operator built for that project) found four
endpoints we never implemented. Three are minor. The fourth,
`/ads/v4/trends/moment/metrics/{region}`, is **the only endpoint in Pinterest
Trends that resolves below weekly** — and this project is calendar-first. We were
calling `moment/available` for takeoff/peak *dates* and never fetching the
*curve* those dates sit on. Our own market_map doc did not catch it either: its
coverage table listed `moment/available` and never mentioned `moment/metrics`.

Implemented and **live-probed before being built on** (Rule 1 of
`etsy-pipeline-work`). Measured on `halloween`: `daily` + 365 → 365 points,
`weekly` → 66, `weekly` + `predicted_days=91` → 66 with 13 forecast.

**Two traps found by probing, both now handled at the wire boundary:**

1. **The wire returns the series NEWEST-FIRST** — `[0]` was 2026-11-23, `[-1]`
   was 2025-08-25. Every other series here is oldest-first, so a consumer looping
   forward reads every trend backwards. The method reverses to ascending and
   records it in `series_order`.
2. **`peaks[]` is forward-looking while most of the curve is history.** Declared
   peak 2026-10-19, observed max 2025-10-27 at 61, forecast max 79. Read the DATE
   from `peaks`, the HEIGHT from the forecast points. There is no
   `has_prediction` flag on this endpoint (unlike search `/metrics/`), so
   `is_forecast` is derived per point from a non-null upper bound.

**Trap 1 caught its own author**, which is why it is documented as a worked
example rather than a footnote: sampling the raw `[0]` gives `normal_counts: 2`
and reads as a collapsed forecast, when it is really the far tail three weeks
*after* Halloween. The claim "the forecast tops out at 2, understating by 30×"
was made and then disproved by the verification run — the real forecast peak is
79, slightly *above* last year's observed 61. Any summary statistic taken from
the head of an unreversed series describes the end of the story.

**Also:** every one of the five wire-measured 400/500 conditions
(`hourly`, lookback > 730, predicted > 91, interest_limit > 24, monthly + 91) is
refused **client-side before a request is spent** — a 400 costs a round trip and
returns `None`, which is indistinguishable from "no data" (N-02).

**Verified:** `pinterest/endpoints/test_moment_metrics.py`, **21 offline
assertions**, stubbing `_api_resource` with a deliberately DESCENDING fixture so
the reversal is pinned rather than assumed.

## D-55 — the grouped tool: 15 Pinterest operations for the price of two

**Date:** 2026-09-01. The first tool of a second kind, and the pattern every
future expansion follows.

**Context.** Pinterest had **zero** MCP coverage — ~97 callables reachable by an
agent only as a side effect of `calendar`/`cockpit` reading rows a scheduler job
wrote days earlier. Exposing it one-tool-per-capability was the obvious move and
the wrong one: measured, this server's tools average 718 chars of published
schema, so 15 more would cost ~10,770 chars of context **before any work starts**,
and would degrade tool choice besides.

**Chosen: one tool, an `operation` enum.** `pinterest(operation=…)` reaches all
15 capabilities for **1,705 chars** — an 84% saving on this slice.

**The saving is not the enum.** Publishing 15 operation names as enum members is
nearly free. What grouping avoids is paying the **~380-char per-tool envelope**
(name, title, `type: object`, `required`, the `inputSchema` wrapper, and the
repeated shared parameters `term`/`region`/`limit`) fifteen times instead of once.
That is the whole mechanism, and it is why this scales.

**Four contract rules, each with a measured reason** (SDK 2.0.0, pydantic 2.13):

| Rule | Measured consequence of breaking it |
|---|---|
| `Literal`, never `Enum` | an `Enum` subclass hoists into `$defs` behind a `$ref` — +28 chars and an indirection the agent must resolve |
| Required, never `Optional[Literal[…]]` | `Optional` collapses the enum into an `anyOf`, burying the options a level down |
| One `Field(description=…)` on `operation` | cheapest of the three documentation channels: 544 chars vs 579 for a dedented docstring vs 601 raw |
| Tool docstring stays ONE line | docstrings publish **verbatim including source indentation** (`base.py:78`, no `cleandoc`) — a multi-line docstring ships its leading whitespace on the wire |

⚠️ **Shared `Literal` aliases must be imported by bare name.** They live in
`mcp_server/_ops.py`, and MCP resolves annotations via
`inspect.signature(fn, eval_str=True)` against the **wrapped function's own
module globals**. An alias reached through a namespace raises `InvalidSignature`
at registration.

**Argument validation runs BEFORE preflight**, which matters more here than
anywhere: constructing a Pinterest client on an empty vault is a bounded
**120-second busy-wait** that then raises. `pinterest(operation="metrics")` with
no `term` is refused from the arguments alone — it never reaches Redis, let alone
the constructor. Asserted by source order, not by comment.

**`store=False` on the MCP path.** With the SeriesStore active, `metrics()`
returns *two different row shapes* — a wire row with `date`/`normalizedCount`/
bounds, or a locally-served row with only `count` — depending on what the store
happens to hold. Same arguments, different shape, and `split_forecast()` on the
second silently reports everything as observed. For a surface whose consumer is a
model reading the shape, that is the real hazard. `_ops.normalise_series()`
flattens it regardless, and also absorbs the **three different spellings** of the
upper prediction bound across search `/metrics/`, `category_metrics` and
`moment_metrics`.

**Findings are stated, not left as empty results.** `etsy_competitors` returning
`[]` carries an explicit `finding` explaining that no Etsy seller ranks there —
measured zero in Area rugs, Bath mats, Candles and Cake decorating — because an
empty list otherwise reads to a model as a broken call rather than as "mass
retail owns this niche."

**Verified live**, not just registered: `operation="moments"` returned 13 moments
(13 dated), `operation="related"` returned 5 terms each carrying its own 53–66
point series free in the same request, and the missing-argument path refused
cleanly. Published surface now **14,633 chars ≈ 3,658 tokens** for 19 tools
reaching 33 capabilities — still under the 4,000-token ceiling the plan set.
MCP suite 30 → **40 assertions**, including that `operation` publishes as a
top-level `enum` with no `$ref` and no `anyOf`.

## D-56 — the context budget becomes a test, and it immediately failed

**Date:** 2026-09-01.

**Context.** Adding `pinterest_research` (11 composed operations over
`pinterest/products/`) pushed the published surface to **4,120 tokens** — past
the 4,000-token ceiling the phase plan had set. The plan's own words were "fail
the phase if it exceeds that."

**The temptation was to raise the ceiling**, since 4,120 is not obviously worse
than 4,000. Rejected: a budget that moves whenever it binds is not a budget, and
every tool schema is resident in the agent's context for the entire session, so
this number competes directly with the work the agent is there to do. The
grouped-tool design exists precisely to hold this line while capability grows.

**Chosen: reclaim the space instead.** `_plumbing.strip_schema_titles()` removes
Pydantic's auto-generated per-parameter `title` from every published schema —
`"title": "Category Id"` beside a property already named `category_id`. It
repeats the property name, on every tool, in every session.

Measured: **15,369 chars ≈ 3,842 tokens**, down from 16,483 ≈ 4,120. **1,114
chars reclaimed**, back under the ceiling with 20 tools reaching 44 capabilities.

**Safe, and verified rather than assumed.** MCP validates arguments against a
separate `arg_model` built at registration, and `list_tools()` reads
`info.parameters` live at call time — so editing it in place changes only what is
published. Confirmed after the change: tools still execute, and
`pinterest(operation="not_a_real_op")` is still rejected with the identical
`ToolError`. **`description` is deliberately never stripped** — that is the one
channel an agent reads to choose correctly, and it is where this server's
guidance lives.

**The ceiling is now an assertion**, not a note in a plan: `test_server.py` sums
every published schema and fails if the total exceeds 4,000 tokens, reporting the
three largest tools so the next person knows where to look. A companion check
asserts the titles stay stripped, and a third asserts the operation
*descriptions* survived — a strip that took those with it would be invisible
until an agent started choosing badly.

**Also in this change:** `pinterest_research` skips preflight entirely for its
two local operations (`alerts`, `history`). They read the local archive and need
no Pinterest session, so gating them on one would refuse work that can plainly be
done — verified live: `alerts` returned 45 events across 6 archived weeks with no
session involved.

And `alerts` states the difference between *no movement* and *not enough
history*: with fewer than two archived weeks it returns a `finding` saying so,
because an empty event list otherwise reads as "nothing changed" when the truth
is "a diff needs two readings and cannot be backfilled."

## D-57 — the crawl gets a wall an agent cannot argue past

**Date:** 2026-09-01.

**Context.** `keyword_crawl` is the operator's stated need — one seed in, the
whole long-tail neighbourhood out, each term sized for winnability — and it is
**the single riskiest tool on this surface**, for the same reason. It spends
`etsy_private`: the operator's own seller account, the one asset here that
cannot be replaced (D-29).

The cost compounds three levels deep, measured:
`get_similar_keywords(iterations=10)` runs 10 enqueue rounds per keyword, each
polling ~2–3 times, and the crawl calls it once per expanded node — **~35 private
requests and ~90 seconds per keyword**. At the CLI's defaults
(`max_nodes=150, max_depth=3`) a deep crawl runs to hundreds of requests. Fine
for a human to type deliberately; terrible for an agent reaching for it while
exploring.

**Chosen: refuse, never clamp.** An over-cap argument returns a `_fail` naming
the ceiling. The alternative — silently clamping 5,000 to 200 — is the worse
failure: the agent believes it searched the whole neighbourhood when it saw 4% of
it, and nothing in the response says otherwise. A refusal is noisy and correct.

**Inside the ceiling the tool decides for itself**, which is what the operator
asked for ("let the mcp decide"): it stops when the frontier is exhausted, when
the budget is spent, or — adaptively — once it has already found enough winnable
pockets to answer the question. Every result carries `spent`, `expansions_remaining`
and `stopped_because`, so going deeper is an explicit second call rather than an
automatic escalation.

**Implemented as a counting proxy, not a forked crawl.** `_Budgeted` wraps the
private client and raises once the expansion ceiling is hit; nodes found before
that survive via the crawl's own `on_node` callback. This keeps
`keyword_crawl.crawl`'s real logic — the best-first frontier, the cycle dedupe,
the top-k pruning — exactly as the CLI runs it. All that changes is who is
allowed to keep going. `iterations` drops 10 → 3 on the agent path: each
iteration asks Etsy's LLM again for *different* edges, so this trades edge
diversity for a ~3.5× cost cut.

### The live run corrected the tool's own number

First live crawl (`felt garland`, 40 terms) returned in **under a second** having
spent **zero** network requests — `get_similar_keywords` is cached for 30 days
and that neighbourhood had been crawled before. But the payload reported
`estimated_private_requests: 10`.

That is precisely the plausible-wrong-number this project exists to prevent: a
derived figure presented as a measurement. Renamed to
**`private_requests_upper_bound`**, with a basis stating that a cached expansion
spends 0 and the true cost lies between 0 and the bound (Rule 3 — bounds are
labelled as bounds). The expansion count itself remains exactly measured.

**The run's actual finding is also worth recording**: 40 terms, **0 winnable, 0
contested, 39 walls**. The payload says plainly that this is a *result* — "the
neighbourhood is a wall all the way down" — not a failed run, because an agent
seeing `pockets: []` would otherwise report a broken tool.

**Verified:** `mcp_server/test_crawl_budget.py`, **19 offline assertions**. The
load-bearing one drives the real `crawl()` with a deliberately runaway client
that returns fresh children for ever: without the proxy that test would hang or
run away rather than fail, which is exactly the production failure being
prevented. Others assert the caps refuse rather than clamp, that the refusal
explains *why* the ceiling exists, that the cheaper iteration count is actually
passed through, and that the request figure is named as a bound.

**The budget test earned its keep the same day.** Adding this tool pushed the
published surface to **4,076 tokens** and the offline gate went red on
`mcp_server.test_server` — the ceiling introduced one commit earlier (D-56)
catching a real regression rather than sitting decorative.

The fix was to trim, not to raise the ceiling again: three descriptions that
predated the house rule were carrying more prose than their warnings needed —
`deep_dive_keyword` **1,091 → 452**, `calendar` **717 → 450**, `cockpit`
**610 → 383**. **1,163 chars reclaimed, no warning lost**; `deep_dive_keyword`
still says that leaving `cogs` at 0 produces false *winners*, `calendar` still
leads with `is_wall` and the christmas-ornament example, `cockpit` still says
conflicts are two opposite readings rather than a middling score.

Final: **15,142 chars ≈ 3,785 tokens, 21 tools reaching 46 capabilities.**

A note on the house rule: the plan said "descriptions ≤ 400 chars". Seven now sit
at 449–529 because what they carry is worth the bytes, and the test does not
police them individually. The **total** is what is enforced, and that is the
honest arrangement — a per-tool rule nobody meets is worse than no rule, and the
budget is the constraint that actually matters to an agent's context.

## D-58 — `analyze`: the judgements, free and offline

**Date:** 2026-09-01.

**Context.** The expensive tools fetch; nothing let an agent *decide* without
spending. `analyze` is seven operations that read the local database or are pure
arithmetic — **no network, no session, no preflight** — so reasoning is never
rationed. That separation is the point: thinking should not compete with a
request budget.

Every operation is one of the system's refuse-rather-than-guess functions:
`winnability` returns the **ratio** not a score (D-31), `intent` compares CVR
**between** terms and never as units (D-43), `saturation` withholds brackets
whose interval straddles a threshold (D-36), `discriminate` refuses to rank when
the dimensions cannot separate the pool (N-01), and every one of them can answer
`unmeasured` — which is a real answer here, not a failure (N-02).

**Live, it immediately produced a compound finding neither half gives alone:**
`mom necklace` is a **wall** at 0.035 demand-per-listing *and* converts at
**0.448×** the pooled median CVR. Winnable-looking traffic, weak intent, and
unrankable supply — three independent readings agreeing.

### Two bugs the smoke test caught that reading signatures would not have

**1. `measured_cvrs()` returns a dict, not a list.** Iterating it bare yields the
keyword *strings*, which reach `_median` and crash on `str / int`. Mine, not the
project's — and invisible until the operation was actually called, because the
signature says nothing about it. Fixed with `.values()`.

**2. `can_discriminate()` returns a NamedTuple**, which JSON-serialises to a bare
array: `[true, "single dimension…", ["supply"], null]`. Every field name is lost
on the wire, so a consumer would have to know the positional order to read its own
answer. Converted to an explicit dict. This is a general hazard for this surface —
**any dataclass or NamedTuple crossing the MCP boundary loses its field names
silently**, and the payload still looks plausible.

### The budget is now genuinely binding

Adding `analyze` pushed the surface to 4,117 tokens; trimming `analyze`'s own
operation doc plus `verdict_history` (529 → ~380) and `discover` (520 → ~380)
brought it to **15,965 chars ≈ 3,991 tokens** — under 4,000 by **nine tokens**,
with 22 tools reaching 53 capabilities.

That margin is the finding. The ceiling has now forced out **~2,600 chars of
genuine waste across three commits** (auto-generated titles, then three bloated
descriptions, then two more) and has stopped finding fat. The next tool will
exceed it, and the remaining descriptions carry warnings worth their bytes.

**This was put to the operator rather than quietly relaxed**, with the efficiency
argument on the record: 53 capabilities at 3,991 tokens is ~75 tokens each,
against ~180 per tool under the old one-tool-per-capability design — a 2.4× gain.

**Decision: raise the ceiling to a flat 6,000** (operator's call). It leaves room
for the remaining tool groups without further trimming and is still under a
quarter of what ~150 flat tools would cost.

**A second assertion was added so the raise does not remove the discipline.** A
flat total penalises *reach* rather than *bloat* — a tool that adds 12 useful
operations looks identical to one that adds 12 paragraphs of prose. So the suite
now checks both:

| Limit | Now |
|---|---|
| total ≤ 6,000 tokens | **3,991** |
| ≤ 120 tokens per capability | **75** |

The per-capability figure is the one that actually measures whether grouping is
still doing its job. If a future tool pushes the total up while efficiency holds,
that is reach being bought honestly; if efficiency degrades, something is bloating
regardless of what the total says.

**The 4,000 figure was not wrong** — while binding it forced out ~2,600 chars of
real waste across three commits (auto-generated titles, then five oversized
descriptions). It was raised at the point it stopped finding fat and started
cutting warnings, which is the right moment to move a budget and the only honest
reason to.

## D-59 — the two Etsy tiers, and `daily_stats` finally has a consumer

**Date:** 2026-09-01.

**Two tools, not one, on purpose.** `etsy_private` and `etsy_public` could have
been a single tool with a `tier` parameter. They are separate so the tier is
visible **at the call site** rather than buried in an argument: D-29 is the rule
that costs the most to break, and `etsy_private(...)` in a transcript reads as
spending the irreplaceable account in a way `etsy(tier="private", ...)` does not.

**`daily_stats` now has its first consumer.** D-51 found it — a day-by-day volume
series with a 7-day rolling average riding free on *every* `results_data` call,
parsed by nothing in the project's life. It is a materially different instrument
from `chart_series`: **daily over ~3 weeks** rather than monthly over a year, so
it answers "is this moving NOW" where the other answers "when does it peak
annually." For a calendar-first product that is the sharper question.

Verified live: `mom necklace` → 30 daily points, peak **Aug 18 at 540**, range
133–540, each with its rolling average. Free, on a call the system already makes.

`similar_keywords` gets the same `iterations=3` cap as the crawl (D-57), for the
same reason: the CLI's 10 is for a human who chose to wait.

### The public session was burned mid-verification, and the system behaved correctly

While smoke-testing `etsy_public`, the buyer profile took a **403** from Etsy.
The observable sequence:

```
Request blocked or unauthorized: 403 on profile profile_p5ewxsodn
🚫 [Vault] Marked profile_p5ewxsodn on etsy as INVALID. Removed from rotation.
⏳ [Vault] No usable 'etsy' profile. Waiting up to 120s...
   -> VaultEmpty
```

**Every layer did its job.** `session_manager.classify()` read the 403 as
`blocked` rather than as a rate limit or a bug in our own request, and evicted —
which is exactly D-35's design, and exactly what must NOT happen for a 429.
Preflight had passed legitimately: the pool was healthy when the tool was called
and the block happened mid-request, which no gate can pre-empt. The seller
account was untouched (2 usable throughout) — the tier separation held under a
real failure, not just in principle.

**Verification, in the order it actually happened.** `etsy_private` verified
first: `daily_stats` → 30 daily points, peak Aug 18 at 540; `results_data` →
11,141 volume / 381,511 supply / CVR 0.000303 / 17 competitor cards.
`etsy_public` could NOT be verified at that moment — its session had just been
evicted — and was written up as unverified rather than assumed, on the grounds
that "the code path looks like the others" is an argument and not a measurement.

The extension re-synced minutes later and it was then verified properly:
`search('felt garland')` → 29,334 total, 12 cards (all organic), **46 ranked
listing ids**, 20 pages; `listing` → `physical`, 13 tags, breadcrumb
`Home & Living > Home Decor > Wall Decor`.

Two things that run confirms beyond the tool working. The **46 ranked ids
against 12 rendered cards** is the D-PS-2 fix still holding — that list was
empty for the project's entire life until the 2026-08-20 regex fix, and it is
what makes rank tracking possible at all. And **20 pages** against a system that
only ever reads page one is the pagination gap quantified: 19 pages of
competitors this surface cannot see, which the tool now says out loud rather
than leaving as silence.

## D-60 — time becomes readable, and the learning loop stops being invisible

**Date:** 2026-09-01.

**The append-only design finally has a consumer.** Every `*_observations` table
carries `collected_at` in its primary key and is never overwritten (Rule 5) —
a discipline the system has paid for since the beginning and, until now, nobody
could spend: **no tool could read a series.** An agent could see that supply is
381,511 and never that it grew 40% while volume held, which is the difference
between a number and a finding.

Live on first call: `mom necklace` has **9 demand readings** spanning 2026-08-19
to 2026-08-27, and `shopflowerlane` has **7 shop readings yielding 23.9
sales/day** — the only *measured* sales figure anywhere in this system, and it
was unreachable.

**The learning loop lives in a different database, which is why it had no
consumer at all.** Launches, ranks and outcomes are in `GraphDB`
(`etsy/data/graph/graph.db`); keyword and shop readings are in `MarketDatabase`.
The existing `learn_status` tool reads only the latter — so
`prediction_vs_outcome()`, *the one query the LEARN loop exists to answer*, was
reachable by nothing.

**`calibration` refuses, and names why.** On the current data it returns
`can_calibrate: false` with two blockers: *0 launches recorded; calibration needs
~10*, and *no launches, so the control ratio is unmeasured*. That is the honest
output — the alternative is a confident model of noise.

⚠️ **`control_ratio` is a gate, not a statistic.** Below ~0.1 (B-04) calibration
measures the model against its own preferences: if every launch was something the
model liked, "the model was right" is circular. `None` means nothing launched,
which is a different claim from "no controls were run" — and the tool
distinguishes them.

**Three ambiguities the payloads resolve rather than leave to the reader:**

* `latest_rank: null` is meaningless alone — `observations: 0` means never
  checked, `> 0` means checked and not found. An untracked listing is not a
  failed one.
* A shop counter that did not move means "sold less than the counter can show"
  (it is quantised at 100 for large shops), never zero.
* **One reading is not a trend.** A single-row series returns "direction is
  unknown rather than flat", because a delta needs two readings a day apart and
  **cannot be backfilled** — a day the scheduler missed is gone permanently.

`history(operation="trend")` matches across the Etsy/Pinterest wording gap and
**refuses a near-match**: importing `cat collar`'s momentum for `dog collar`
would be a wrong number wearing a right label. Verified — `christmas ornament`
returned `matched_trend: null` rather than reaching for something close.

**And the tool states the thing the operator most needs to hear.** With zero
launches, `launches` returns: *"This is the binding constraint on the whole
system: every verdict it produces is currently unfalsifiable, and no amount of
further measurement changes that."* More tools do not fix it; a listing does.

**25 tools, 70 capabilities, 4,743 tokens** — efficiency improved again to
**68 tokens/capability** (from 72, from 75). Reach going up while cost per
capability goes down is grouping doing exactly what it was chosen for.

---

## D-61 — the strategy layer moves into skills, because the UI that carried it is gone

**2026-09-01.** Five new skills: `etsy-private-tier`, `etsy-public-tier`,
`pinterest-tier`, `finding-winners`, `calendar-and-timing`. `ui-builder` deleted.

**Why now.** D-52 deleted the UI and the read server and made MCP the interface.
That was the right call, but it quietly removed the place where a lot of
discipline lived. A generated page could *show* a Wilson interval, grey out an
untrusted filter, or label a bound as a bound — the layout itself enforced
honesty. An MCP tool returns a dict, and nothing stops a model reading
`query_cvr` as orders per month.

The tool payloads already carry `basis` on every number. That is necessary and
not sufficient: `basis` says *what kind of number this is*, never *what you are
allowed to conclude from it*. The seven existing skills all ask whether the
**work** is right — is the number true, is it shown first, is it worth
gathering. None of them answered "what does this number mean once I have it",
because until now a screen answered it.

**Why skills and not longer docstrings.** The MCP surface is 25 tools / 70
capabilities / 4,743 tokens, and the phase gate is a ceiling on that number.
Caveats in schemas are paid for on **every** request whether or not they are
relevant; a skill is paid for only when its trigger fires. The house rule stands:
docstring ≤ 1 line, operation table in `Field(description=…)`, **long caveats go
in the matching skill.** The skills are where the expensive-to-rediscover
material goes precisely because they are not resident.

**Why these five.** Three are the tiers, because the first question about any
number here is which tier produced it and what that tier is allowed to say —
private is irreplaceable and relative-only, public is unlimited and 9 of its 12
filters lie, Pinterest is 0-100 normalised and arrives backwards. Two are the
verbs: `finding-winners` fixes the gate ORDER (wall → intent → margin → timing →
discrimination, worst-of, each able only to reject), and `calendar-and-timing`
holds the distinction the whole product is named for — **late is not missed**.

Each carries the measured evidence, not the rule alone. `home decor` at 0.14
demand-per-listing versus `backpack name tag` at 2.79. `custom family name
necklace` ranked first while converting at 0.15x its neighbours. The $5.21
versus $12.69 COGS ceiling on the same term. `mom necklace` peaking in December.
A rule with its counter-example attached survives a rewrite; a rule alone gets
optimised away by the next reader who finds it inconvenient.

**What this does not do.** It does not make any recommendation correct. With
**0 launches** LEARN still cannot calibrate, so every verdict remains
unfalsifiable — the skills say so out loud rather than letting confident
formatting imply otherwise.

---

## D-62 — four defects, and the one that only a probe could have caught

**2026-09-01.** The audit (`docs/SEO_LAYER_AUDIT.md`) named four. All four are
fixed. Three were code; the fourth was a *meaning*, and it is the one worth
recording.

**What the code fixes were.** `chart-series-data` answers only the first three
terms, silently — the daily sweep passed 11 and stored 3 for the life of the job.
`analyze(discriminate)` judged rankability on **one** dimension of six, because
the discovery layer names its columns for a reader and `scoring` names them for
the weighting and nothing translated. Four analytics modules had been raising
`AttributeError` on line one since they were written, swallowed by a bare
`except`. And a fully ranked SERP was reduced to `len(ids)` every day, which is
the only one of the four that was destroying something unrecoverable.

Each is the same shape: **nothing raised.** A truncated response is well-formed.
A missing scoring dimension is a legitimate state that `score_pool` handles
correctly. A swallowed exception prints one line. An integer is a valid column
value. This is what "a plausible wrong number, not a crash" means in practice —
not one dramatic bug, but four quiet ones that each looked like normal operation.

**The one that a review would not have caught.** The plan said to parse
`Listed on <date>` out of the listing page and called it *"honeymoon detection,
done"* — the date is right there, on HTML already cached for 30 days. Live probe,
listing `1864690497`: **7,700 reviews**, and the page says `Listed on Sep 1,
2026`. That day.

Etsy auto-renews listings and the displayed date moves with the renewal. The
regex was correct. The claim built on it would have called a four-year
best-seller brand new, in a field explicitly named for deciding whether a listing
is new.

So `listing_age()` reports `age_days_lower_bound`, never an age, and `honeymoon`
is **three-valued** — `None` when a young-looking date meets a review count that
contradicts it. A boolean would have to pick a side for the renewed case, and
either choice asserts something the data does not support.

The general lesson is not "probe more". It is that **a field being present and
parseable says nothing about what it means**, and the audit, the plan and the
first implementation all agreed with each other while being wrong. Only the wire
disagreed.

The same probe answered two other things by looking: the cart count is **not** on
the listing page at all (favourites are, and are listing-level), and it is not
reachable behind an add-to-cart either, because `SessionManager` claims a freshly
shuffled profile per request — an add and a read are two different buyer
identities. Both are recorded in the code so they are not re-litigated.

**What accrues from here.** `rank_observations` now gets one row per listing per
term per day — verified live at 43 rows for `felt garland`, with one shop holding
ranks 1, 6 and 7. It reuses the existing table because `record_rank` never had a
`launches` foreign key, which turns out to matter: the competitor series is the
only outcome dataset available that does **not** wait for the operator to launch,
and it is unbiased precisely because our own model did not select it (B-04).

With **0 launches** that remains the binding constraint. None of this fixes it.

---

## D-63 — the batch door, the drill, and the free source we already half-knew

**2026-09-01.** Three additions that answer one complaint: *"always a limited scan
for only one keyword… he cannot process all that and give me a list and
comparison."*

**The complaint was accurate and the cause was not where it looked.** Not the
wire, not the analytics. Every decision tool on the surface was typed singular —
one term, one moment, one shop — while a complete, tested pool ranker
(`score_pool` / `percentile_ranks` / `shortlist` / `explain`) sat behind them with
**zero MCP callers**. The agent could reach `can_discriminate`, the guard that
REFUSES a ranking, without being able to reach the ranking it guards. The surface
could say *"these cannot be compared"* and never *"here is the comparison"*.

So `compare` writes almost no new analytics. It is an entry point.

**`drill` is the same shape of finding.** `expand_seed` already called
`get_similar_keywords`, which returns 120–173 children **each already carrying its
own volume and supply** — and then returned `all_terms`, a flat list of bare
strings. Every measurement paid for was discarded at the boundary. Drill returns
them as ranked rows in the same shape `compare` emits, so a drill's output is a
valid input to another drill and going deeper never means learning a second
format.

**And the autocomplete was listed as a capability that did not exist.** Two docs
claimed "Search Autosuggest"; `core/settings.py:27` carried a dead
`TYPING_SUGGEST_ENDPOINT` constant nothing imported. What existed was
`similar_keywords` — LLM-*generated* adjacency, on the seller session, ~10
requests. The real query stream is a buyer-session call. The operator supplied the
better of the two endpoints from their own browser; probing settled the rest.

### What probing changed, in each case

Every one of these came from running the thing, not from reading it:

* **The unit bug.** `compare`'s cheap mode divided a YEAR of searches by a
  point-in-time listing count. `custom guitar strap` read **3.285 "winnable"**
  against a true **0.156 "wall"** — and every verdict in an 8-term batch flipped.
  The fix was free: the curve's last complete month is already in the response.
* **The zero CVR.** `back70 sneakers` returns `query_cvr` exactly **0** against
  ~10,500 monthly searches. `confirm_intent` only guarded `is None`, so `0/median
  = 0.0` fell under the weak threshold and the gate *rejected* the term on a
  number nobody measured.
* **The silent slice.** The first live drill kept **59 of 173** children and
  reported 59 as the neighbourhood.
* **The rotation that isn't.** Ten consecutive suggestion calls returned identical
  lists, across ten different buyer profiles.

### The caveat that qualifies an earlier conclusion

`supply` is the count Etsy **returns** for a query, which is a broad match. Private
and public agree closely up to three words, so it is not a parsing artifact — Etsy
really returns ~39,000 results for a four-word phrase, and 6 of 7 page-one
listings do contain all four words. But the listings truly competing are fewer,
and Etsy publishes **no exact-match count at any price**.

So `demand_per_listing` is systematically **conservative** on long-tail terms: it
divides a narrow, phrase-specific volume by a broad result count, and pushes
specific terms toward `wall` by construction.

This is **not corrected**, because any correction would be a guess dressed as a
measurement. It is reported — `supply_basis`, `phrase_words`, and a note on drill
saying to compare a child against its **siblings**.

It matters because earlier the same day this repo produced "1,713 of 1,716
discovered terms are walls", which reads as *the market is saturated*. They are
all long-tail expansions, so a large part of that is the metric, not the market.
A conclusion that survives one day and not the next is exactly what a decision
log is for.

---

## D-64 — `compare` was written in the wrong layer, and the UI question exposed it

**2026-09-01.** Moved `compare` out of `mcp_server/tools_decide.py` into
`etsy/analytics/compare.py`. The MCP tool is now a wrapper that adds the preflight
and the `_ok`/`_fail` envelope, and nothing else.

**How it was found.** The operator asked whether the plan had changed — *"we are
working on MCP and we are going to work on the UI web app later, I do not know
what we are doing now."* Checking whether today's work would actually survive
into a web app answered the question and found the defect at the same time.

~290 lines of gate sequencing — the two fetchers, `_monthly_volume`, the
winnability/intent/discrimination ordering, the worse-of rule — sat inside a
protocol adapter whose only import was `mcp_server._plumbing`. A second surface
had exactly two options, both bad: import from `mcp_server` (a protocol adapter is
not a library) or reimplement the gates, leaving the system with **two gate orders
that drift apart**. D-41 already names one read layer for precisely this reason,
and this walked straight past it.

**Why it happened.** Every tool in `mcp_server/` before this was thin — a call into
`etsy/analytics/` plus framing — so the file did not look like a place where logic
accumulates. `compare` was the first tool that *composed* several analytics
functions rather than wrapping one, and the composition landed where the wrapper
lived because that was the file already open.

**What the split buys, concretely.** `compare()` now takes injectable `fetch_cheap`
/ `fetch_full` / `preflight`, so any surface can drive the judgement layer with no
session and no MCP at all — which is also how the 52 assertions now run. The web
app, a CLI, and the MCP tool call one function and get one answer.

**Pinned, not just fixed.** `test_compare` now asserts the analytics module imports
no MCP plumbing, that the gate sequencing is absent from the tool file, and that
`compare()` runs offline through injected fetchers. The pull to write the next
composite tool the same way is strong, and the cost of not resisting it only
appears once the second surface exists — which is exactly too late.

⚠️ The first version of that assertion was itself wrong: it searched for the
substring `mcp_server` and fired on the docstring paragraph *explaining why the
module is not in mcp_server*. It now matches import syntax only — the same false
positive `test_preflight` hit on a prose mention of `vault_mirror.py`, which is
twice now that a naive substring check has flagged the documentation of a rule as
a violation of it.
