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
| **Server auth** | `etsy/server/app.py` has none — fine on `127.0.0.1`, unsafe on a LAN or beyond | See §2 below; this is the first thing any wider deployment needs |

None of these block daily use of the calendar/cockpit/discover screens today.
They're the honest list of what's thin, not blockers to using what exists.

---

## 2. Design notes: if this became a listed MCP server or a SaaS

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
   or one noisy user burns another tenant's session budget.
4. **A tool manifest**: the 17 tools already carry docstrings good enough to
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
