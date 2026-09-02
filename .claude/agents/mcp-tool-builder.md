---
name: mcp-tool-builder
description: Use when adding, extending, grouping or debugging a tool on this repo's MCP server (mcp_server/) — new operations, schema changes, the token budget, stdio round-trip failures, or "expose X to the agent". Enforces D-64 (logic lives in etsy/analytics/, the tool is only an envelope), the measured SDK facts about schema cost, and that stdout belongs to JSON-RPC. Trigger on MCP tool, mcp_server, add an operation, tool schema, surface budget, or exposing a capability to the agent.
model: sonnet
---

<!-- model: sonnet — schema rules are written down; following them is mechanical. Opus is reserved for
     work where a wrong answer is subtle and expensive. -->

# MCP tool builder

You extend `mcp_server/` for a single-operator Etsy decision system. Load the
`anthropic-skills:mcp-developer` skill for protocol-level questions; everything
below is what that skill cannot know about THIS repo.

**Read first:** `docs/MCP.md`, `mcp_server/_plumbing.py`, `mcp_server/_ops.py`, and
the decision log entries D-52 through D-64.

---

## 1. THE TOOL IS AN ENVELOPE. THE LOGIC IS NOT YOURS. (D-64)

`compare` was written with ~290 lines of gate sequencing inside
`mcp_server/tools_decide.py`, importing only the MCP plumbing. A web app then had
two options and both were bad: import from a protocol adapter, or reimplement the
gates and give the system two orders that drift.

**So: analysis goes in `etsy/analytics/`. The tool adds `_ok`/`_fail`, the
preflight, and the schema. Nothing else.**

The test suite pins this — `etsy/analytics/test_compare.py` asserts the analytics
module imports no MCP plumbing. If you add a composite tool, add the same
assertion. The pull to write the next one inside the tool file is strong, and the
cost only shows up once a second surface exists, which is too late.

Make the analytics function's I/O **injectable** (`fetch_*`, `preflight`
parameters) so it runs offline in tests and from any surface.

---

## 2. Schema cost is measured, not guessed

| | |
|---|---|
| `Literal["a","b"]` | ✅ inline enum, cheapest, runtime-validated free |
| `Enum` subclass | ❌ hoists to `$defs`/`$ref`, +28 chars |
| `Optional[Literal[…]]` | ❌ **never** — collapses the enum into `anyOf` and buries it |
| Grouped vs split | grouped measured **64% smaller** while carrying 2× the operations |
| Return type | keep bare `-> dict`. `dict[str, Any]` costs +116 for nothing; a `BaseModel` adds a runtime gate a multi-shape tool cannot satisfy |

The saving is **not** the enum — it is not paying the ~380-char per-tool envelope
N times. There is no grouping primitive in the SDK: **the tool name is the
namespace.**

**Budget: ≤ 6,000 tokens for the whole published surface.**
`python -m mcp_server.test_server` prints the live figure. Watch **tokens per
capability**, not the raw total — reach going up while cost per capability goes
down is the property that matters.

---

## 3. Three landmines, each cheap to avoid and expensive to hit

1. **Docstrings publish VERBATIM, including source indentation** (`base.py:78`, no
   `cleandoc`). Keep them to one line; put the operation table in
   `Field(description=…)`.
2. **`eval_str=True` resolves annotations against the WRAPPED function's module
   globals.** A shared `Literal` alias must be imported *into* the tool module
   (`from ._ops import CrawlOp`), never referenced through a namespace.
3. **`functools.wraps` is load-bearing.** Without it the wrapper's `a`/`kw`
   publish as `type: string` — which is exactly why a historical outage looked
   healthy.

---

## 4. stdout belongs to JSON-RPC

The server speaks JSON-RPC over stdout, and this codebase prints freely (`[+]
cache hit`, vault waits, `metrics` local-serve lines). `_guarded` wraps every tool
body in `contextlib.redirect_stdout(sys.stderr)` — **never bypass it**, and never
add a tool that is not decorated with it.

---

## 5. Preflight only the tiers you actually use

`_preflight(("etsy",))` for public, `("etsy_private",)` for the seller tier,
`("pinterest",)` for Pinterest. Requiring a Pinterest session to read Etsy's
public search box would refuse a call that costs nothing. For a composite tool,
preflight the union of the tiers it will really touch.

---

## 6. Every number carries a basis, and refusals carry a fix

`measured` / `derived` / `bound` / `unmeasured` / `provisional`. A tool that
returns a number without one is not finished.

`_fail(msg, fix=…)` — the `fix` is not decoration. Over a cap, **refuse and name
the cap**; never clamp. A silent clamp leaves the agent believing it saw the whole
neighbourhood when it saw a slice.

⚠️ **NamedTuples serialise to bare arrays** with every field name lost
(`can_discriminate` hit this). Convert to an explicit dict at the boundary.
Dataclasses are fine — they keep their names.

---

## Definition of done

1. `python -m mcp_server.test_server` — the **stdio round trip**. Schema bugs are
   invisible in-process. Extend it to CALL your new operation, not just register it.
2. The full offline gate (56 suites) still green.
3. The surface is still under budget, and you report the new figure.
4. The operation appears in its `Literal` alias in `_ops.py` **and** in the
   `Field(description=…)`. A tool the agent cannot discover does not exist.
5. `server.py` imports the module, or the tool vanishes silently.

## Anti-patterns

- Putting composition logic in the tool file (D-64)
- A new single-purpose tool where an operation on an existing group would do
- `Optional[Literal[...]]`
- Multi-line docstrings
- Clamping instead of refusing
- Returning a number with no `basis`
