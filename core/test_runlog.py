"""Offline tests for structured run logging. No network; a temp file for the log.

What matters here is that the five health questions in MIGRATION_AND_OPERATIONS.md:118-128
get *answers*, and that a stage which fails is recorded as failed rather than vanishing.

Run:  python -m core.test_runlog
"""
import json
import os
import sys
import tempfile

from core import guards, runlog
from core.runlog import (current_stage, health, logged_stage, read_records, stage,
                         write_record)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    tmp = tempfile.mkdtemp()
    log = os.path.join(tmp, "run.jsonl")

    # --- a successful stage -----------------------------------------------------------
    with stage("discover", path=log, quiet=True, seed="mom necklace") as st:
        st.count(rows_out=42, cache_hits=10, metered_calls=2)
        st.note("crawled 2 levels")

    recs = read_records(log)
    check("one stage writes exactly one JSON line", len(recs) == 1, f"got {len(recs)}")
    r = recs[0]
    check("the record names the stage", r["stage"] == "discover")
    check("it is marked ok", r["ok"] is True)
    check("counters are carried", r["rows_out"] == 42 and r["metered_calls"] == 2)
    check("caller context is carried", r["seed"] == "mom necklace")
    check("notes are carried", r["notes"] == ["crawled 2 levels"])
    check("a duration is recorded", isinstance(r["duration_s"], float))
    check("started and finished timestamps exist", r["started"] and r["finished"])

    # --- unknown counters are refused rather than silently dropped ----------------------
    print()
    try:
        with stage("bad", path=log, quiet=True) as st:
            st.count(widgets=3)
        check("an unknown counter raises", False)
    except ValueError:
        check("an unknown counter raises", True)

    # --- a failing stage is recorded AND re-raised ---------------------------------------
    print()
    raised = False
    try:
        with stage("crashy", path=log, quiet=True):
            raise RuntimeError("upstream 500")
    except RuntimeError:
        raised = True
    check("an exception in a stage propagates — a crashed stage must crash", raised)

    crashed = [x for x in read_records(log) if x["stage"] == "crashy"][0]
    check("the failed stage is recorded, not lost", crashed["ok"] is False)
    check("and it says why", "upstream 500" in crashed["error"])
    check("and it counts as an error", crashed["errors"] == 1)

    # --- guard failures are captured per stage --------------------------------------------
    print()
    with stage("parsey", path=log, quiet=True):
        for _ in range(3):
            with guards.soft_parse("shop.ld_json"):
                raise ValueError("markup changed")

    parsey = [x for x in read_records(log) if x["stage"] == "parsey"][0]
    check("guard failures land in the stage record",
          parsey["guard_failures"] == {"shop.ld_json": 3}, f"got {parsey['guard_failures']}")
    check("and are totalled", parsey["guard_failure_total"] == 3)

    # A later stage must not inherit them.
    with stage("clean", path=log, quiet=True):
        pass
    clean = [x for x in read_records(log) if x["stage"] == "clean"][0]
    check("a stage resets guard counts on entry, so counts are per-stage",
          clean["guard_failure_total"] == 0, f"got {clean['guard_failures']}")

    # --- reset=False carries failures accumulated outside the block ------------------------
    print()
    guards.reset_failures()
    with guards.soft_parse("outside.the.block"):
        raise ValueError("happened in a loop")
    with stage("after_loop", path=log, quiet=True, reset=False):
        pass
    after = [x for x in read_records(log) if x["stage"] == "after_loop"][0]
    check("reset=False captures failures from work done before the block",
          after["guard_failures"] == {"outside.the.block": 1},
          f"got {after['guard_failures']}")
    guards.reset_failures()

    # --- the five health questions get answers ---------------------------------------------
    print()
    h = health(path=log, db_path=os.path.join(tmp, "nonexistent.db"))
    check("Q1: every stage is listed with its outcome",
          set(h["stages"]) >= {"discover", "crashy", "parsey"}, f"got {list(h['stages'])}")
    # Both "crashy" and "bad" failed — "bad" because the unknown-counter ValueError
    # propagated through its block, which is the intended behaviour on both counts.
    check("Q1: failed stages are named explicitly",
          sorted(h["failed_stages"]) == ["bad", "crashy"], f"got {h['failed_stages']}")
    check("Q1: a stage that raised on a bad counter is recorded as failed too",
          h["stages"]["bad"]["ok"] is False)
    check("Q2: freshness reports every observation table",
          set(h["freshness"]) == {"trend_observations", "keyword_observations",
                                  "listing_observations", "listing_flaws"},
          f"got {h['freshness']}")
    check("Q2: a missing database yields None per table, not a crash",
          all(v is None for v in h["freshness"].values()))
    check("Q3: guard failures are aggregated across the run",
          h["guard_failures"].get("shop.ld_json") == 3, f"got {h['guard_failures']}")
    check("Q4: budget totals are summed across stages",
          h["metered_calls"] == 2 and h["cache_hits"] == 10,
          f"metered={h['metered_calls']} hits={h['cache_hits']}")
    check("Q5: circuit breakers report None (unimplemented), NOT 'none tripped'",
          h["circuit_breakers"] is None)

    # --- robustness --------------------------------------------------------------------------
    print()
    with open(log, "a", encoding="utf-8") as f:
        f.write("this is not json\n")
    check("a malformed line is skipped, not fatal", len(read_records(log)) >= 5)
    check("reading a log that does not exist returns empty",
          read_records(os.path.join(tmp, "missing.jsonl")) == [])

    # --- the log is append-only ----------------------------------------------------------------
    print()
    before = len(read_records(log))
    write_record({"stage": "extra", "ok": True}, path=log)
    check("writing appends rather than replacing", len(read_records(log)) == before + 1)

    # --- the decorator form, used on the ~15 operator entry points -----------------------------
    print()
    log2 = os.path.join(tmp, "dec.jsonl")

    class Pipeline:
        @logged_stage("demo_pipeline", path=log2, quiet=True)
        def run(self, n):
            # Deep code contributes counts without the stage being threaded through.
            self._inner(n)
            return "done"

        def _inner(self, n):
            runlog.count(rows_out=n)

    check("the decorator returns the wrapped function's value",
          Pipeline().run(7) == "done")
    d = read_records(log2)[0]
    check("the decorator writes a stage record", d["stage"] == "demo_pipeline")
    check("runlog.count() from nested code reaches the running stage",
          d["rows_out"] == 7, f"got {d['rows_out']}")
    check("the decorator preserves the function name",
          Pipeline.run.__name__ == "run")

    # A failure inside a decorated method is still recorded and still raised.
    class Broken:
        @logged_stage("broken_pipeline", path=log2, quiet=True)
        def run(self):
            raise KeyError("missing field")

    try:
        Broken().run()
        check("a decorated stage still raises on failure", False)
    except KeyError:
        check("a decorated stage still raises on failure", True)
    b = [x for x in read_records(log2) if x["stage"] == "broken_pipeline"][0]
    check("and is recorded as failed", b["ok"] is False and "missing field" in b["error"])

    # --- count() outside any stage is a no-op, not a crash --------------------------------------
    print()
    check("current_stage() is None outside a stage", current_stage() is None)
    runlog.count(rows_out=99)   # must not raise
    check("count() outside a stage is a harmless no-op", current_stage() is None)

    # --- nesting: a guard failure belongs to exactly ONE stage ------------------------------------
    print()
    # This mirrors master_arbitrage -> master_niche_finder. Before the exit-reset, the
    # inner stage's failure was also counted by the outer one and health() reported it
    # twice.
    log3 = os.path.join(tmp, "nested.jsonl")
    guards.reset_failures()

    class Nested:
        @logged_stage("inner", path=log3, quiet=True)
        def run(self):
            with guards.soft_parse("inner.parse"):
                raise ValueError("inner failed")

    with stage("outer", path=log3, quiet=True):
        with guards.soft_parse("outer.before"):
            raise_ = ValueError("outer, before the child")
            raise raise_
    # (the outer block above exits via the guard, not an exception — soft_parse ate it)

    with stage("outer2", path=log3, quiet=True):
        Nested().run()

    recs3 = {r["stage"]: r for r in read_records(log3)}
    check("the inner stage owns its own failure",
          recs3["inner"]["guard_failures"] == {"inner.parse": 1},
          f"got {recs3['inner']['guard_failures']}")
    check("the parent does NOT double-count the child's failure",
          recs3["outer2"]["guard_failure_total"] == 0,
          f"got {recs3['outer2']['guard_failures']}")
    check("a failure before any child still belongs to the parent",
          recs3["outer"]["guard_failures"] == {"outer.before": 1},
          f"got {recs3['outer']['guard_failures']}")

    h3 = health(path=log3, db_path=os.path.join(tmp, "nonexistent.db"))
    check("so health() counts each guard failure exactly once",
          h3["guard_failures"] == {"inner.parse": 1, "outer.before": 1},
          f"got {h3['guard_failures']}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
