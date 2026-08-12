"""Offline tests for N-01 — the score that cannot discriminate. No network, no database.

Found by running `master_niche_finder`, not by reading it: with demand and supply at
equal weight and one inverted, a pool whose demand and supply are rank-correlated scores
**every candidate at exactly 0.500**, at any pool size. That is the normal shape of this
data — popular keywords carry more listings.

A ranking that looks meaningful and is not is the exact failure this project names as
its reason to exist, so the fix is not a louder warning. It is:

  1. `can_discriminate()` — ask BEFORE scoring whether the available dimensions could
     ever separate this pool, and refuse to call the output a ranking if not.
  2. `shortlist()` — when they cannot, select by a stated rule and label it a filter.
  3. Rank later, once the deep dive has supplied intent and profit.

Run:  python -m etsy.analytics.test_discrimination
"""
import sys

from etsy.analytics.scoring import (can_discriminate, score_pool, shortlist)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


# The real-world shape: popular keywords carry more listings, so demand and supply
# rise together. Five candidates, perfectly rank-correlated.
CORRELATED = [{"key": k, "demand": d, "supply": s} for k, d, s in
              [("a", 400, 100), ("b", 2200, 900), ("c", 9000, 48000),
               ("d", 15000, 52000), ("e", 30000, 90000)]]

DS_WEIGHTS = {"demand": 0.5, "supply": 0.5}


def main():
    # --- the diagnosis, before any scoring happens -------------------------------------
    verdict = can_discriminate(CORRELATED, DS_WEIGHTS)
    check("can_discriminate says NO on rank-correlated demand/supply",
          verdict.ok is False, f"got {verdict}")
    check("and names the reason rather than just refusing",
          "correlat" in verdict.reason.lower(), f"got {verdict.reason!r}")
    check("it names which dimensions were available",
          set(verdict.dimensions) == {"demand", "supply"}, f"got {verdict.dimensions}")

    # Confirm the underlying maths it is protecting against.
    scored = score_pool(CORRELATED, weights=DS_WEIGHTS, pool_id="correlated")
    check("the maths it predicts really does collapse to 0.500",
          all(abs(s.score - 0.5) < 1e-9 for s in scored),
          f"got {[s.score for s in scored]}")

    # --- a pool it CAN rank ---------------------------------------------------------------
    print()
    rich = [
        {"key": "a", "demand": 400, "supply": 100, "intent": 0.02, "profit": 10},
        {"key": "b", "demand": 2200, "supply": 900, "intent": 0.05, "profit": 300},
        {"key": "c", "demand": 9000, "supply": 48000, "intent": 0.01, "profit": 40},
        {"key": "d", "demand": 15000, "supply": 52000, "intent": 0.04, "profit": 220},
        {"key": "e", "demand": 30000, "supply": 90000, "intent": 0.03, "profit": 90},
    ]
    w = {"demand": 0.25, "supply": 0.25, "intent": 0.25, "profit": 0.25}
    verdict = can_discriminate(rich, w)
    check("four independent dimensions CAN discriminate", verdict.ok is True,
          f"got {verdict.reason}")
    s = score_pool(rich, weights=w, pool_id="rich")
    spread = max(x.score for x in s) - min(x.score for x in s)
    check("and the real spread confirms it", spread > 0.05, f"spread {spread}")

    # --- two dimensions that are NOT correlated are fine ------------------------------------
    print()
    uncorrelated = [{"key": k, "demand": d, "supply": s} for k, d, s in
                    [("a", 400, 90000), ("b", 2200, 52000), ("c", 9000, 900),
                     ("d", 15000, 48000), ("e", 30000, 100)]]
    check("the refusal is about correlation, not about having only two dimensions",
          can_discriminate(uncorrelated, DS_WEIGHTS).ok is True,
          f"got {can_discriminate(uncorrelated, DS_WEIGHTS).reason}")

    # --- a single dimension can always order, but says so -----------------------------------
    print()
    v = can_discriminate(CORRELATED, {"demand": 1.0})
    check("one dimension orders fine — nothing to cancel against", v.ok is True)

    # --- shortlist: an honest filter when ranking is impossible --------------------------------
    print()
    picked = shortlist(CORRELATED, limit=3)
    check("shortlist returns the requested count", len(picked) == 3, f"got {len(picked)}")
    check("it is labelled a filter, never a ranking",
          all(p.selection == "filter" for p in picked))
    check("every pick states the rule that selected it",
          all("supply" in p.reason for p in picked), f"got {[p.reason for p in picked]}")

    # The rule: prefer candidates whose supply is below the pool median, then take the
    # highest demand among them. Median supply here is 48000, so a/b/c qualify.
    check("it prefers below-median supply, then highest demand",
          [p.key for p in picked] == ["c", "b", "a"], f"got {[p.key for p in picked]}")

    # --- shortlist must not invent an order it cannot justify -------------------------------------
    print()
    flat = [{"key": k, "demand": 100, "supply": 500} for k in ("x", "y", "z")]
    picked = shortlist(flat, limit=2)
    check("an entirely tied pool still returns picks", len(picked) == 2)
    check("but every one says the order among ties is arbitrary",
          all("arbitrary" in p.reason for p in picked), f"got {[p.reason for p in picked]}")

    # --- degenerate inputs ---------------------------------------------------------------------------
    print()
    check("an empty pool shortlists to nothing", shortlist([], limit=3) == [])
    check("a limit larger than the pool returns the whole pool",
          len(shortlist(CORRELATED, limit=99)) == 5)
    check("can_discriminate on an empty pool is a refusal, not a crash",
          can_discriminate([], DS_WEIGHTS).ok is False)
    check("a pool of one cannot be discriminated",
          can_discriminate([{"key": "a", "demand": 1, "supply": 2}], DS_WEIGHTS).ok is False)

    # --- missing dimensions are not counted as available ------------------------------------------------
    print()
    sparse = [{"key": "a", "demand": 1, "supply": 2, "profit": None},
              {"key": "b", "demand": 5, "supply": 9, "profit": None},
              {"key": "c", "demand": 9, "supply": 20, "profit": None}]
    v = can_discriminate(sparse, {"demand": 0.3, "supply": 0.3, "profit": 0.4})
    check("a dimension that is None for every candidate does not count as available",
          "profit" not in v.dimensions, f"got {v.dimensions}")
    check("so a pool that looks 3-dimensional is correctly judged on its real 2",
          v.ok is False, f"got {v.reason}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
