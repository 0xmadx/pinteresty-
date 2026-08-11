"""Offline tests for the survivor bound. No network, no database.

`BIASES_AND_BLIND_SPOTS.md` B-01 proposes: total supply vs listings with any reviews →
a crude survivor rate. **That number is not computable from a SERP.** It needs the
reviewed count across the whole population; a search returns roughly 12 rendered cards,
and those cards are the *best-ranked* listings in the niche.

So what is computed here is a **bound**, and the asymmetry is the whole point:

  * top listings mostly UNREVIEWED  → strong evidence the niche is a graveyard,
    because these are the listings most likely to have sold
  * top listings mostly reviewed    → says nothing at all about the tail

Run:  python -m etsy.analytics.test_survivorship
"""
import sys

from etsy.analytics.survivorship import survivor_bound

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def cards(*review_counts):
    return [{"listing_id": str(i), "review_count": rc}
            for i, rc in enumerate(review_counts)]


def main():
    # --- the informative direction: top listings are dead ---------------------------------
    s = survivor_bound(cards(0, 0, 0, 0, 0, 0, 0, 0, 2, 0), total_supply=9000)
    check("9 of 10 top listings unreviewed -> reviewed share 0.1",
          s.reviewed_share == 0.1, f"got {s.reviewed_share}")
    check("that is a graveyard verdict — the best-ranked listings have not sold",
          s.verdict == "graveyard", f"got {s.verdict}")
    check("it is labelled an upper bound on the population, not the population rate",
          s.is_upper_bound is True)
    check("the reasoning is stated, not left to the reader",
          "rank" in s.note.lower(), f"got {s.note!r}")

    # --- the uninformative direction ---------------------------------------------------------
    print()
    s = survivor_bound(cards(50, 120, 8, 300, 42, 9, 71, 15, 200, 33), total_supply=9000)
    check("every top listing reviewed -> share 1.0", s.reviewed_share == 1.0)
    check("but the verdict says UNINFORMATIVE, not 'healthy niche'",
          s.verdict == "uninformative", f"got {s.verdict}")
    check("because a 10-of-9000 sample of the winners cannot describe the losers",
          "tail" in s.note.lower(), f"got {s.note!r}")

    # --- coverage is always reported ------------------------------------------------------------
    print()
    # Stored at 8 dp — enough for a 12-of-500,000 coverage to remain legible.
    check("coverage says how little of the population was seen",
          abs(s.coverage - 10 / 9000) < 1e-8, f"got {s.coverage}")
    check("coverage survives a supply large enough to underflow a coarser rounding",
          survivor_bound(cards(*([5] * 12)), total_supply=500_000).coverage == 2.4e-05,
          f"got {survivor_bound(cards(*([5] * 12)), total_supply=500_000).coverage}")
    check("sample size and total supply are both carried",
          s.sample_size == 10 and s.total_supply == 9000)

    # --- unparsed is not zero -----------------------------------------------------------------
    print()
    # review_count None means the stars element was missing, i.e. NOT PARSED. Counting
    # those as zero-review would invent a graveyard out of a scraping failure.
    s = survivor_bound(cards(None, None, None, 5, 0), total_supply=100)
    check("unparsed cards are excluded from the denominator, not counted as unreviewed",
          s.sample_size == 2, f"got {s.sample_size}")
    check("1 of the 2 parsed cards is reviewed -> 0.5", s.reviewed_share == 0.5)
    check("the unparsed count is reported so the shrunken sample is visible",
          s.unparsed == 3, f"got {s.unparsed}")

    s = survivor_bound(cards(None, None, None), total_supply=100)
    check("all-unparsed yields no share at all — None, never 0.0",
          s.reviewed_share is None and s.verdict == "unmeasured",
          f"got {s.reviewed_share}/{s.verdict}")

    # --- degenerate inputs ------------------------------------------------------------------------
    print()
    check("no cards is unmeasured, not a graveyard",
          survivor_bound([], total_supply=100).verdict == "unmeasured")
    check("unknown total supply still yields a share, with coverage None",
          (lambda r: r.reviewed_share == 0.5 and r.coverage is None)(
              survivor_bound(cards(0, 3), total_supply=None)))
    check("zero supply does not divide by zero",
          survivor_bound(cards(0, 3), total_supply=0).coverage is None)

    # --- a sample too small to conclude from -------------------------------------------------------
    print()
    s = survivor_bound(cards(0, 0), total_supply=5000)
    check("a 2-card sample refuses a graveyard verdict — too few to conclude",
          s.verdict == "unmeasured", f"got {s.verdict}")
    check("but the observed share is still reported", s.reviewed_share == 0.0)

    # --- the mixed middle -----------------------------------------------------------------------------
    print()
    s = survivor_bound(cards(0, 0, 0, 5, 9, 0, 2, 0, 11, 0), total_supply=9000)
    check("a middling share is 'mixed', neither verdict", s.verdict == "mixed",
          f"got {s.verdict} share={s.reviewed_share}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
