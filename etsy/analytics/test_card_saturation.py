"""Saturation from listings we can name, and the refusal when the sample is too small.

The filter audit (D-32) took away most of the gap dimensions. They are recoverable
from SERP card fields — a strictly better measurement in kind, because a card
count is something observed about listings we can name, while a filter count is a
number about a result set that may not be a subset of this market.

The trap is that recovering them FEELS like a fix and mostly is not: 6 organic
listings cannot support a saturation share. These tests exist mainly to pin the
refusal, because a share of "33%" from two hits in six is exactly the kind of
well-formed wrong number this project is named after.

    .venv/Scripts/python.exe -m etsy.analytics.test_card_saturation
"""
from etsy.analytics.card_saturation import (PREDICATES, measure, profile, read,
                                            usable_brackets, wilson)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def cards(n, **fields):
    """n identical organic cards."""
    return [dict(is_ad=False, **fields) for _ in range(n)]


def main():
    # --- the interval must be possible -------------------------------------------
    print()
    low, high = wilson(2, 6)
    check("a Wilson interval stays inside [0,1] at n=6", 0 <= low < high <= 1, (low, high))
    check("and it is WIDE there — that is the point",
          high - low > 0.5, high - low)
    l2, h2 = wilson(20, 60)
    check("ten times the sample tightens it", (h2 - l2) < (high - low) / 2, (l2, h2))
    check("0 successes does not produce a negative bound", wilson(0, 6)[0] == 0.0)
    check("all successes does not exceed 1", wilson(6, 6)[1] == 1.0)
    check("n=0 has no interval at all", wilson(0, 0) is None)

    # --- the refusal --------------------------------------------------------------
    print()
    m = measure(cards(2, star_seller=True) + cards(4, star_seller=False),
                PREDICATES[("quality", "star_seller")])
    check("the share is computed", m["share"] == 0.3333, m["share"])
    check("but at n=6 the interval spans 10%-70% and cannot place it",
          m["can_discriminate"] is False, m)
    check("and the basis says it is a sample, not a market share",
          "NOT a market share" in m["basis"])

    # THE IMPORTANT CASE. D-10's trap is reading an empty bracket as a loophole.
    # Here the statistics refuse it before any rule has to: nothing matched, and
    # the true share could still be as high as 39%.
    empty = measure(cards(6, star_seller=False), PREDICATES[("quality", "star_seller")])
    check("0 out of 6 does NOT establish an empty bracket",
          empty["can_discriminate"] is False, empty)
    check("because the true share could still be 39%",
          empty["high"] > 0.30, empty["high"])
    check("the point estimate is still reported honestly as 0%", empty["share"] == 0.0)

    big = measure(cards(40, star_seller=True) + cards(20, star_seller=False),
                  PREDICATES[("quality", "star_seller")])
    check("at n=60 the same proportion CAN discriminate",
          big["can_discriminate"] is True, big)

    # A value far from every threshold discriminates even on a small sample —
    # the rule is about the interval's position, not the sample size alone.
    clear = measure(cards(6, star_seller=True), PREDICATES[("quality", "star_seller")])
    check("6/6 is unambiguously crowded and does discriminate",
          clear["can_discriminate"] is True, clear)

    # --- absent is not false (N-02) -------------------------------------------------
    print()
    m = measure(cards(4, rating=4.9) + cards(6, rating=None),
                PREDICATES[("quality", "5_star")])
    check("listings with no rating leave the denominator, not join the misses",
          m["sample"] == 4, m)
    check("and the exclusion is reported", m["excluded_unmeasured"] == 6, m)
    none_at_all = measure(cards(5, rating=None), PREDICATES[("quality", "5_star")])
    check("a field nobody reported is unmeasured, with no share invented",
          none_at_all["sample"] == 0 and none_at_all["share"] is None, none_at_all)

    # --- ads are not the market ------------------------------------------------------
    print()
    mixed = ([dict(is_ad=True, star_seller=True) for _ in range(10)]
             + cards(4, star_seller=False))
    m = measure(mixed, PREDICATES[("quality", "star_seller")])
    check("ad slots are excluded from saturation entirely",
          m["sample"] == 4 and m["matched"] == 0, m)

    # --- the rating predicate answers what min_rating=5 pretends to -------------------
    print()
    # Etsy's min_rating=5 filter returns 4.8 and 4.9 listings. Counted here instead.
    m = measure(cards(3, rating=4.9) + cards(3, rating=5.0),
                PREDICATES[("quality", "5_star")])
    check("4.9 does not count as five stars — that is the filter's bug, not ours",
          m["matched"] == 3, m)

    # --- discount: a listing with no price history is unmeasured ----------------------
    print()
    m = measure([dict(is_ad=False, percent_discount=20, original_price=10.0),
                 dict(is_ad=False, percent_discount=None, original_price=10.0),
                 dict(is_ad=False, percent_discount=None, original_price=None)],
                PREDICATES[("discount", "true")])
    check("a listing with no pricing fields at all is excluded, not counted undiscounted",
          m["sample"] == 2 and m["matched"] == 1, m)

    # --- only discriminating brackets reach the gap analysis ---------------------------
    print()
    small = profile(cards(3, star_seller=True, free_shipping=False,
                          rating=4.2, percent_discount=None, original_price=9.0))
    usable = usable_brackets(small)
    check("brackets that cannot discriminate are withheld from find_gaps",
          ("free_shipping", "true") not in usable, usable)
    check("a share that cannot be placed against a threshold cannot classify against it",
          len(usable) < len(small), (len(usable), len(small)))

    # --- what read() always says --------------------------------------------------------
    print()
    lines = read(profile(cards(2, star_seller=True) + cards(4, star_seller=False)))
    joined = " ".join(lines)
    check("every line states the sample size", "/6" in joined, joined[:120])
    check("every line states the interval, not just the point estimate",
          "anywhere from" in joined, joined[:120])
    check("an unusable one says why", "too few listings" in joined, joined[:160])
    check("nothing is described as a market share",
          "of the market" not in joined.lower())

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
