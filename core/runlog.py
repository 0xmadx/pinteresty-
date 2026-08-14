"""Structured run logging — one JSON line per stage.

`MIGRATION_AND_OPERATIONS.md:118-128`: a weekly batch system fails **silently**, and five
questions catch it. The repo's answer was ~330 `print()` calls, which answer none of
them — not because printing is wrong, but because nothing is *recorded*. Converting every
print to `logger.info()` would not have helped: the missing thing is a per-stage record
with counts, not prettier lines.

So this module adds the record and leaves the prints alone. Console output stays
human-readable for an operator watching a run; the JSONL is what answers the questions
afterwards.

    from core.runlog import stage

    with stage("arbitrage", seed="mom necklace") as s:
        ...
        s.count(rows_out=3, cache_hits=12, metered_calls=1)

On exit that appends one line to `etsy/data/logs/run_<date>.jsonl`:

    {"stage": "arbitrage", "started": "...", "duration_s": 84.2, "ok": true,
     "rows_out": 3, "cache_hits": 12, "metered_calls": 1,
     "guard_failures": {"shop.ld_json": 3}, "seed": "mom necklace"}

Guard-flag counts (question 3) are captured automatically from `core/guards.py` — the
early warning that a provider changed shape, per `MIGRATION_AND_OPERATIONS.md:136-138`.

Scale discipline: this is a single-operator weekly batch. A JSONL file is the whole
storage layer — no log server, no rotation daemon, no schema migration. `health()` reads
it back and answers all five questions in one call.
"""
import functools
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

from core import guards

# The stage currently running, so code deep inside a pipeline can add counts without
# every function in between growing a parameter it does not otherwise need.
_CURRENT = ContextVar("current_stage", default=None)

LOG_DIR = os.path.join("etsy", "data", "logs")

# Counters a stage may accumulate. Fixed set so the JSONL stays queryable — an arbitrary
# key would make every consumer defensive.
COUNTERS = ("rows_in", "rows_out", "cache_hits", "cache_misses", "metered_calls", "errors")


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def log_path(when=None):
    day = (when or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return os.path.join(LOG_DIR, f"run_{day}.jsonl")


class StageRecord:
    """Mutable counters for one stage. Handed to the caller by `stage()`."""

    def __init__(self, name, context):
        self.name = name
        self.context = context
        self.started = _utcnow()
        self._t0 = time.monotonic()
        self.counters = dict.fromkeys(COUNTERS, 0)
        self.ok = True
        self.error = None
        self.notes = []

    def count(self, **kwargs):
        """Add to one or more counters. Unknown names raise rather than silently vanish."""
        for key, value in kwargs.items():
            if key not in self.counters:
                raise ValueError(f"unknown counter {key!r}; expected one of {COUNTERS}")
            self.counters[key] += value
        return self

    def note(self, text):
        """A short free-text observation to carry into the record."""
        self.notes.append(text)
        return self

    def to_dict(self, guard_failures):
        return {
            "stage": self.name,
            "started": self.started,
            "finished": _utcnow(),
            "duration_s": round(time.monotonic() - self._t0, 3),
            "ok": self.ok,
            "error": self.error,
            **self.counters,
            # Question 3: a jump here means a source changed shape.
            "guard_failures": guard_failures,
            "guard_failure_total": sum(guard_failures.values()),
            "notes": self.notes,
            **self.context,
        }


def write_record(record, path=None):
    """Append one JSON line. Creates the directory on first use."""
    target = path or log_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return target


@contextmanager
def stage(name, path=None, quiet=False, reset=True, **context):
    """Record one stage of a run.

    Guard failures are counted **for this stage only**: the collector is reset on entry,
    so counts are per-stage rather than cumulative across a whole run.

    Pass `reset=False` when the stage record is written *after* the work it describes
    (a long loop that would be noisy to re-indent). The caller is then responsible for
    calling `guards.reset_failures()` before that work, or the record will include
    failures from earlier stages.

    An exception is recorded and then **re-raised**. A crashed stage must crash —
    `MIGRATION_AND_OPERATIONS.md:146` says re-run it, everything is idempotent and cached,
    so swallowing it here would trade a loud recoverable failure for a quiet partial one.
    """
    if reset:
        guards.reset_failures()
    record = StageRecord(name, context)
    token = _CURRENT.set(record)
    if not quiet:
        print(f"[stage] {name} started")
    try:
        yield record
    except BaseException as exc:
        record.ok = False
        record.error = f"{type(exc).__name__}: {exc}"
        record.counters["errors"] += 1
        raise
    finally:
        _CURRENT.reset(token)
        failures = dict(guards.summarise_failures())
        # Clear on the way out as well as in, so a guard failure is attributed to exactly
        # one stage. Without this a nested stage's failures are counted again by its
        # parent (whose window runs to its own exit), and health() double-counts them.
        # The parent still records anything that fails before the child starts or after
        # it finishes — which is the correct attribution.
        guards.reset_failures()
        payload = record.to_dict(failures)
        write_record(payload, path)
        if not quiet:
            status = "ok" if record.ok else f"FAILED ({record.error})"
            counts = " ".join(f"{k}={v}" for k, v in record.counters.items() if v)
            flags = (f" guard_failures={payload['guard_failure_total']}"
                     if payload["guard_failure_total"] else "")
            print(f"[stage] {name} {status} in {payload['duration_s']}s "
                  f"{counts}{flags}".rstrip())


def current_stage():
    """The running StageRecord, or None outside any stage."""
    return _CURRENT.get()


def count(**kwargs):
    """Add to the running stage's counters from anywhere. A no-op outside a stage.

    A no-op rather than an error on purpose: these modules are also imported by tests
    and run ad hoc from a REPL, and refusing to work outside a stage would make the
    instrumentation something you have to work around.
    """
    record = _CURRENT.get()
    if record is not None:
        record.count(**kwargs)


def logged_stage(name, path=None, quiet=False, **static_context):
    """Decorator form: record a whole function or method as one stage.

    Used on the ~15 operator entry points, where wrapping the body in a `with` block
    would mean re-indenting a 200-line method for no behavioural gain. Duration,
    success/failure and guard-flag counts come for free; anything wanting row counts
    calls `runlog.count(...)` from inside.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            with stage(name, path=path, quiet=quiet, **static_context):
                return fn(*args, **kwargs)
        return wrapper
    return decorator


# --- reading it back -------------------------------------------------------------------

def read_records(path=None):
    """Every stage record from one day's log. Malformed lines are skipped, not fatal."""
    target = path or log_path()
    if not os.path.exists(target):
        return []
    out = []
    with open(target, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            with guards.soft_parse("runlog.line", path=target):
                out.append(json.loads(line))
    return out


def freshness(db_path="market_intelligence.db"):
    """Question 2: max collected_at per observation table. None = the table is empty.

    If these do not move between runs, the run did nothing — which is exactly the
    silent failure this whole module exists to catch.
    """
    import sqlite3
    tables = ("trend_observations", "keyword_observations",
              "listing_observations", "listing_flaws")
    out = {}
    if not os.path.exists(db_path):
        return dict.fromkeys(tables)
    with sqlite3.connect(db_path) as conn:
        for table in tables:
            with guards.soft_parse("runlog.freshness", table=table):
                row = conn.execute(
                    f"SELECT MAX(collected_at), COUNT(*) FROM {table}").fetchone()
                out[table] = {"latest": row[0], "rows": row[1]}
    return out


def health(path=None, db_path="market_intelligence.db"):
    """Answer all five health questions from one day's log plus the database.

    Returns a dict; `print_health` renders it. Kept separate so a UI can consume the
    same numbers without scraping stdout — which is the whole point of the exercise.
    """
    records = read_records(path)
    stages = {}
    for r in records:
        # Last run of a stage wins; earlier ones stay in the file for history.
        stages[r["stage"]] = r

    guard_totals = {}
    for r in records:
        for label, count in (r.get("guard_failures") or {}).items():
            guard_totals[label] = guard_totals.get(label, 0) + count

    return {
        # 1. Did every stage complete?
        "stages": {name: {"ok": r["ok"], "duration_s": r["duration_s"],
                          "rows_out": r.get("rows_out", 0), "error": r.get("error")}
                   for name, r in stages.items()},
        "failed_stages": [n for n, r in stages.items() if not r["ok"]],
        # 2. How fresh is the freshest data?
        "freshness": freshness(db_path),
        # 3. How many rows were guard-flagged?
        "guard_failures": dict(sorted(guard_totals.items(), key=lambda kv: -kv[1])),
        # 4. What did the budget cost?
        "metered_calls": sum(r.get("metered_calls", 0) for r in records),
        "cache_hits": sum(r.get("cache_hits", 0) for r in records),
        "cache_misses": sum(r.get("cache_misses", 0) for r in records),
        # 5. Circuit breakers — no breaker exists yet, so this is honestly reported as
        #    unimplemented rather than as "none tripped", which would be a false all-clear.
        "circuit_breakers": None,
        "log_file": path or log_path(),
        "records": len(records),
    }


def print_health(path=None, db_path="market_intelligence.db"):
    h = health(path, db_path)
    print("\n=== RUN HEALTH ===")
    print(f"log: {h['log_file']} ({h['records']} stage records)\n")

    print("1. Did every stage complete?")
    if not h["stages"]:
        print("   (no stages recorded — the run never started, or used plain print())")
    for name, s in h["stages"].items():
        mark = "ok " if s["ok"] else "FAIL"
        print(f"   [{mark}] {name:<22} {s['duration_s']:>8}s  rows_out={s['rows_out']}"
              + (f"  {s['error']}" if s["error"] else ""))

    print("\n2. How fresh is the freshest data?")
    for table, info in (h["freshness"] or {}).items():
        if not info or not info.get("rows"):
            print(f"   {table:<24} EMPTY")
        else:
            print(f"   {table:<24} {info['latest']}  ({info['rows']} rows)")

    print("\n3. How many rows were guard-flagged?")
    if not h["guard_failures"]:
        print("   none")
    for label, count in h["guard_failures"].items():
        print(f"   {count:>5}x {label}")

    print("\n4. What did the budget cost?")
    total = h["cache_hits"] + h["cache_misses"]
    rate = f"{h['cache_hits'] / total:.0%}" if total else "n/a"
    print(f"   metered calls: {h['metered_calls']}   cache: "
          f"{h['cache_hits']} hit / {h['cache_misses']} miss (hit rate {rate})")

    print("\n5. Did any circuit breaker trip?")
    print("   NOT IMPLEMENTED — no breaker exists (07_gaps_and_risks.md). This is an "
          "absence of measurement, not an all-clear.")
    print()
    return h


if __name__ == "__main__":
    print_health()
