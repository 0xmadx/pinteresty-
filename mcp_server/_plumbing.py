"""The shared server instance and the four things every tool is built on.

Split out of `server.py` (D-53) so tools can live in per-domain modules without a
circular import: the `mcp` instance has to be importable by every tool module,
and `server.py` imports those modules purely to trigger registration.

⚠️ **`functools.wraps` in `_guarded` is load-bearing, not tidiness.** MCP builds
each tool's input schema by inspecting the callable's signature. A bare
`*a, **kw` wrapper publishes a schema demanding two required arguments named `a`
and `kw` — every tool then registers cleanly and fails on every actual call. That
happened once here, to all 13 tools at the time, and an in-process
`list_tools()` check could not see it; only a real stdio round trip caught it.
`wraps` sets `__wrapped__`, which `inspect.signature` follows back to the true
parameters. **Any new decorator layered into this stack must do the same.**
"""
import functools
import traceback

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="etsy-market-intel",
    instructions=(
        "Market intelligence for one Etsy seller, joining Etsy Private (demand), "
        "Etsy Public (supply) and Pinterest (momentum).\n\n"
        "READ THE `basis` FIELD ON EVERY NUMBER AND REPORT IT. `measured` is a "
        "fact; `derived` is computed from facts; `bound` is an upper limit and must "
        "never be restated as a rate; `unmeasured` means nobody looked, which is NOT "
        "zero; `provisional` means the operator has not confirmed the fee/cost inputs "
        "so the verdict may move.\n\n"
        "Rank opportunities by demand-per-listing, never by search volume — a term "
        "with 2M listings is a wall, not an opportunity.\n\n"
        "Every tool is read-only. Nothing here can list a product or spend money; if "
        "asked to, say so and hand the step back to the operator."
    ),
)


def _ok(payload, **meta):
    # `payload` is splatted LAST on purpose: a tool that sets a key in its payload
    # wins over a same-named meta key rather than being silently overridden.
    return {"ok": True, **meta, **payload}


def _fail(error, fix=None, **meta):
    """A refusal is a result. It always says what would resolve it."""
    return {"ok": False, "error": str(error), "fix": fix, **meta}


def _guarded(fn):
    """Turn any exception into a structured refusal rather than a protocol error.

    See the module docstring for why `functools.wraps` cannot be dropped here.
    """
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:
            return _fail(f"{type(e).__name__}: {e}",
                         fix="See traceback in `detail`; most failures here are a "
                             "stale session vault or a missing config value.",
                         detail=traceback.format_exc()[-1200:])
    return wrapper


def _preflight(platforms=("etsy",)):
    """Refuse fast when the session pool is empty. It HANGS otherwise, not fails.

    Uses vault_status.scan(), which never blocks. RedisCookieVault.get_valid_account()
    is the wrong call here: it sleeps in an unbounded loop waiting for the Chrome
    extension, which from an agent's side is a tool that simply never returns.
    """
    from core import vault_status as vs
    try:
        report = vs.scan(tuple(platforms))
    except Exception as e:
        return _fail(f"cannot reach the session vault: {e}",
                     fix="Is the Docker Redis container running? Note that two Redis "
                         "servers share port 6379 on this machine (D-30) — `localhost` "
                         "reaches a stale native one. Check: python -m core.vault_status")
    missing = [p for p in platforms if not report.get(p, {}).get("usable")]
    if missing:
        return _fail(
            f"no valid sessions for: {', '.join(missing)}",
            fix="Open Chrome with the extension signed in to Etsy/Pinterest so it "
                "re-posts cookies to the Go cookie server, then retry. Check with: "
                "python -m core.vault_status. An empty pool makes live calls hang, "
                "so this refuses up front instead.")
    return None
