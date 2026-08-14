"""Offline tests for the guard boundary. No network, no database.

The behaviour that matters: a tolerated failure must still be *counted*. The old
`except Exception: pass` made a run where every parse failed print exactly what a
clean run printed.

Run:  python -m core.test_guards
"""
import sys

from core.guards import (report_failures, reset_failures, soft_parse,
                         summarise_failures, failures)

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
    # --- it still swallows, so a crawl is not aborted ------------------------------------
    box = []
    reached = False
    with soft_parse("demo.field", collector=box):
        raise ValueError("bad json")
    reached = True
    check("an exception inside the block does not propagate", reached)
    check("but it is recorded, not erased", len(box) == 1, f"got {box}")
    check("the record keeps the exception type and message",
          box[0].error_type == "ValueError" and box[0].message == "bad json")

    # --- the success path is untouched -----------------------------------------------------
    print()
    box2 = []
    out = {}
    with soft_parse("demo.ok", collector=box2):
        out["value"] = 42
    check("a block that succeeds runs to completion", out["value"] == 42)
    check("and records nothing", box2 == [])

    # --- context is carried so a failure can be located --------------------------------------
    print()
    box3 = []
    with soft_parse("listing.price", collector=box3, listing_id="1370681297"):
        raise KeyError("lowPrice")
    check("caller context is attached to the failure",
          box3[0].context == {"listing_id": "1370681297"}, f"got {box3[0].context}")

    # --- grouping ----------------------------------------------------------------------------
    print()
    box4 = []
    for i in range(3):
        with soft_parse("shop.ld_json", collector=box4):
            raise ValueError(f"attempt {i}")
    with soft_parse("shop.rating", collector=box4):
        raise TypeError("nope")
    check("failures group by label, most frequent first",
          summarise_failures(box4) == [("shop.ld_json", 3), ("shop.rating", 1)],
          f"got {summarise_failures(box4)}")
    check("report returns the total count", report_failures(box4) == 4)

    # --- a clean run prints nothing -----------------------------------------------------------
    print()
    check("report_failures on a clean run returns 0 and prints nothing",
          report_failures([]) == 0)

    # --- the module-level collector catches callers that forget one ---------------------------
    print()
    reset_failures()
    with soft_parse("no.collector.passed"):
        raise RuntimeError("still recorded")
    check("a failure is never lost just because no collector was passed",
          len(failures()) == 1, f"got {failures()}")
    reset_failures()
    check("reset clears it for the next run", failures() == [])

    # --- BaseException still escapes -----------------------------------------------------------
    print()
    try:
        with soft_parse("interrupt", collector=[]):
            raise KeyboardInterrupt()
        check("KeyboardInterrupt is NOT swallowed", False)
    except KeyboardInterrupt:
        check("KeyboardInterrupt is NOT swallowed", True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
