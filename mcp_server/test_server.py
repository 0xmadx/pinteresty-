"""End-to-end MCP test: launch the server as a real subprocess, speak the protocol.

THIS FILE EXISTS BECAUSE AN IN-PROCESS CHECK LIED. `mcp.list_tools()` reported all
13 tools registered and healthy while every single one failed on invocation: the
`_guarded` decorator wrapped each function as `*a, **kw`, so MCP published a schema
demanding two required arguments named `a` and `kw`. Registration is not wiring.

Only a real stdio round trip that CALLS a tool catches that class of bug, so this
calls three — one with no arguments, one parameterised, one hitting the database —
and asserts on the published schemas as well as the results.

    python -m mcp_server.test_server

Needs no network and no session vault: every tool exercised here is local.
"""
import asyncio
import json
import os
import pathlib
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


async def run():
    params = StdioServerParameters(
        command=os.path.join(REPO, ".venv", "Scripts", "python.exe"),
        args=["-m", "mcp_server.server"],
        cwd=REPO,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print()
            check("the server starts and identifies itself",
                  init.server_info.name == "etsy-market-intel", init.server_info.name)

            tools = (await session.list_tools()).tools
            check("every tool registers", len(tools) >= 13, len(tools))
            check("the instructions tell a model to read the basis field",
                  "basis" in (init.instructions or ""), init.instructions)

            # --- the bug this file exists for -------------------------------------------
            print()
            by_name = {t.name: t for t in tools}
            schema = by_name["filter_trust_report"].input_schema
            check("a no-argument tool publishes NO required arguments",
                  not schema.get("required"), schema.get("required"))
            schema = by_name["verdict_history"].input_schema
            check("a parameterised tool publishes its REAL parameter",
                  schema.get("required") == ["subject"], schema.get("required"))
            check("no tool leaks the decorator's *a/**kw into its schema",
                  not any(k in (t.input_schema.get("properties") or {})
                          for t in tools for k in ("a", "kw")),
                  [t.name for t in tools
                   if "kw" in (t.input_schema.get("properties") or {})])

            # --- the context budget, enforced rather than hoped for ---------------
            # Capabilities = ungrouped tools + every operation of a grouped one.
            # Counted here so the budget can be read per-capability rather than as
            # a bare total, which would penalise reach instead of bloat.
            capabilities = 0
            for t in tools:
                op = (t.input_schema.get("properties") or {}).get("operation") or {}
                capabilities += len(op["enum"]) if "enum" in op else 1
            # Every tool schema is resident in the agent's context for the whole
            # session, so the surface competes with the work. The grouped-tool
            # design exists to hold this line while capability grows; without an
            # assertion it would drift back up one convenient tool at a time.
            sizes = {t.name: len(json.dumps(
                t.model_dump(mode="json", by_alias=True, exclude_none=True)))
                for t in tools}
            total = sum(sizes.values())
            # 4,000 originally, raised to 6,000 by the operator on 2026-09-01
            # (D-58) once the lower figure stopped catching waste and started
            # cutting warnings. It did its job first: ~2,600 chars of genuine
            # waste came out across three commits while it was binding.
            #
            # The number to watch is EFFICIENCY, not size: ~75 tokens per
            # capability here, against ~180 per tool under one-tool-per-
            # capability. 6,000 leaves room for the remaining tool groups and is
            # still a fraction of the ~38,000 a flat surface would cost.
            budget = 6000
            per_cap = total / 4 / max(1, capabilities)
            check(f"published surface stays within {budget} tokens "
                  f"({total:,} chars ≈ {total // 4:,}, {per_cap:.0f}/capability)",
                  total // 4 <= budget,
                  f"largest: {sorted(sizes.items(), key=lambda kv: -kv[1])[:3]}")
            check("and grouping keeps it under 120 tokens per capability — the "
                  "property that actually matters, not the raw total",
                  per_cap < 120, f"{per_cap:.0f} tokens/capability")

            check("no tool publishes per-parameter `title` keys — pure waste",
                  not any("title" in p
                          for t in tools
                          for p in (t.input_schema.get("properties") or {}).values()
                          if isinstance(p, dict)),
                  [t.name for t in tools
                   if any("title" in p for p in
                          (t.input_schema.get("properties") or {}).values()
                          if isinstance(p, dict))])

            # Stripping titles must not have taken the descriptions with it —
            # that is the one channel an agent reads to choose correctly.
            check("but operation descriptions SURVIVE the strip",
                  all("description" in by_name[n].input_schema["properties"]["operation"]
                      for n in ("pinterest", "pinterest_research")),
                  "an operation enum with no description is unusable")

            # --- the grouped-tool schema, as PUBLISHED over the wire ---------------
            op = by_name["pinterest"].input_schema["properties"]["operation"]
            check("operation publishes as a top-level enum, not anyOf",
                  "enum" in op and "anyOf" not in op, list(op))
            check("no $ref indirection — the options are inline",
                  "$ref" not in json.dumps(op), op)
            check("every operation is reachable (the enum is not truncated)",
                  len(op["enum"]) >= 15, len(op.get("enum", [])))
            check("operation is REQUIRED — a defaulted one lets an agent guess",
                  "operation" in by_name["pinterest"].input_schema.get("required", []),
                  by_name["pinterest"].input_schema.get("required"))

            # --- calling them, which is the only real proof --------------------------------
            print()
            for name, args, must_contain in [
                ("filter_trust_report", {}, "not_a_subset"),
                ("price_and_cost_ladder",
                 {"product_type": "personalized", "shipping_cost": 7.99}, "max_cogs"),
                ("verdict_history", {"subject": "nothing-recorded"}, "readings"),
                ("settings_summary", {}, "confirmed"),
            ]:
                res = await session.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                payload = json.loads(text) if text.strip().startswith("{") else {}
                check(f"{name} returns a result when actually CALLED",
                      payload.get("ok") is True, text[:130])
                check(f"{name} returns real content, not an error string",
                      must_contain in text, text[:130])

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


def tool_source(name):
    """The source of one tool, found ANYWHERE in the mcp_server package.

    Deliberately not a hardcoded file path. These checks used to open
    `server.py` directly, which broke the moment the tools were split into
    per-domain modules (D-53) even though nothing about their behaviour changed
    — a test that fails on a file move is testing the layout, not the property.
    """
    for path in sorted(pathlib.Path(REPO, "mcp_server").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        marker = f"\ndef {name}("
        if marker not in src:
            continue
        start = src.index(marker)
        nxt = src.find("\n@mcp.tool()", start)
        return src[start:nxt if nxt != -1 else len(src)], path.name
    raise AssertionError(f"tool {name!r} not found anywhere in mcp_server/")


def check_one_read_layer():
    """discover() must route through app_data, not query the database itself.

    A behavioural test cannot tell these apart — app_data.build_discovered() is a
    thin field-projection over the exact same MarketDatabase.latest_discovered(),
    so the outputs are near-identical either way. The property that actually
    matters (D-41: ONE read layer, presentation reads through it and never past
    it) is a fact about which CODE PATH is taken, so that is what gets asserted.

    This is the regression that prompted the fix: discover() used to query
    MarketDatabase directly, its own second implementation of "what counts as
    discovered" that could silently drift from what the web UI showed for the
    identical pool. The UI is gone (D-52) and MCP is now the read layer's ONLY
    consumer, which makes this stricter, not looser: nothing else is left to
    notice a drift.
    """
    body, where = tool_source("discover")
    check(f"discover() routes through etsy.ui.app_data (D-41) [{where}]",
          "from etsy.ui.app_data import build_discovered" in body, body[:200])
    check("discover() does not query MarketDatabase directly any more",
          "MarketDatabase()" not in body, body[:200])


def check_deep_dive_wiring():
    """deep_dive_keyword must preflight both platforms, and the engine it wraps
    must actually return its result.

    HybridArbitrageEngine.run() had no return statement on its success path
    (D-50) -- only its own CLI ever called it, and only ever read the JSON file
    it wrote rather than using the return value. A behavioural test would need a
    live, several-minute run to catch a regression here; both properties are
    facts about the source, so that is what gets asserted instead.
    """
    body, where = tool_source("deep_dive_keyword")
    check(f"deep_dive_keyword preflights etsy AND etsy_private [{where}]",
          '_preflight(("etsy", "etsy_private"))' in body, body[:200])
    check("deep_dive_keyword wraps HybridArbitrageEngine",
          "HybridArbitrageEngine" in body, body[:200])

    engine_src = open(os.path.join(REPO, "etsy", "engines", "master_arbitrage.py"),
                      encoding="utf-8").read()
    run_start = engine_src.index("\n    def run(self):")
    check("HybridArbitrageEngine.run() returns its payload on the success path",
          "return final_payload" in engine_src[run_start:],
          "run() building final_payload but never returning it means every "
          "programmatic caller (MCP included) gets None back on success")


def check_stdout_is_protected():
    """A tool that prints must not corrupt the JSON-RPC stream.

    The server speaks JSON-RPC over STDOUT. Anything a tool prints lands in the
    middle of that stream, and the failure mode is a dead connection rather than
    a wrong answer — no `basis` field helps. The layers these tools call print
    freely: ten print() calls sit under the Pinterest path alone, including
    cookie_vault's "waiting for the extension" line, which fires exactly when a
    session is missing and a tool is most likely to be called.

    `_guarded` redirects stdout to stderr for every tool, so this asserts the
    guard rather than trusting each tool author to remember.
    """
    import contextlib
    import io

    from mcp_server._plumbing import _guarded

    @_guarded
    def noisy_tool():
        print("this would corrupt the protocol")
        return {"ok": True, "value": 1}

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = noisy_tool()
    check("a tool's print() never reaches stdout", buf.getvalue() == "",
          repr(buf.getvalue()))
    check("and the tool still returns its payload", result.get("value") == 1, result)

    # The guard must not swallow the exception path either.
    @_guarded
    def noisy_and_broken():
        print("noise before the failure")
        raise RuntimeError("boom")

    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        failed = noisy_and_broken()
    check("stdout stays clean even when the tool raises", buf2.getvalue() == "",
          repr(buf2.getvalue()))
    check("and the failure still comes back as a structured refusal",
          failed.get("ok") is False and "boom" in failed.get("error", ""), failed)


def check_grouped_tool_contract():
    """A grouped tool must publish a real enum, and refuse before it spends.

    The whole expansion rests on `operation` publishing as an inline JSON-schema
    `enum`. Two ways that silently degrades, both measured on this SDK:
    `Optional[Literal[...]]` collapses it into an `anyOf` with the enum buried a
    level down, and an `Enum` subclass hoists into `$defs` behind a `$ref`. Either
    still "works" while being worse for the agent, so it needs an assertion.

    The second half is about cost: a call missing a required argument must be
    refused from the arguments alone, BEFORE `_preflight` touches Redis and long
    before a client is constructed — construction on an empty vault is a bounded
    120-second wait.
    """
    from mcp_server import tools_pinterest as tp

    src = pathlib.Path(REPO, "mcp_server", "tools_pinterest.py").read_text(encoding="utf-8")
    val = src.index("_NEEDS_TERM and not term")
    pre = src.index('_preflight(("pinterest",))')
    check("argument refusals come BEFORE preflight, so a bad call costs nothing",
          val < pre, f"validation at {val}, preflight at {pre}")
    check("the client is constructed only after preflight",
          pre < src.index("api = _client()"))

    fn = tp.pinterest.__wrapped__
    r = fn(operation="metrics")           # missing `term`
    check("a missing required arg is a structured refusal, not an exception",
          r.get("ok") is False and "needs `term`" in r.get("error", ""), r)
    check("and the refusal names what would fix it", bool(r.get("fix")), r)

    r2 = fn(operation="top_products")     # missing `category_id`
    check("category operations refuse without a category_id",
          r2.get("ok") is False and "category_id" in r2.get("error", ""), r2)


def check_package_layout():
    """The split itself: every tool registers, and none went missing in the move.

    D-53 moved 18 tools out of one 699-line file into five domain modules that
    register on import. The failure mode that would be invisible otherwise is a
    module `server.py` forgets to import — its tools simply do not exist, and a
    server with 14 tools starts and answers perfectly well.
    """
    server_src = pathlib.Path(REPO, "mcp_server", "server.py").read_text(encoding="utf-8")
    modules = sorted(p.stem for p in pathlib.Path(REPO, "mcp_server").glob("tools_*.py"))
    check("there are per-domain tool modules to import", len(modules) >= 5, modules)
    for m in modules:
        check(f"server.py imports {m} (or its tools vanish silently)",
              m in server_src, server_src[:400])
    check("server.py holds no tool definitions itself — it is wiring only",
          "@mcp.tool()" not in server_src, "server.py should only import and run")


def main():
    check_stdout_is_protected()
    check_grouped_tool_contract()
    check_package_layout()
    check_one_read_layer()
    check_deep_dive_wiring()
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
