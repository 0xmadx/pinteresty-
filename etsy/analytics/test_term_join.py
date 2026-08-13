"""Offline tests for the Pinterest<->Etsy term join. No network, no database.

`pinterest/endpoints/overviews.md` §5 names this as THE join between the two graphs:

    term -> etsy_term | normalization | Lowercase, singularize, strip stopwords on both sides.

Without it the bridge writes "mom necklaces" and the Etsy engine looks up "mom necklace",
misses, and silently scores the candidate with no momentum — which is exactly how a free
dimension goes unused without anyone noticing.

The rule that matters most: a WRONG match is worse than no match. Joining "dog collar" to
"cat collar" would import another niche's momentum and present it as this one's.

Run:  python -m etsy.analytics.test_term_join
"""
import sys

from etsy.analytics.term_join import best_match, normalize

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
    # --- the basics --------------------------------------------------------------------
    check("lowercases", normalize("Mom Necklace") == "mom necklace")
    check("collapses whitespace", normalize("  mom   necklace ") == "mom necklace")
    check("strips punctuation", normalize("mom's necklace!") == "mom necklace")

    # --- singularisation, carefully -----------------------------------------------------
    print()
    check("plural -> singular", normalize("necklaces") == "necklace")
    check("both words singularised", normalize("Gifts Necklaces") == "gift necklace")
    # Naive "strip the s" breaks these, and a broken stem silently stops matching.
    check("'dress' is not stemmed to 'dres'", normalize("dress") == "dress",
          f"got {normalize('dress')}")
    check("'glass' survives", normalize("glass") == "glass")
    check("-ies -> -y", normalize("babies") == "baby", f"got {normalize('babies')}")
    check("-ches -> -ch", normalize("watches") == "watch", f"got {normalize('watches')}")
    check("-xes -> -x", normalize("boxes") == "box", f"got {normalize('boxes')}")
    check("short words are left alone", normalize("as") == "as")

    # --- stopwords ------------------------------------------------------------------------
    print()
    check("stopwords dropped", normalize("gifts for mom") == "gift mom",
          f"got {normalize('gifts for mom')}")
    check("word order is preserved, not sorted",
          normalize("necklace for mom") == "necklace mom")
    check("a stopword-only term does not vanish to empty",
          normalize("for the") == "for the", f"got {normalize('for the')}")

    # --- the join --------------------------------------------------------------------------
    print()
    pinterest = ["Mom Necklaces", "Coquette Bedroom Decor", "Dog Collars"]
    check("plural/case difference joins", best_match("mom necklace", pinterest) == "Mom Necklaces")
    check("stopword difference joins",
          best_match("necklaces for mom", ["Mom Necklace"]) == "Mom Necklace")
    check("returns the ORIGINAL string, not the normalised one",
          best_match("dog collar", pinterest) == "Dog Collars")

    # --- refusing a wrong match ---------------------------------------------------------------
    print()
    check("a different niche does NOT match",
          best_match("cat collar", pinterest) is None,
          f"got {best_match('cat collar', pinterest)}")
    check("an unrelated term does not match",
          best_match("wedding invitation", pinterest) is None)
    check("empty candidates yields None", best_match("mom necklace", []) is None)
    check("empty term yields None", best_match("", pinterest) is None)

    # A shared word is not a match — "necklace" alone must not claim "mom necklace".
    check("a single shared word is not enough to join",
          best_match("necklace", ["Mom Necklace"]) is None,
          f"got {best_match('necklace', ['Mom Necklace'])}")

    # --- word-order tolerance, which IS safe ---------------------------------------------------
    print()
    check("same words in a different order still join",
          best_match("necklace mom", ["Mom Necklaces"]) == "Mom Necklaces")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
