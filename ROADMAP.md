# Roadmap — what's missing, and what "bigger" would require

Two different lists on purpose. The first is **things this single-operator
system still needs**, ordinary backlog. The second is **design notes for a
future you don't have to build yet** — what would actually change if this
became a listed MCP server or a multi-tenant SaaS. Read the second list as
"here's what to expect," not "here's what to do next."

---

## 1. Still missing (single-operator scope)

| Item | Why it's not done | What unblocks it |
|---|---|---|
| **First launch** | LEARN (`etsy/analytics/learn.py`) refuses to calibrate below 10 launches — currently 0 | Operator lists something. Nothing in the codebase can substitute for this; it's the one input that must come from outside the system. |
| **Mid-tier competitor shops tracked** | Only 2 tracked shops exist, both stars (survivorship bias, B-01 in `bias_audit.md`) | Operator adds shop URLs via `settings_store` / the tracking config — a data-entry task, not a code task |
| **X-ray screen** | Last screen on the original board, never built: one competitor listing dissected field-by-field (tags, price history, review timeline) rather than the market-wide view every other screen takes | Straightforward extension of `etsy/ui/cockpit_page.py`'s pattern, scoped to a single `listing_id` instead of a `term` |
| **Colour dimension recovery** | `attr_1` (colour) is in `filter_trust.json` as `NOT_A_SUBSET` — Etsy's own colour buckets don't sum to 100%. Recovering it needs image analysis of listing photos, deliberately not built (out of scope for a text/API pipeline) | Would need a vision step — new capability, not a bug fix. Worth reconsidering only if colour becomes decision-relevant for a real candidate. |
| **Offsite Ads $100/order fee cap** | Etsy charges Offsite Ads fees only up to $100 per order; not modeled in `etsy/analytics/profit.py`, which applies the flat percentage unconditionally | Low priority — only bites on orders near/above $100, uncommon for personalized/digital goods at this shop's price points. Flagged, not fixed. |
| **History depth** | Trend/listing/shop observations only started accumulating 2026-08-19 (calendar fix) / earlier for keywords. Trend detection, momentum, and "did the verdict flip and why" all get better with more days behind them | Time only — cannot be backfilled. The scheduler (`EtsyScrapperDaily`, 07:00) is the whole mechanism. |
| **Server auth** | `etsy/server/app.py` has none — fine on `127.0.0.1`, unsafe on a LAN or beyond | See §3 below; this is the first thing any wider deployment needs |
| ~~**Full physical separation from `pinterest-apify`**~~ | ✅ **Done 2026-08-25.** The operator's plan throughout: each project owns its full stack — own containers, own Redis, own database, no sharing. The specific mechanics differed from this doc's original proposal (which was to move THIS project onto a new Redis/Go server) — instead `pinterest-apify` moved itself, onto its own `pinterest-redis` container (port 6380) — but the target state is exactly what was planned. This project's access layer needed zero changes either way — it never depended on the other side. Their 7 `ads_*` jars, confirmed abandoned (heartbeats stopped advancing) after their cutover, were purged from db 0. See `docs/VAULT_SEPARATION.md`. | ✅ **The db 0/db 1 mirror is also retired now (D-49, 2026-08-26).** Once nothing shared db 0 any more, the mirror had nothing left to defend against — `core/vault_mirror.py` deleted, every client reads db 0 directly. |

None of these block daily use of the calendar/cockpit/discover screens today.
They're the honest list of what's thin, not blockers to using what exists.

---

## 2. Designed and probed, never wired — the highest-leverage next builds

Different from §1: these aren't gaps, they're **capabilities the project already
verified exist on the wire** (via `docs/architecture/08_capability_map.md` and
`docs/market_map/`), sometimes with the exact join spelled out, that simply
never got built. Ranked by the project's own stated leverage, highest first —
not chronological, not by ease.

| # | Capability | Source | Why it matters |
|---|---|---|---|
| ~~0~~ | ~~**The intent gate** — do the searchers actually buy?~~ | ✅ **done 2026-08-20 (D-43)** | Was the top item and is now built. `winnability` divides searches by listings, both supply-side, so a term passed on traffic alone; 5 of the top 6 candidates converted below half the pool median, including the one ranked first. Also uncovered that `volume × query_cvr` is **not** an order count — see the warning in `CLAUDE.md`. |
| ~~1~~ | ~~**JOIN 2 — winnable AND rising**~~ | ✅ **done 2026-08-20 (D-44)** | Built as a third AXIS, not a fourth gate — Pinterest tracks under half the pool (3 of 7 probed), so gating on it would reject terms for absence. One `/metrics/` call per run covers the whole surviving pool. ⚠️ The stored-topic path is a dead end — see below. |
| 2 | **JOIN 3 — intent gate** (`OUTBOUND_CLICK` vs `SAVE` on Pinterest) | `combinations.md` §JOIN 3; `08_capability_map.md` §4.2 item 1 | Separates buyers from daydreamers. A niche high in `SAVE`, low in `OUTBOUND_CLICK`, looks like Pinterest momentum but will not convert on Etsy — the one filter that catches this before a Blueprint gets built on it. |
| 3 | **JOIN 4 — demographics-shaped tags** (Pinterest age/gender → Blueprint copy) | `combinations.md` §JOIN 4; `08_capability_map.md` §4.1 `demographics` endpoint | Not "necklace" but the words a specific 25-34-female audience actually searches. Marked `⚠️ demographics endpoint unproven` — worth a live probe before building on it, same discipline as everything else here. |
| ~~4~~ | ~~**A free seasonality curve**~~ | ✅ **done 2026-08-20 (D-45)** | The note was right that a curve was being declined and wrong about where it was. `include_trendline` is INERT — True and False return identical structures. The curve was in `series` all along, fetched on every call and discarded by every caller. Now parsed, profiled and stored per sweep. |
| 5 | **Shopping-family endpoints (`ApiResource`)** — 383-category DAG, category growth ranking, category demand curve **with a forecast**, category demographics, actual top-products-in-category | `08_capability_map.md` §4.2 — 7 of 8 endpoints `❌`, "almost entirely unused" | Replaces LLM keyword clustering with Pinterest's own taxonomy (item 14 in `09_build_plan.md` Phase 3) and gives a demand *forecast*, which nothing else in the system currently produces. |
| 6 | **Community-relative momentum** | `09_build_plan.md` Phase 3, item 15 | "Rising faster than its own community" (real trend) vs "rising with it" (just the season) — sharper than the raw velocity number currently used, and cheap: same Pinterest data, different denominator. |
| 7 | **`editorial/content`** | `08_capability_map.md` §4.2 | 6 trend stories with keywords, across US+GB+IE+CA, in **one free call** — currently never called. |
| 8 | **Where-to-list (D-11)** | `docs/DECISION_LOG.md` D-11 / D-21 | Etsy vs Shopify/Pinterest, decided by searched-for vs discovered demand with CAC as a range (not fee percentage, which favors Shopify on a naive read). Deliberately deferred by scope (D-21: Etsy-only for now) — a real feature, not a bug, just parked. Revisit only if a second channel is seriously on the table. |
| 9 | **Pagination on Etsy search** | `09_build_plan.md` stage 2 gap | The private/public search calls read one page; the free 20-card sample per call is real but shallow for high-supply terms. |
| 10 | **Pinterest wide crawl** | `09_build_plan.md` stage 1 gap | Discover's front door (`trending-search-terms-v2`) covers 7 populated taxonomy ids; the broader Pinterest search/spotlight/shopping seed crawl described in the funnel (`combinations.md` stage 1) is still Etsy-seed-only in practice. |

**If picking one to build next: JOIN 3** (row 2). JOIN 2 and the intent gate
gave the pool a *does it convert* axis and an *is it growing* axis; JOIN 3 adds
Pinterest's own buyer-vs-daydreamer split.

⚠️ **Check this first.** `event` (`OUTBOUND_CLICK` vs `SAVE`) appears only on
the SHOPPING-family endpoints — `top_categories`, `category_metrics`,
`top_products` — and **not** on the search `/metrics/` endpoint JOIN 2 uses.
So click-vs-save is available per *Pinterest category*, not per term, and
using it means mapping Etsy terms onto Pinterest's 383-category DAG. That is
another vocabulary-matching problem of exactly the shape that has already
failed twice here (the calendar, and the stored-topic join below). Probe the
mapping before building on it.

⚠️ **What JOIN 2 had to avoid, probed 2026-08-20.** The obvious cheap path — join the momentum already stored in `trend_observations` onto the
discovered pool — **does not work, and the data says so unambiguously**:

| Check | Result |
|---|---|
| 84 stored Pinterest featured topics vs 1,333 discovered Etsy terms | |
| Exact content-word matches (what D-17 requires) | **0** |
| Containment matches, either direction (looser) | **0** |
| Topics sharing *any* content word with any candidate | 64 of 84 |

Pinterest's featured topics are editorial phrases — "Skirt and Leggings
Combinations", "Apple-Themed Preschool Activities" — and Etsy candidates are
product keywords. They describe the same world in different vocabularies. This
is the identical failure that silently broke the calendar (86 topics vs 13
moments, zero overlap, every `takeoff_timestamp` NULL), so it is a known shape,
not a surprise.

**The viable path is live, not stored.** Pinterest's `metrics` and
`related_terms` endpoints accept an *arbitrary* term and return momentum for
that term, so the join is `for each winnable Etsy candidate → ask Pinterest
about THAT term`, not `match against topics Pinterest chose to feature`. That
costs one Pinterest call per candidate (cheap — no seller account, no quota),
and it is the design that should be built. Do not spend time on the stored-topic
path; it has been measured and it is empty.

**One idea from project history, noted but not adopted.** An early handoff doc
(`gemini/claude_handoff.md`, since reconciled into `docs/architecture/10_session_layer.md`)
raised matching the Chrome browser's IP to the Python scraper's IP (residential
proxy, or one shared VPS) to reduce DataDome ban risk — explicitly parked as an
infrastructure-layer concern, not a Python code change. Still infrastructure,
not code, and still adjacent to the access layer this project doesn't modify
without explicit permission — flagged here so it isn't rediscovered from
scratch, not recommended as a next build.

---

## 3. Design notes: if this became a listed MCP server or a SaaS

**Not a build plan.** No code here. This is what to check against before
starting that work, written down now so the shape doesn't have to be
re-derived later.

### What single-tenant assumptions are baked in today

| Assumption | Where it lives | What breaks it |
|---|---|---|
| One SQLite file, `market_intelligence.db` | `core/database.py`, read by every engine and by `etsy/ui/app_data.py` | A second operator's data would need its own file/schema, or a real multi-tenant DB (Postgres + a `tenant_id` on every table) |
| One Redis vault, one operator's cookies | `core/cookie_vault.py`, `core/session_manager.py` — access layer, out of scope to modify per project rules | Multi-tenant needs one vault **per operator's own Etsy login** — sessions cannot be shared across tenants; this is the hardest part, not a schema change |
| One `config/settings.json`, one fee schedule, one hourly rate | `core/settings_store.py` | Needs to become per-tenant config, keyed the same way the DB would be |
| No auth anywhere — not the FastAPI server, not the MCP server | `etsy/server/app.py`, `mcp_server/server.py` | Both would need real auth (API keys or OAuth) before touching a network beyond localhost/LAN |
| MCP server is invoked as a local stdio subprocess by the client | `mcp_server/server.py`, `docs/MCP.md` | A **listed** MCP server (discoverable, remote) speaks a different transport — HTTP/SSE, not stdio-per-user-machine. This is a real rewrite of the transport layer, not a config change; the 17 tool functions themselves would not need to change, only how a client reaches them. |

### The one-way door: the access layer

`core/session_manager.py`, `core/cookie_vault.py`, `cookie_server_go/`, and
`chrome_extension/` are off-limits to modify without explicit fresh
permission (standing project rule — see `CLAUDE.md`). Any SaaS design has to
treat this layer as **the reason multi-tenancy is hard, not easy**: this
system's edge over a generic scraper is that it authenticates as the
operator's *own* seller account for private-tier data. That doesn't
generalize to "log in as anyone" without redesigning session handling
per-tenant, which is exactly the surface this project has committed not to
touch casually.

**Practical reading**: a SaaS version of the *public*-tier features (supply,
saturation, sourcing — no seller login required) is a much smaller lift than
a SaaS version of the *private*-tier features (search volume, CVR — requires
each tenant's own authenticated Etsy session). If this path is ever taken
seriously, split the product along that line first.

### What a listed MCP server would need, concretely

1. **Transport**: stdio → HTTP/SSE (or whatever the listing surface requires
   at the time). The tool functions in `mcp_server/server.py` are the
   business logic already; a listing mainly changes how a client connects,
   not what the tools do.
2. **Per-tenant credentials**: today `cwd` implicitly scopes one operator's
   `.env`/`config`/DB. A listed server needs an explicit tenant identity per
   connection (API key, OAuth token) that maps to that tenant's own DB/vault.
3. **Rate limiting and cost control on live tools**: `analyze_keyword`,
   `sourcing_profile`, `cheap_competitors`, `pod_quote` all spend real
   requests against Etsy/Printify. A public listing needs a quota per tenant,
   or one noisy user burns another tenant's session budget. `deep_dive_keyword`
   (D-50) is the sharpest version of this problem — dozens of requests and
   several minutes per call, not one or two.
4. **A tool manifest**: the 21 tools already carry docstrings good enough to
   double as a listing description (`vault_status` — "Can this system make
   live calls right now? Check FIRST" — is already written for an unfamiliar
   reader, not just this operator). Minimal extra work here.
5. **The `basis` discipline becomes the trust story**: for an unfamiliar
   third-party client (not "the operator's own agent," which today's four
   design rules assume), the `measured`/`derived`/`bound`/`provisional`
   tagging is the whole reason a stranger could trust a number from this
   server at all. Nothing here needs to change — it needs to be advertised as
   the product's core guarantee.

### What NOT to do preemptively

- Don't add multi-tenancy scaffolding (tenant_id columns, per-tenant config
  loading) until there's a second real tenant. It's dead weight against a
  single-operator system's actual scale, and the `system-architect` skill's
  scale discipline applies here too: SQLite + one Redis + one Docker Compose
  file is the right size for what this is *today*.
- Don't containerize the MCP server. It's invoked as a local subprocess by
  the agent client (Claude Code, Antigravity) that already runs on the same
  machine — Docker adds a network hop and a config surface for zero benefit
  until (2) above (remote listing) is a real, funded decision.
- Don't add auth to the FastAPI server "just in case." It's bound to
  `127.0.0.1` by default specifically so it needs none; add auth exactly when
  `HOST=0.0.0.0` stops being a rare, deliberate LAN opt-in and starts being
  the normal way it's run.
