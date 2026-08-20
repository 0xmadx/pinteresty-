"""D-10's missing half: is anyone buying INSIDE this bracket?

Every bracket in this system's history has returned `thin_but_unproven`, because
nothing ever supplied demand-inside-a-bracket and `find_gaps` refuses to call a
gap without it. That refusal is correct. These tests cover the measurement that
lets it finally pass — and, more importantly, the cases where it must still refuse.

The failure this guards against is the original trap, stated in D-10: reading a 0%
bracket as a loophole. A demand number invented from two listings, or from cards
whose review counts never parsed, would turn "nobody wants this" into "nobody has
filled this" — a launch recommendation built on an absence.

    .venv/Scripts/python.exe -m etsy.analytics.test_bracket_demand
"""
from etsy.analytics.bracket_demand import (MIN_MEDIAN_REVIEWS, MIN_SAMPLE, measure,
                                           read)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def cards(reviews, ads=0, unparsed=0):
    out = [{"review_count": r, "is_ad": False} for r in reviews]
    out += [{"review_count": 900, "is_ad": True} for _ in range(ads)]
    out += [{"review_count": None, "is_ad": False} for _ in range(unparsed)]
    return out


def main():
    # --- demand demonstrated ------------------------------------------------------
    print()
    r = measure(cards([40, 120, 65, 88, 210]))
    check("a bracket whose listings carry real reviews shows demand",
          r["demand"] == 88, r)
    check("the basis says measured", r["basis"] == "measured", r["basis"])
    check("the median is reported, not just the verdict", r["median_reviews"] == 88)

    # --- thin supply with NO demand is the empty cell, not a gap -------------------
    # This is the trap D-10 exists for: 0% saturation read as a loophole.
    print()
    r = measure(cards([0, 1, 0, 2, 1]))
    check("listings with almost no reviews do NOT demonstrate demand",
          r["demand"] is None, r)
    check("and it is 'insufficient', distinct from never having looked",
          r["basis"] == "insufficient", r["basis"])
    check("the reason names the threshold it missed",
          str(MIN_MEDIAN_REVIEWS) in r["note"], r["note"])
    check("the median is still reported so the operator can see how close it was",
          r["median_reviews"] == 1, r)

    # --- a sample too small to mean anything --------------------------------------
    print()
    r = measure(cards([400, 500]))
    check("two listings cannot establish a median, however large",
          r["demand"] is None, r)
    check("and that is UNMEASURED, not 'no demand'",
          r["basis"] == "unmeasured", r["basis"])
    check("even though both listings are clearly selling well",
          r["sample"] == 2, r)
    check("the note names how many are needed", str(MIN_SAMPLE) in r["note"], r["note"])

    # --- absent is not zero (N-02) -------------------------------------------------
    # Counting unparsed cards as 0 would drag a healthy bracket to "nobody buys here".
    print()
    r = measure(cards([50, 60, 70, 80], unparsed=6))
    check("cards with no review count are EXCLUDED, not counted as zero",
          r["demand"] == 65, r)
    check("the sample reports only what was actually read", r["sample"] == 4, r)
    check("but the organic card count includes them, so the gap is visible",
          r["organic_cards"] == 10, r)

    all_unparsed = measure(cards([], unparsed=8))
    check("a bracket where NO count parsed is unmeasured, never empty",
          all_unparsed["demand"] is None and all_unparsed["basis"] == "unmeasured",
          all_unparsed)

    # --- ads prove spending, not conversion ----------------------------------------
    print()
    r = measure(cards([1, 0, 2, 1], ads=6))
    check("ad slots are excluded from the demand median",
          r["demand"] is None and r["median_reviews"] == 1, r)
    check("six high-review ads cannot rescue a bracket nobody buys in",
          r["sample"] == 4, r)

    # --- the market baseline is reported, never folded into the verdict -------------
    print()
    r = measure(cards([200, 220, 240, 260]), baseline_cards=cards([20, 22, 24, 26]))
    check("the market median is carried alongside", r["market_median_reviews"] == 23, r)
    check("and the ratio is exposed so the claim stays checkable",
          r["vs_market"] == 10.0, r["vs_market"])
    check("but the verdict does not depend on beating the market",
          measure(cards([200, 220, 240, 260]))["demand"] == 230)

    weak = measure(cards([1, 1, 2, 2]), baseline_cards=cards([100, 100, 100, 100]))
    check("underperforming the market does not by itself deny demand — the "
          "absolute floor does",
          weak["demand"] is None and weak["basis"] == "insufficient", weak)

    tiny_base = measure(cards([50, 60, 70, 80]), baseline_cards=cards([5, 5]))
    check("a baseline too small to trust is dropped, not used anyway",
          tiny_base["market_median_reviews"] is None, tiny_base)
    check("and the bracket verdict survives without it",
          tiny_base["demand"] == 65, tiny_base)

    # --- what read() will and will not say -----------------------------------------
    print()
    line = read("gift_wrap=true", measure(cards([40, 120, 65, 88])))
    check("a demonstrated bracket says so, and says reviews are LIFETIME",
          "demand demonstrated" in line and "Lifetime" in line, line)
    check("and that it is a top-of-page sample", "sample" in line, line)
    line = read("gift_wrap=true", measure(cards([400, 500])))
    check("an unmeasured bracket says UNMEASURED, not 'no demand'",
          "UNMEASURED" in line, line)

    # --- an untrusted filter is REFUSED, which is not the same as unmeasured ------
    # We did not fail to look; we declined to. Measuring a result set that is not
    # this bracket would launder an untrusted count into a demand verdict, and a
    # demand verdict is what turns a bracket into a launch.
    print()
    untrusted = {"demand": None, "basis": "untrusted_source",
                 "note": "the 'locationQuery' filter did not pass the trust audit"}
    line = read("geographic=China", untrusted)
    check("an untrusted bracket reads as REFUSED", "REFUSED" in line, line)
    check("and read() does not crash on a result with no median",
          "median" not in line, line)

    # --- an empty bracket ------------------------------------------------------------
    print()
    r = measure([])
    check("no cards at all is unmeasured", r["basis"] == "unmeasured", r)
    check("and reports zero organic cards honestly", r["organic_cards"] == 0)
    check("None cards does not crash", measure(None)["demand"] is None)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
