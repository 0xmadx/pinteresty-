"""MCP surface for this project — one tool per question the operator asks.

    .venv/Scripts/python.exe -m mcp_server.server

Register it with Claude Code / Antigravity / any MCP client (see docs/MCP.md).

**This file is the wiring, not the tools.** It was a single 699-line module until
2026-09-01; the tools now live in per-domain siblings and register themselves on
import (D-53). The split is a prerequisite for opening the surface up — MCP
reached ~7.5% of this codebase, and that expansion is unmaintainable in one file.

    _plumbing.py         the shared `mcp` instance, _ok/_fail/_guarded/_preflight
    tools_system.py      can this run, did it run, what is it assuming
    tools_opportunity.py is there room here
    tools_economics.py   does it pay
    tools_decide.py      what should I list, and when
    tools_learning.py    did it work

DESIGN RULES, in the order they matter
--------------------------------------

**1. Read only.** No tool here lists a product, edits a shop, places an order, or
writes to Etsy or Printify. The token in .env carries products.write and
orders.write; nothing below touches them. An agent that can spend money or
publish on the operator's behalf is a different product with a different risk
profile, and this is not it.

**2. Every number carries its provenance.** Values come back with `basis`
(measured / derived / bound / unmeasured / provisional) attached, because the
consumer is a language model that will otherwise present a bound as a fact. This
is the single most important property of this surface.

**3. Refusals are results.** A tool that cannot answer returns
`{"error": ..., "fix": ...}` and never a plausible zero. `PoolTooSmall`,
`SessionDown`, an untrusted filter and an unconfirmed fee schedule are all
answers, and each names what would resolve it.

**4. The vault is checked before anything live.** An empty session pool does not
fail — it HANGS, in an unbounded sleep loop. A tool call that never returns is
the worst failure mode for an agent, so `preflight` gates every live tool.

**5. One tool per question, not one per module.** `analyze_keyword` answers "is
there room here", which internally touches four modules. An agent should not have
to know this codebase's file layout to use it.

**6. The private tier is the scarce asset.** `etsy_private` authenticates as the
operator's OWN seller account (D-29). A buyer session costs a re-login to
replace; that one costs the business. Tools that spend it say so in their
docstring, and recursive/crawling tools must cap how much of it they can spend.
"""
from mcp_server._plumbing import mcp, strip_schema_titles

# Imported for the side effect of registering their tools on `mcp`. They look
# unused and are not — deleting one silently removes those tools from the server.
from mcp_server import (  # noqa: F401
    tools_crawl,
    tools_decide,
    tools_economics,
    tools_learning,
    tools_opportunity,
    tools_pinterest,
    tools_pinterest_research,
    tools_system,
)


# Every tool is now registered, so the published schemas can be trimmed once.
# Runs at import rather than in main() so `list_tools()` is identical whether the
# server is run as a subprocess or imported by a test.
strip_schema_titles()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
