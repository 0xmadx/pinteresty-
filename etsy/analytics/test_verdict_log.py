"""Offline checks for the verdict change log. Temp database, no network."""
import os
import tempfile

from etsy.analytics.verdict_log import (BECAME_MEASURED, BECAME_UNMEASURED,
                                        diff_inputs, explain, read, record)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    # --- what counts as a change ---------------------------------------------------------
    print()
    d = diff_inputs({"volume": 1000}, {"volume": 1001})
    check("a 0.1% move is noise, not a change — Etsy's own counts drift that much",
          d == [], d)
    d = diff_inputs({"volume": 1000}, {"volume": 1400})
    check("a 40% move is reported", len(d) == 1 and d[0]["kind"] == "moved", d)
    check("with its relative size, which is what makes it comparable",
          abs(d[0]["relative"] - 0.40) < 0.001, d[0])
    d = diff_inputs({"supply": 100, "volume": 1000},
                    {"supply": 300, "volume": 1200})
    check("changes are ranked by relative move, biggest first",
          d[0]["key"] == "supply", [x["key"] for x in d])

    # --- the distinction that matters most -------------------------------------------------
    print()
    d = diff_inputs({"volume": 5000}, {"volume": None})
    check("a value that disappeared is BECAME_UNMEASURED, not a fall to zero",
          d[0]["kind"] == BECAME_UNMEASURED, d)
    check("and it is NOT recorded as a -100% change",
          d[0]["relative"] is None and d[0]["change"] is None, d[0])
    d = diff_inputs({"volume": None}, {"volume": 5000})
    check("a newly measured value is flagged as newly measured",
          d[0]["kind"] == BECAME_MEASURED, d)
    d = diff_inputs({"a": 5000, "b": 100}, {"a": None, "b": 900})
    check("a lost measurement outranks even a 9x numeric move",
          d[0]["key"] == "a", [x["key"] for x in d])

    # --- booleans and strings are changes, not arithmetic ------------------------------------
    print()
    d = diff_inputs({"trusted": True}, {"trusted": False})
    check("a boolean flip is 'changed', never treated as a number",
          d[0]["kind"] == "changed", d)
    d = diff_inputs({"tier": "star"}, {"tier": "mid"})
    check("a string change is reported without a relative size",
          d[0]["kind"] == "changed" and d[0]["relative"] is None, d)
    check("an unchanged input is not reported at all",
          diff_inputs({"x": 1, "y": 2}, {"x": 1, "y": 2}) == [])

    # --- history and flips --------------------------------------------------------------------
    print()
    tmp = tempfile.mkdtemp()
    db = os.path.join(tmp, "v.db")

    e = explain("never-seen", db_path=db)
    check("an unrecorded subject says so rather than inventing a state",
          e["readings"] == 0 and e["flipped"] is None, e)

    record("towel", "no_go", {"volume": 2082, "supply": 149116}, db_path=db,
           collected_at="2026-08-01T00:00:00+00:00")
    e = explain("towel", db_path=db)
    check("one reading cannot show a change", e["flipped"] is None, e)
    check("and it says history cannot be backfilled",
          "backfilled" in e["note"], e["note"])

    record("towel", "go", {"volume": 4200, "supply": 149116}, db_path=db,
           collected_at="2026-08-08T00:00:00+00:00")
    e = explain("towel", db_path=db)
    check("two readings expose the flip", e["flipped"] is True, e)
    check("the flip carries its direction", e["from"] == "no_go" and e["to"] == "go", e)
    check("and only the input that moved is listed",
          [c["key"] for c in e["changes"]] == ["volume"], e["changes"])

    lines = read(e)
    check("the reading names the flip", any("flipped" in l for l in lines), lines)
    check("it refuses to attribute cause",
          any("none of them is identified as the cause" in l for l in lines), lines)

    # --- oscillation is a different problem from a trend --------------------------------------
    print()
    db2 = os.path.join(tmp, "osc.db")
    for i, v in enumerate(["go", "no_go", "go", "no_go", "go"]):
        record("flappy", v, {"volume": 1000 + i}, db_path=db2,
               collected_at=f"2026-08-0{i + 1}T00:00:00+00:00")
    lines = read(explain("flappy", db_path=db2))
    check("a verdict that alternates is called oscillating, not trending",
          any("oscillating" in l for l in lines), lines)
    check("and the operator is told to treat one reading as noise",
          any("noise" in l for l in lines), lines)

    # --- a verdict that changed with no input movement ------------------------------------------
    print()
    db3 = os.path.join(tmp, "rule.db")
    record("x", "go", {"volume": 1000}, db_path=db3, collected_at="2026-08-01T00:00:00+00:00")
    record("x", "no_go", {"volume": 1000}, db_path=db3, collected_at="2026-08-02T00:00:00+00:00")
    lines = read(explain("x", db_path=db3))
    check("if nothing moved but the verdict did, it says the RULE changed",
          any("the rule changed, not the market" in l for l in lines), lines)

    # --- holding steady ---------------------------------------------------------------------------
    print()
    db4 = os.path.join(tmp, "hold.db")
    for i in range(3):
        record("steady", "no_go", {"volume": 1000}, db_path=db4,
               collected_at=f"2026-08-0{i + 1}T00:00:00+00:00")
    lines = read(explain("steady", db_path=db4))
    check("a stable verdict reports how long it has held",
          any("held at no_go across 3 readings" in l for l in lines), lines)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
