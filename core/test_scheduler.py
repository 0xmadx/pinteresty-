"""The clock, and the ways a clock lies.

Every assertion here defends a gap that would be invisible afterwards. A skipped
window leaves no row, and a missing row is indistinguishable from a day the shop did
not change — which is exactly the reading the whole system is built on.

Offline: fake jobs, a temp state file, an injected clock.

    .venv/Scripts/python.exe -m core.test_scheduler
"""
import json
import pathlib
import tempfile
from datetime import datetime, timedelta, timezone

import core.scheduler as scheduler
from core.scheduler import Job, Scheduler

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def tmp_state():
    return pathlib.Path(tempfile.mkdtemp()) / "state.json"


T0 = datetime(2026, 8, 15, 9, 0, tzinfo=timezone.utc)


def make(jobs=None, path=None):
    return Scheduler(jobs or [Job("daily", 24, lambda: {"ok": 1})], path or tmp_state())


# --- a job never run is due -------------------------------------------------------
s = make()
check("a never-run job is due", [j.name for j in s.due(T0)] == ["daily"])

# --- due-ness is measured from the last SUCCESS, and persists ----------------------
path = tmp_state()
s = Scheduler([Job("daily", 24, lambda: {"ok": 1})], path)
s.run_job(s.jobs["daily"], now=T0)
check("not due 1h later", s.due(T0 + timedelta(hours=1)) == [])
check("not due 23h later", s.due(T0 + timedelta(hours=23)) == [])
check("due again at 24h", [j.name for j in s.due(T0 + timedelta(hours=24))] == ["daily"])

reloaded = Scheduler([Job("daily", 24, lambda: {"ok": 1})], path)
check("schedule survives a restart", reloaded.due(T0 + timedelta(hours=1)) == [])
# Without persistence every invocation would think nothing had ever run, and a
# Task Scheduler firing hourly would sweep hourly.

# --- a missed window runs LATE, it does not vanish ---------------------------------
s = Scheduler([Job("daily", 24, lambda: {"ok": 1})], tmp_state())
s.run_job(s.jobs["daily"], now=T0)
check("a 3-day outage leaves the job due, not skipped",
      [j.name for j in s.due(T0 + timedelta(days=3))] == ["daily"])
# The alternative — "next run = now + 24h" — silently drops every window the machine
# was asleep for, and afterwards the absence is indistinguishable from no change.

# --- failure is not success --------------------------------------------------------
def boom():
    raise RuntimeError("etsy said no")


path = tmp_state()
s = Scheduler([Job("daily", 24, boom)], path)
outcome = s.run_job(s.jobs["daily"], now=T0)
check("a raising job is caught, not propagated", outcome["status"] == "failed", outcome)
check("the error is recorded", "etsy said no" in outcome["detail"], outcome)
check("a failed job stays due", [j.name for j in s.due(T0)] == ["daily"])
# Recording last_success on failure would mark the window done and lose it forever.
state = json.loads(path.read_text(encoding="utf-8"))
check("no last_success is written on failure", "last_success" not in state["daily"], state)
check("the attempt IS recorded", "last_attempt" in state["daily"], state)
check("a traceback is kept for diagnosis", "last_traceback" in state["daily"])

# --- one failing job must not stop the others ---------------------------------------
ran = []
s = Scheduler([Job("first", 24, boom),
               Job("second", 24, lambda: ran.append("second") or {"ok": 1})],
              tmp_state())
outcomes = s.run_due(now=T0)
check("both jobs are attempted", len(outcomes) == 2, outcomes)
check("the healthy job still ran", ran == ["second"], ran)
check("statuses are reported separately",
      {o["job"]: o["status"] for o in outcomes} == {"first": "failed", "second": "ok"},
      outcomes)
# Losing the Pinterest bridge is no reason to skip the shop delta.

# --- a missing session is a REFUSAL, not a failure and not a success -----------------
class FakePreflightFailed(RuntimeError):
    pass


import core.preflight as preflight  # noqa: E402

_real_require = preflight.require
preflight.require = lambda *a, **k: (_ for _ in ()).throw(
    preflight.PreflightFailed("No usable session for: etsy_private."))

path = tmp_state()
s = Scheduler([Job("needs_seller", 24, lambda: {"ok": 1}, platforms=("etsy_private",))],
              path)
outcome = s.run_job(s.jobs["needs_seller"], now=T0)
check("a job with no session is refused", outcome["status"] == "refused", outcome)
check("refusal names the platform", "etsy_private" in outcome["detail"], outcome)
check("a refused job stays due", [j.name for j in s.due(T0)] == ["needs_seller"])
state = json.loads(path.read_text(encoding="utf-8"))
check("refusal is distinguishable from failure",
      state["needs_seller"]["last_status"] == "refused", state)
# The distinction matters: 'failed' means the site or the code broke and is worth
# investigating; 'refused' means open Chrome. Collapsing them sends the operator
# hunting for a bug that is not there.

preflight.require = _real_require

# --- a job that needs nothing skips preflight entirely ------------------------------
s = Scheduler([Job("local", 24, lambda: {"ok": 1})], tmp_state())
check("a session-free job runs without preflight",
      s.run_job(s.jobs["local"], now=T0)["status"] == "ok")

# --- corrupt state must not stop the clock -------------------------------------------
path = tmp_state()
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text("{not json", encoding="utf-8")
s = Scheduler([Job("daily", 24, lambda: {"ok": 1})], path)
check("corrupt state means everything is due, not nothing",
      [j.name for j in s.due(T0)] == ["daily"])
# Refusing to run on a bad state file stops the time-series silently; re-running a
# job is merely a duplicate reading, and the tables are append-only by design.

# --- the state file stays readable ---------------------------------------------------
path = tmp_state()
s = Scheduler([Job("big", 24, lambda: {"listings": list(range(500))})], path)
s.run_job(s.jobs["big"], now=T0)
stored = json.loads(path.read_text(encoding="utf-8"))["big"]["last_result"]
check("a huge result is truncated in state", len(stored) <= 401, len(stored))

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
