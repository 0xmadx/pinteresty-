# MCP server, and where DeepSeek belongs

Two related things: how an agent (Claude Code, Antigravity, anything speaking
MCP) talks to this system, and the boundary that keeps an LLM from quietly
becoming a source of numbers.

---

## Part 1 — the MCP server

```bash
.venv/Scripts/python.exe -m mcp_server.server
```

Speaks stdio. 12 read-only tools.

### Wiring it up

**Claude Code / Claude Desktop** — add to your MCP config:

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

`cwd` matters: the server resolves `config/`, `market_intelligence.db` and
`.env` relative to the repo root.

**Antigravity** — same command and cwd, in whatever shape its MCP config takes.

### The tools

| Tool | Answers | Live? |
|---|---|---|
| `vault_status` | can this make live calls right now? | reads Redis |
| `run_health` | did the scheduled readings actually happen? | local |
| `analyze_keyword` | is there room here — demand, supply, the ratio | **live** |
| `sourcing_profile` | where do they ship from, how fast | **live** |
| `cheap_competitors` | why are the cheapest listings cheap? | **live** |
| `filter_trust_report` | which SERP filters can be believed | local |
| `profit_verdict` | go/no-go on one unit, with the binding reason | local |
| `price_and_cost_ladder` | at each price, the most it may cost to make | local |
| `pod_quote` | Printify cost and lead time for a chosen product | **live** |
| `learn_status` | did past predictions come true | local |
| `tracked_shops` | competitor shop deltas | local |
| `settings_summary` | fees, costs, and whether anything is confirmed | local |

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
