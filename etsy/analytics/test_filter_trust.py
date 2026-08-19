"""Offline checks for the filter-trust rule. No network — every probe is a fixture."""
import os
import tempfile

from etsy.analytics.filter_trust import (IGNORED, NOT_A_SUBSET, TRUSTED, UNSTABLE,
                                         UNVERIFIED, FilterVerdict, bracket_is_trusted,
                                         classify, filter_for, load, save,
                                         trusted_names)

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
    # --- the basic contract ------------------------------------------------------------
    print()
    s, _ = classify([(10000, {"true": 2000})])
    check("a genuine subset is trusted", s == TRUSTED, s)
    s, note = classify([(10011, {"2921044": 28271})])
    check("a filter returning 282% of the market is not a subset", s == NOT_A_SUBSET, s)
    check("and the note quantifies the overshoot", "182%" in note or "%" in note, note)
    s, _ = classify([(10000, {"5": 10000})])
    check("a filter returning exactly the total was ignored", s == IGNORED, s)
    s, _ = classify([])
    check("no probes means unverified, never trusted", s == UNVERIFIED, s)

    # --- count jitter: the reason exact equality is the wrong test ----------------------
    # Measured live: identical unfiltered searches returned 217,196 / 217,196 /
    # 217,395. An ignored filter sampled a moment later lands NEAR the total, not
    # ON it, and a strict test would call that a broken filter.
    print()
    s, _ = classify([(217213, {"halloween": 217395})])
    check("a count a hair above total is jitter, not a broken filter",
          s == IGNORED, s)
    s, _ = classify([(217213, {"1": 231084})])
    check("but 6% above total is a different result set, not jitter",
          s == NOT_A_SUBSET, s)
    s, _ = classify([(1000, {"a": 1010})], jitter=0.0)
    check("with jitter disabled the same count is a hard failure",
          s == NOT_A_SUBSET, s)

    # --- the case only a SUM reveals -----------------------------------------------------
    # Every value below the total, so every per-call check passes. This is exactly
    # how locationQuery survived: four of eight countries looked reasonable.
    print()
    partition = [(1000, {"a": 400, "b": 400, "c": 400})]
    s, _ = classify(partition, exclusive=False)
    check("without exclusivity, overlapping values look fine", s == TRUSTED, s)
    s, note = classify(partition, exclusive=True)
    check("declared exclusive, the SUM exposes the overlap", s == NOT_A_SUBSET, s)
    check("and the note reports the oversum", "120%" in note, note)

    # --- cumulative brackets must not be summed -------------------------------------------
    print()
    cum = [(1000, {"7": 100, "14": 300, "21": 600, "30": 900})]
    s, _ = classify(cum, cumulative=True)
    check("cumulative brackets summing past the total are still fine",
          s == TRUSTED, s)
    s, _ = classify([(1000, {"7": 400, "14": 300, "21": 600, "30": 900})], cumulative=True)
    check("but a non-monotonic cumulative sequence is broken", s == NOT_A_SUBSET, s)

    # --- passing sometimes is not passing --------------------------------------------------
    print()
    s, _ = classify([(10000, {"1": 9285}), (1689789, {"1": 1717366})])
    check("subset on one query, superset on another -> unstable", s == UNSTABLE, s)
    check("unstable is NOT usable", not FilterVerdict("x", UNSTABLE).usable)
    check("ignored is NOT usable", not FilterVerdict("x", IGNORED).usable)
    check("unverified is NOT usable — absence of evidence is not trust",
          not FilterVerdict("x", UNVERIFIED).usable)
    check("only trusted is usable", FilterVerdict("x", TRUSTED).usable)

    # --- staleness -------------------------------------------------------------------------
    print()
    import time
    check("a never-checked verdict is stale", FilterVerdict("x", TRUSTED).stale)
    fresh = FilterVerdict("x", TRUSTED, checked_at=time.time())
    check("a just-checked verdict is fresh", not fresh.stale)
    old = FilterVerdict("x", TRUSTED, checked_at=time.time() - 200 * 86400)
    check("a verdict older than the window is stale again — Etsy changes",
          old.stale)
    check("a stale verdict does not gate as trusted",
          not bracket_is_trusted("geographic", registry={"locationQuery": old}))

    # --- round trip ---------------------------------------------------------------------------
    print()
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "reg.json")
        save({"gift_wrap": FilterVerdict("gift_wrap", TRUSTED, checked_at=time.time(),
                                         evidence=(("q", 100, {"true": 10}),))}, path)
        back = load(path)
        check("a saved verdict reloads with its status", back["gift_wrap"].status == TRUSTED)
        check("evidence survives the round trip, so the rule can be replayed",
              back["gift_wrap"].evidence[0][1] == 100, back["gift_wrap"].evidence)
        check("filters never probed load as unverified",
              back["locationQuery"].status == UNVERIFIED)
        check("trusted_names returns only the fresh, trusted ones",
              trusted_names(path) == {"gift_wrap"}, trusted_names(path))

    # --- the dimension mapping --------------------------------------------------------------
    print()
    check("geographic maps to locationQuery", filter_for("geographic") == "locationQuery")
    check("shipping_speed maps to delivery_days",
          filter_for("shipping_speed") == "delivery_days")
    check("quality resolves per value", filter_for("quality", "etsys_pick") == "best_by_etsy")
    check("an unknown quality value has no filter", filter_for("quality", "made_up") is None)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
