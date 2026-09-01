# MCP server, and where DeepSeek belongs

Two related things: how an agent (Claude Code, Antigravity, anything speaking
MCP) talks to this system, and the boundary that keeps an LLM from quietly
becoming a source of numbers.

---

## Part 1 — the MCP server

```bash
.venv/Scripts/python.exe -m mcp_server.server
```

Speaks stdio. **25 read-only tools**, seven of which group 52 operations between them. You do not run this command yourself in
normal use — the MCP client (Claude Code, Claude Desktop, Antigravity) launches
it as a subprocess on demand, over stdio. Run it by hand only to sanity-check it
starts, or when writing/debugging a new tool.

### Wiring it up

**Claude Code / Claude Desktop** — add to your MCP config (`~/.claude.json` or
the Desktop app's `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "etsy-market-intel": {
      "command": "C:\\Users\\0xdevy\\Desktop\\etsy scrapper\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\Users\\0xdevy\\Desktop\\etsy scrapper"
    }
  }
}
```

**Antigravity** — the identical block, in whatever shape its MCP settings
panel takes (JSON editor or add-server form — same three fields: command, args,
cwd).

`cwd` is not decorative: the server resolves `config/settings.json`,
`market_intelligence.db`, and `.env` relative to the repo root. Point it
anywhere else and every tool call fails to find its data, not with a clean
error but with an empty result that looks like "no data yet."

**Verify it's wired correctly**, independent of any client:

```bash
.venv/Scripts/python.exe -c "
import asyncio
from mcp_server.server import mcp
tools = asyncio.run(mcp.list_tools())
print(len(tools), 'tools')
for t in tools: print(' ', t.name)
"
```

25 tools should print. If Claude Code / Antigravity shows a different count
after adding the server, the client is pointed at a stale `cwd` or a different
Python (not the venv) — check the command path first.

**A first session, concretely** — once wired, a natural opening exchange:

> **You:** "Is the vault ready? And what does the calendar say I should list
> this week?"
> **Agent calls:** `vault_status` → `{"ready": true, ...}`, then `calendar` →
> the ranked list of 🔴/🟡/⚪ terms with `list_by` dates.
>
> **You:** "Dig into the top one — is it actually worth it?"
> **Agent calls:** `cockpit("<term>")` → three-source state (Pinterest timing,
> Etsy demand, Etsy competition) kept separate, then the combined verdict.
>
> **You:** "What would it cost me to make on Printify?"
> **Agent calls:** `pod_quote(...)` — **live**, spends a real request, gated on
> `vault_status` first.

### The tools

| Tool | Answers | Live? |
|---|---|---|
| `vault_status` | can this make live calls right now? Call this **first**. | reads Redis |
| `run_health` | did the scheduled jobs actually run — status, last success, staleness | local |
| `calendar` | what should be listed, and by when — the front door | local |
| `discover` | the ranked candidate pool — terms the operator has not typed | local |
| `cockpit` | everything known about ONE candidate, three sources kept apart | local |
| `analyze_keyword` | is there room in this niche — demand, supply, the ratio | **live** |
| `sourcing_profile` | where sellers in this niche ship from, and how fast | **live** |
| `cheap_competitors` | why the cheapest listings are cheap — origin of the price floor | **live** |
| `pinterest` | **15 operations** — the raw audience/timing/momentum surface. See below | **live** |
| `pinterest_research` | **11 operations** — composed research: expansion, audience skew, merchant share, movement | **live** (2 are local-only) |
| `keyword_crawl` | recursive seed expansion → the winnable pockets. **SPENDS THE SELLER ACCOUNT**, hard-capped | **live, seller-tier** |
| `analyze` | **7 operations** — winnability, intent, seasonality, saturation, freshness, filter trust, discriminability | local, free |
| `etsy_private` | **5 operations** — results_data, daily_stats, chart_series, similar_keywords, trending | **live, SELLER tier** |
| `etsy_public` | **4 operations** — search, listing, shop_metrics, shop_listings | **live**, buyer session |
| `history` | **8 operations** — readings over time, launches, outcomes, calibration | local, free |
| `deep_dive_keyword` | full BFS crawl + gap/sourcing arbitrage on a seed — slow, dozens of requests | **live, expensive** |
| `filter_trust_report` | which Etsy SERP filters can be believed, which silently lie | local |
| `profit_verdict` | go/no-go on one unit, with the reason it failed | local |
| `price_and_cost_ladder` | at each price, the most a unit may cost and still clear the floor | local |
| `pod_quote` | what Printify would charge, and whether it can ship fast enough | **live** |
| `learn_status` | did the system's past predictions come true | local |
| `verdict_history` | has this verdict changed, and which inputs moved under it | local |
| `tracked_shops` | which competitor shops are tracked, and the daily delta | local |
| `tracked_market` | the competitor window — tracked shops' listings that match a term | local |
| `settings_summary` | the operator's fee schedule, cost assumptions, margin floors | local |

"Live" tools spend a real HTTP request against Etsy/Printify and gate on
`vault_status` first — call it once at the start of a session and re-use the
`ready` answer rather than checking before every single live call.

`deep_dive_keyword` is a different order of cost from the rest of the "live"
row — dozens of public requests per niche that clears its profit gate,
realistically several minutes per call. It wraps `etsy/engines/master_arbitrage.py`,
the same BFS-crawl-plus-arbitrage engine `docs/DECISION_LOG.md` D-50 wired in
after finding `master_spider.py` (a standalone, unpreflighted concurrency
wrapper around the older, narrower `MasterNicheFinder` alone) was the only
thing offering this shape of analysis and had no MCP equivalent. Treat it as
the deep instrument, not the first look — run `analyze_keyword` or `discover`
first and only reach for this once a seed already looks worth the cost.

### Grouped tools — one tool, many operations

`pinterest` is the first tool of a second kind: instead of one tool per
capability, it takes an `operation` enum. This is how the surface grows without
the context cost growing with it.

**Measured on this SDK:** grouping is ~64% cheaper in published schema, and the
saving is **not** the enum — it is not paying the ~380-char per-tool envelope
once per capability. Concretely, `pinterest`'s 15 operations cost **1,705
chars**; as 15 separate tools at this server's mean they would cost ~10,770.

```
pinterest(operation="related", term="mom necklace")
pinterest(operation="moment_curve", term="halloween")
pinterest(operation="category_top", event="SAVE")
```

`pinterest` — 15 raw operations: `top_trends · metrics · related · prefix ·
demographics · moments · moment_curve · categories · category_top ·
category_metrics · category_demographics · top_products · etsy_competitors ·
featured · editorial`.

`pinterest_research` — 11 composed ones: `expand · long_tail · neighbours ·
sweep · audience · merchant_share · demand_table · classify · taxonomy_search ·
alerts · history`.

**Cost is declared per operation, because it varies by 12×:**

| Operation | Requests |
|---|---|
| `expand` (depth 1) | **2** — and **zero `/metrics/`**; the series ride inside the two expansion responses. Best value on the surface. |
| `long_tail` · `neighbours` · `demand_table` · `merchant_share` | 1 |
| `sweep` (all interests) | **24**, ~15s wall clock at the client's 0.6s pacing |
| `alerts` · `history` | **0** — local archive, and they skip preflight entirely since they need no session |

### `keyword_crawl` — the only tool with a wall around it

Every other tool here is either free or spends a replaceable buyer/Pinterest
session. This one spends **`etsy_private`, the operator's own seller account**,
and it spends it *recursively* — which is why it is the only tool with hard caps.

Measured cost at the CLI's settings: **~35 private requests and ~90 seconds per
keyword expanded**. A deep crawl runs to hundreds. On the agent path,
`iterations` drops 10 → 3 and expansions are capped at 4.

**It refuses rather than clamps.** `max_nodes=5000` returns an error naming the
ceiling, not a quietly truncated crawl — an agent that asked for 5,000 and
silently got 200 would report "I searched the whole neighbourhood" having seen
4% of it.

Read three fields on the way out:

| Field | Means |
|---|---|
| `spent.expansions` | **measured** — keywords whose children were fetched |
| `spent.private_requests_upper_bound` | a **bound**, not a count. A cached expansion spends 0; observed live, a 40-term crawl returned in under a second having spent nothing |
| `stopped_because` | `frontier exhausted` · `request budget spent` · `found N winnable pockets — enough to answer` |

**`pockets: []` is an answer, not a failure.** A crawl that finds 40 terms and 0
pockets has told you the neighbourhood is a wall all the way down. Measured on
`felt garland`: 40 terms, 39 walls, 0 winnable.

### The context budget is a test, not a hope

Every tool's schema is resident in the agent's context for the whole session, so
the surface competes with the actual work. `test_server.py` enforces **two**
limits and fails the build on either:

| Limit | Now |
|---|---|
| total ≤ **6,000 tokens** | 15,965 chars ≈ **3,991** |
| ≤ **120 tokens per capability** | **75** |

The per-capability figure is the one that matters. A flat total penalises reach
rather than bloat; efficiency is the property grouping actually buys — 75 tokens
per capability here against ~180 per tool under one-tool-per-capability.

The ceiling was 4,000 until 2026-09-01. It earned that: while binding it forced
out ~2,600 chars of genuine waste across three commits. It was raised once it
stopped finding fat and started cutting warnings — deliberately, on the record
(D-58), rather than nudged each time it bound.

Two things keep it there. Grouping is the big one. The other:
`_plumbing.strip_schema_titles()` removes Pydantic's auto-generated
`"title": "Category Id"` from every parameter — ~1,100 chars that repeat what the
property name already says. Safe because MCP validates against a separate
`arg_model`; verified that a bad enum value is still rejected identically.
**Descriptions are never stripped** — that is the channel an agent reads to
choose correctly.

**Writing a grouped tool** — four rules, each with a measured reason:

| Rule | Why |
|---|---|
| `Literal`, never `Enum` | `Literal` publishes inline; an `Enum` subclass hoists into `$defs` behind a `$ref` (+28 chars, extra indirection) |
| Required, never `Optional[Literal[…]]` | `Optional` collapses the enum into an `anyOf` and buries it |
| One `Field(description=…)` on `operation` | cheapest documentation channel measured (544 vs 579 dedented-docstring vs 601 raw) |
| Docstring stays ONE line | published **verbatim, including source indentation** — a multi-line docstring ships its leading whitespace on the wire |

**Keep descriptions tight, but the enforced constraint is the TOTAL**, not a
per-tool rule. Adding `keyword_crawl` pushed the surface to 4,076 tokens and the
budget test failed the build; the fix was trimming three oversized descriptions
(`deep_dive_keyword` 1,091 → 452, `calendar` 717 → 450, `cockpit` 610 → 383)
without dropping a single load-bearing warning — 1,163 chars reclaimed. A handful
of descriptions still sit in the 450–530 range because what they carry is worth
the bytes; the test does not police them individually, and pretending otherwise
would be a rule nobody follows.

⚠️ Shared `Literal` aliases live in `mcp_server/_ops.py` and must be **imported
into the tool module by bare name**. MCP resolves annotations with
`inspect.signature(fn, eval_str=True)` against the *wrapped function's* module
globals — an alias reached through a namespace raises `InvalidSignature`.

⚠️ **Validate arguments BEFORE preflight.** `pinterest` refuses a missing `term`
from the arguments alone, so a malformed call never touches Redis and never
constructs a client — and constructing a Pinterest client on an empty vault is a
bounded **120-second wait** before it raises.

### Where the code lives

`mcp_server/` is a package, not one file (D-53, 2026-09-01 — it was a single
699-line `server.py` before that). Tools register **on import**:

| File | Holds |
|---|---|
| `_plumbing.py` | the shared `mcp` instance, `_ok`/`_fail`/`_guarded`/`_preflight` |
| `tools_system.py` | can this run, did it run, what is it assuming (3) |
| `tools_opportunity.py` | is there room here (5) |
| `tools_economics.py` | does it pay (3) |
| `tools_decide.py` | what should I list, and when (4) |
| `tools_learning.py` | did it work (3) |
| `tools_pinterest.py` | audience, timing, momentum — 15 operations |
| `tools_pinterest_research.py` | composed research over `pinterest/products/` — 11 operations |
| `tools_crawl.py` | recursive keyword discovery — the only seller-tier tool, hard-capped |
| `tools_analyze.py` | the judgements — DB-backed or pure, no network, no preflight |
| `tools_etsy.py` | the two Etsy tiers, kept as separate tools so D-29 is visible at the call site |
| `tools_history.py` | the append-only series + the LEARN join, which lives in a different database |
| `server.py` | wiring + `main()` only — no tool definitions |

⚠️ **Adding a tool module means adding its import to `server.py`.** Those imports
look unused (`# noqa: F401`) and are not: without one, its tools simply do not
exist, and the server still starts and answers normally. `test_server.py`'s
`check_package_layout()` asserts every `tools_*.py` is imported, for exactly that
reason.

⚠️ **Any new decorator in the stack must use `functools.wraps`.** MCP builds a
tool's schema from the callable's signature; a bare `*a, **kw` wrapper publishes
one demanding arguments named `a` and `kw`. That broke all 13 tools once, and
`list_tools()` reported them healthy the whole time.

### Four design rules

**1. Read only.** Nothing lists a product, edits a shop, places an order, or
spends money. The Printify token in `.env` carries `products.write` and
`orders.write`; no tool touches them. An agent that can publish on the operator's
behalf is a different product with a different risk profile.

**2. Every number carries its `basis`.** `measured` · `derived` · `bound` ·
`unmeasured` · `provisional`. This is the single most important property of the
surface, because the consumer is a language model, and a model handed a bare
number will present a bound as a fact. The server's `instructions` say so
explicitly, and every payload repeats it per-field.

**3. Refusals are results.** A tool that cannot answer returns
`{"ok": false, "error": ..., "fix": ...}` — never a plausible zero. An empty
vault, an untrusted filter, an unconfirmed fee schedule and a too-small pool are
all *answers*, and each names what would resolve it.

**4. Preflight before anything live.** An empty session pool does not fail, it
**hangs** — `get_valid_account` sleeps in an unbounded loop. A tool call that
never returns is the worst failure mode for an agent, so live tools gate on
`vault_status.scan()`, which never blocks.

### What an agent should do first

Call `vault_status`. If `ready` is false, say so and stop — every live tool will
refuse anyway, and the fix is on the operator's side (sign in to Chrome so the
extension re-posts cookies).

Then `filter_trust_report` before quoting any saturation percentage, and
`settings_summary` before quoting any profit figure. Both take a moment and both
prevent confidently reporting a number that is not true.

### Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Client shows 0 tools, or fails to start the server | `command` path wrong, or venv not built | Run the verify snippet above by hand; fix the path in the client's MCP config |
| Tool schemas require odd params like `a`/`kw` | Was a real bug once (`_guarded` decorator lost the signature) — regression-tested in `mcp_server/test_server.py` | Run that test; if it fails, the fix is `functools.wraps` on the wrapper |
| Every live tool returns `ready: false` | Empty session vault | Open Chrome with the extension logged in so it re-posts cookies to the vault; then `vault_status` again |
| A number looks off | Check `basis` on that field first | `provisional`/`default`/`bound` are not the same claim as `measured` — the tool is telling you, not lying |
| Antigravity/Claude Desktop can't find `config/`, `.env`, or the database | `cwd` missing or wrong in the MCP config | `cwd` must be the repo root, exactly as in the JSON block above |

---

## Part 2 — where DeepSeek goes

`core/llm_client.py` already calls DeepSeek to summarise negative reviews into
pain points. That is exactly the right shape. The rule that should govern every
future use:

> ### DeepSeek touches text. It never produces a number.

| ✅ Legitimate | ❌ Never |
|---|---|
| Review pain points → what to fix *(built)* | COGS, price, search volume, CVR |
| Draft title / tags / description from **mined** tags | "Estimate demand for…" |
| Explain a verdict in plain language | Decide the verdict |
| Cluster keywords into product concepts | Score or rank the clusters |
| Summarise a competitor's description | Judge whether they are winning |
| Narrate what changed between two readings | Compute the change |

The moment an LLM produces a figure the operator acts on, the system has a
plausible wrong number with no provenance — the exact thing every guard here
exists to stop (D-27). The `basis` field is the test: if a number cannot be
tagged `measured` or `derived` from something measured, it must not exist.

### In the UI — attach it to objects, not to a corner

A floating chat box invites precisely the questions the assistant must refuse
("what do you think this will sell for?"). Instead, put it where there is already
real data to hand it:

| Control | Where it lives | What it is given |
|---|---|---|
| **"Why?"** | beside every verdict | the structured verdict dict **with its `basis` fields** |
| **"Draft copy"** | on a candidate product | mined tags + the titles of ranked competitors |
| **"Pain points"** | on a competitor listing | its negative reviews *(already built)* |
| **"What changed?"** | on a flipped verdict | the diff between two observations |

Every one is contextual, arrives with real data attached, and cannot invent —
because the numbers are computed before the model is called, and the model's job
is only to phrase them.

**Implementation shape:** each button posts a structured payload to a thin
endpoint that builds the prompt from that payload and nothing else. No endpoint
takes free-form user text and returns a figure. If a prompt ever needs a number
the payload does not contain, that is a signal to build the measurement, not to
let the model fill it in.

### Prompt rule

Every system prompt should carry a version of:

> You are given figures that have already been computed and labelled. Restate
> them exactly, including whether each is measured, derived, a bound, or
> unmeasured. Never estimate a figure that is not present — say it is unmeasured
> instead. A bound is an upper limit and must never be described as a rate.

That last sentence is not decoration. The survivor bound, the badge-derived sales
figure, and the shop-counter bound are all upper limits that read naturally as
rates, and all three have been misread before.
