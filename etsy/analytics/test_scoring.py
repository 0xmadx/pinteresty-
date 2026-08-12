"""Offline tests for percentile scoring. No network, no database.

The assertions that matter most are the ones that would catch a silent regression to the
old behaviour: a raw-magnitude variable dominating the result (D-02), a missing input
being scored as zero, and a thin-margin candidate outranking a healthy one.

Run:  python -m etsy.analytics.test_scoring
"""
import sys

from etsy.analytics.profit import DIGITAL, PERSONALIZED, verdict
from etsy.analytics.scoring import (DEFAULT_WEIGHTS, MIN_POOL_SIZE, PoolTooSmall,
                                    explain, percentile_ranks, score_pool)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def score_pool_first(results, key):
    """The Scored row for `key` from a score_pool result."""
    return next(r for r in results if r.key == key)


def main():
    # --- percentile_ranks --------------------------------------------------------------
    check("percentiles: worst is 0.0 and best is 1.0",
          percentile_ranks([10, 20, 30]) == [0.0, 0.5, 1.0])
    check("percentiles: ties share the average rank",
          percentile_ranks([5, 5, 9]) == [0.25, 0.25, 1.0],
          f"got {percentile_ranks([5, 5, 9])}")
    check("percentiles: None stays None and never becomes 0.0",
          percentile_ranks([10, None, 30]) == [0.0, None, 1.0],
          f"got {percentile_ranks([10, None, 30])}")
    check("percentiles: a lone value is mid-pack, not best",
          percentile_ranks([None, 7, None]) == [None, 0.5, None])
    check("percentiles: all-missing stays all-missing",
          percentile_ranks([None, None]) == [None, None])

    # --- D-02: raw magnitude must not dominate -----------------------------------------
    print()
    # demand in the thousands, momentum on a 0-100 index. Under the old multiplicative
    # formula demand would swamp momentum purely because its numbers are bigger.
    pool = [
        {"key": "big-demand-no-momentum", "demand": 90000, "momentum": 1,
         "intent": 0.02, "profit": 10, "supply": 50000, "serp_difficulty": 90},
        {"key": "small-demand-high-momentum", "demand": 900, "momentum": 99,
         "intent": 0.05, "profit": 400, "supply": 300, "serp_difficulty": 10},
        {"key": "middling", "demand": 9000, "momentum": 50,
         "intent": 0.03, "profit": 120, "supply": 5000, "serp_difficulty": 50},
    ]
    ranked = score_pool(pool, pool_id="d02")
    check("D-02: a 100x larger demand does not dominate the score",
          ranked[0].key == "small-demand-high-momentum",
          f"winner was {ranked[0].key}")
    check("D-02: every score carries its pool id and size",
          all(r.pool_id == "d02" and r.pool_size == 3 for r in ranked))
    check("D-02: scores stay inside 0..1 regardless of input magnitude",
          all(0.0 <= r.score <= 1.0 for r in ranked),
          f"got {[r.score for r in ranked]}")

    # --- inverted dimensions ------------------------------------------------------------
    print()
    low_supply = next(r for r in ranked if r.key == "small-demand-high-momentum")
    high_supply = next(r for r in ranked if r.key == "big-demand-no-momentum")
    check("supply is inverted: less competition scores higher",
          low_supply.percentiles["supply"] > high_supply.percentiles["supply"],
          f"{low_supply.percentiles['supply']} vs {high_supply.percentiles['supply']}")
    check("serp_difficulty is inverted: weaker incumbents score higher",
          low_supply.percentiles["serp_difficulty"] > high_supply.percentiles["serp_difficulty"])

    # --- missing inputs ------------------------------------------------------------------
    print()
    sparse = [
        {"key": "complete", "demand": 100, "momentum": 50, "intent": 0.03,
         "profit": 200, "supply": 500, "serp_difficulty": 40},
        {"key": "no-momentum", "demand": 200, "intent": 0.04,
         "profit": 300, "supply": 400, "serp_difficulty": 30},
        {"key": "bare", "demand": 300},
    ]
    s = score_pool(sparse, pool_id="sparse")
    bare = next(r for r in s if r.key == "bare")
    nomo = next(r for r in s if r.key == "no-momentum")
    complete = next(r for r in s if r.key == "complete")

    check("missing: a missing dimension is reported, not silently zeroed",
          "momentum" in nomo.missing and "momentum" not in nomo.percentiles,
          f"got missing={nomo.missing}")
    check("missing: confidence falls as inputs go missing",
          complete.confidence == 1.0 and nomo.confidence < 1.0 and bare.confidence < nomo.confidence,
          f"got {complete.confidence}/{nomo.confidence}/{bare.confidence}")
    check("missing: a sparse candidate is not punished as if it scored zero",
          bare.score > 0.0, f"got {bare.score}")
    check("missing: the reason names which inputs are absent",
          any("missing input" in r for r in bare.reasons))

    # --- pool guard -----------------------------------------------------------------------
    print()
    try:
        score_pool([{"key": "a", "demand": 1}, {"key": "b", "demand": 2}], pool_id="tiny")
        check("guard: a pool below the minimum is refused, not scored", False)
    except PoolTooSmall as e:
        check("guard: a pool below the minimum is refused, not scored",
              "at least" in str(e))
    check("guard: the minimum is at least 3, since 2 gives only 0.0 and 1.0",
          MIN_POOL_SIZE >= 3)

    try:
        score_pool(sparse, weights={"nonsense": 1.0})
        check("guard: an unknown dimension raises", False)
    except ValueError:
        check("guard: an unknown dimension raises", True)

    # --- D-01: the margin floor is a gate, not a weighted term ----------------------------
    print()
    healthy = verdict(price=6.0, product_type=DIGITAL, demand_units_per_week=100)
    thin = verdict(price=45.0, product_type=PERSONALIZED, demand_units_per_week=40,
                   cogs=30.0, shipping_cost=6.0, labor_minutes=60)

    gated = score_pool([
        # The thin one is given the best raw numbers on every other dimension.
        {"key": "thin-margin", "demand": 99999, "momentum": 99, "intent": 0.09,
         "profit": thin["weekly_profit"], "supply": 10, "serp_difficulty": 1,
         "margin": thin["margin"], "margin_floor": thin["margin_floor"],
         "capacity_bound": thin["capacity_bound"]},
        {"key": "healthy", "demand": 500, "momentum": 20, "intent": 0.02,
         "profit": healthy["weekly_profit"], "supply": 5000, "serp_difficulty": 70,
         "margin": healthy["margin"], "margin_floor": healthy["margin_floor"]},
        {"key": "filler", "demand": 1000, "momentum": 30, "intent": 0.03,
         "profit": 50, "supply": 2000, "serp_difficulty": 50},
    ], pool_id="d01")

    check("D-01: a below-floor candidate is a no-go however well it scores",
          not next(r for r in gated if r.key == "thin-margin").go)
    check("D-01: a no-go never outranks a go, even with better raw inputs",
          gated[0].key != "thin-margin" and gated[-1].key == "thin-margin",
          f"order: {[r.key for r in gated]}")
    check("D-01: the no-go states which floor it missed",
          any("floor" in r for r in next(x for x in gated if x.key == "thin-margin").reasons))
    check("D-01: a capacity ceiling is surfaced rather than ignored",
          any("capacity-bound" in r
              for r in next(x for x in gated if x.key == "thin-margin").reasons))

    # --- degenerate pools: large enough to score, too small to discriminate --------------
    print()
    # These are the exact figures from the first real three-way run (digital printable /
    # physical mug / personalized sign). Each candidate leads on some dimensions and
    # trails on others, and with n=3 the only percentiles available are {0, 0.5, 1} — so
    # all three land on exactly 0.500 and the ranking carries no information. Kept as the
    # regression case because it was found by running the thing, not by reasoning about it.
    flat = score_pool([
        {"key": "digital printable", "demand": 9000, "momentum": 40, "intent": 0.021,
         "profit": 597.60, "supply": 48000, "serp_difficulty": 80},
        {"key": "physical mug", "demand": 15000, "momentum": 55, "intent": 0.028,
         "profit": 111.40, "supply": 52000, "serp_difficulty": 85},
        {"key": "personalized sign", "demand": 2200, "momentum": 88, "intent": 0.047,
         "profit": 42.00, "supply": 900, "serp_difficulty": 25},
    ], pool_id="flat")
    check("degenerate: the observed case really does collapse to the pool mean",
          all(abs(r.score - 0.5) < 1e-9 for r in flat),
          f"got {[r.score for r in flat]}")
    spread = max(r.score for r in flat) - min(r.score for r in flat)
    check("degenerate: a non-discriminating pool is detected", spread < 0.05,
          f"spread {spread}")
    check("degenerate: every result says the ranking is not discriminating",
          all(any("not discriminating" in r for r in s.reasons) for s in flat))
    check("degenerate: confidence is halved rather than left at 100%",
          all(s.confidence <= 0.5 for s in flat),
          f"got {[s.confidence for s in flat]}")

    # A structural case, not a small-n artefact: with exactly two dimensions at equal
    # weight, one normal and one inverted, a pool where demand and supply are perfectly
    # rank-correlated scores *every* candidate at 0.500 no matter how many there are.
    # That is the real-world shape — popular keywords have more listings — so scoring on
    # demand/supply alone cannot rank anything. Found by rewiring master_niche_finder,
    # which had only those two dimensions available.
    correlated = score_pool(
        [{"key": k, "demand": d, "supply": s} for k, d, s in
         [("a", 400, 100), ("b", 2200, 900), ("c", 9000, 48000),
          ("d", 15000, 52000), ("e", 30000, 90000)]],
        weights={"demand": 0.5, "supply": 0.5}, pool_id="correlated")
    check("degenerate: rank-correlated demand/supply collapses at ANY pool size",
          all(abs(r.score - 0.5) < 1e-9 for r in correlated) and len(correlated) == 5,
          f"got {[r.score for r in correlated]}")
    check("degenerate: that case is flagged too, so it cannot be mistaken for a ranking",
          all(any("not discriminating" in x for x in r.reasons) for r in correlated))

    spread_ok = max(r.score for r in ranked) - min(r.score for r in ranked)
    check("degenerate: a genuinely discriminating pool is NOT flagged",
          spread_ok >= 0.05
          and not any("not discriminating" in r for r in ranked[0].reasons),
          f"spread {spread_ok}")

    # --- interpretability -----------------------------------------------------------------
    print()
    text = explain(gated[0])
    check("explain: names the pool, size, confidence and weights version",
          "pool " in text and "confidence" in text and "weights v" in text)
    check("explain: shows each dimension's contribution",
          text.count("x weight") >= 3, f"got:\n{text}")
    check("weights: the profit term carries the largest single weight (D-01)",
          DEFAULT_WEIGHTS["profit"] == max(DEFAULT_WEIGHTS.values()))

    # --- B-10: freshness travels onto the score -------------------------------------------
    print()
    from datetime import datetime, timezone
    now = datetime(2026, 8, 11, tzinfo=timezone.utc)
    fresh, stale = "2026-08-10T00:00:00+00:00", "2026-07-01T00:00:00+00:00"

    # Two candidates identical but for the age of their supply reading.
    ft = score_pool([
        {"key": "fresh-all", "demand": 100, "momentum": 50, "intent": 0.03, "profit": 200,
         "supply": 500, "serp_difficulty": 40,
         "freshness": {"demand": fresh, "supply": fresh}},
        {"key": "stale-supply", "demand": 200, "momentum": 60, "intent": 0.04, "profit": 250,
         "supply": 400, "serp_difficulty": 30,
         "freshness": {"demand": fresh, "supply": stale}},
        {"key": "filler", "demand": 50, "momentum": 20, "intent": 0.02, "profit": 90,
         "supply": 900, "serp_difficulty": 60},
    ], pool_id="fresh", now=now)
    by = {r.key: r for r in ft}
    check("a score inherits the OLDEST timestamp among the inputs it used",
          by["stale-supply"].freshness_floor == stale,
          f"got {by['stale-supply'].freshness_floor}")
    check("an all-fresh score reads 'fresh'", by["fresh-all"].freshness == "fresh")
    check("a month-old input makes the composite 'stale', not fresh",
          by["stale-supply"].freshness == "stale", f"got {by['stale-supply'].freshness}")
    check("a stale composite has its confidence halved",
          by["stale-supply"].confidence <= 0.5, f"got {by['stale-supply'].confidence}")
    check("and says why in its reasons",
          any("stale" in r for r in by["stale-supply"].reasons))
    check("a candidate with no freshness map is 'unknown', not penalised",
          by["filler"].freshness == "unknown" and by["filler"].freshness_floor is None)

    # A stale reading for a dimension that was MISSING must not drag freshness down —
    # it did not contribute to the score.
    only_missing_stale = score_pool([
        {"key": "a", "demand": 100, "supply": 500,
         "freshness": {"demand": fresh, "momentum": stale}},  # momentum absent from score
        {"key": "b", "demand": 200, "supply": 900,
         "freshness": {"demand": fresh}},
        {"key": "c", "demand": 300, "supply": 100,
         "freshness": {"demand": fresh}},
    ], weights={"demand": 0.5, "supply": 0.5}, pool_id="mf", now=now)
    check("a stale timestamp for an unused dimension does not make the score stale",
          score_pool_first(only_missing_stale, "a").freshness == "fresh",
          f"got {score_pool_first(only_missing_stale, 'a').freshness}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
