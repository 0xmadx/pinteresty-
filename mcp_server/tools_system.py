"""System state — can this run, did it run, what is it assuming?

Split out of the single 699-line `server.py` (D-53). Registration happens
on import — `server.py` imports this module for that side effect alone.
Every tool here follows the same contract: `@mcp.tool()` outermost,
`@_guarded` innermost, `_preflight` first if it touches the network, and
`_ok`/`_fail` with a per-field `basis` on the way out.
"""
import json
import os

from mcp_server._plumbing import _fail, _guarded, _ok, _preflight, mcp


@mcp.tool()
@_guarded
def vault_status() -> dict:
    """Can this system make live calls right now? Check FIRST, before any live tool.

    An empty session pool does not raise — it sleeps forever waiting for the Chrome
    extension. Every live tool here gates on this, but calling it first turns a
    mysterious refusal into a clear one.
    """
    from core import vault_status as vs
    try:
        report = vs.scan()
    except Exception as e:
        return _fail(f"cannot reach the session vault: {e}",
                     fix="Is the Docker Redis container running? Two Redis servers "
                         "share port 6379 here (D-30); `localhost` reaches a stale "
                         "native one. Check: python -m core.vault_status")
    per_platform = {p: {"usable": len(r["usable"]), "known": len(r["profiles"])}
                    for p, r in report.items()}
    return _ok({"sessions": per_platform,
                "ready": bool(per_platform.get("etsy", {}).get("usable")),
                "note": "etsy = public scraping. etsy_private = the operator's OWN "
                        "seller account; never used to ask about a competitor. "
                        "usable < known means profiles are present but stale or "
                        "signed out."})


@mcp.tool()
@_guarded
def run_health(limit: int = 10) -> dict:
    """Did the scheduled jobs actually run? Job status, last success, and staleness.

    The system's value compounds only if the clock keeps running. This is where a
    silently dead scheduler becomes visible.
    """
    from core.scheduler import Scheduler, default_jobs
    sched = Scheduler(default_jobs())
    jobs = []
    for job in sched.jobs.values():
        last = sched.last_success(job.name)
        jobs.append({"job": job.name, "every_hours": job.every_hours,
                     "last_success": last.isoformat() if last else None,
                     "due_now": job in sched.due(),
                     "basis": "measured" if last else "unmeasured",
                     "description": job.description})
    return _ok({"jobs": jobs,
                "note": "last_success=None means this reading has NEVER been taken. "
                        "History cannot be backfilled."})


@mcp.tool()
@_guarded
def settings_summary() -> dict:
    """The operator's fee schedule, cost assumptions and margin floors.

    `confirmed` is the field that matters: while it is empty, EVERY profit verdict
    this system produces is provisional, because the fee and cost inputs are
    defaults rather than the operator's real numbers.
    """
    path = os.path.join("config", "settings.json")
    if not os.path.exists(path):
        return _fail("config/settings.json is missing",
                     fix="python -m core.settings_store init")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    confirmed = raw.get("confirmed") or []
    return _ok({"settings": raw, "confirmed": confirmed,
                "all_verdicts_provisional": not confirmed,
                "note": "Nothing confirmed means every margin and capacity figure "
                        "rests on defaults, not on this operator's real costs."})
