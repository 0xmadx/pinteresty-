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


def main():
    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
