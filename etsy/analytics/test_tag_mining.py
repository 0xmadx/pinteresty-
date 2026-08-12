"""Offline tests for age-weighted tag mining (B-02). No network, no database.

The confound: the generator copies tags from top-ranked listings, but a listing may rank
because it is four years old with 4,000 reviews and Etsy favours tenure — not because its
tags are good. Copying its tags copies a *symptom* of ranking, not a cause.

The mitigation B-02 names: weight toward young listings that rank well. If a six-month-old
shop with 20 reviews outranks establishment, its SEO is doing real work, so its tags are
the ones worth copying.

Run:  python -m etsy.analytics.test_tag_mining
"""
import sys

from etsy.analytics.tag_mining import earned_weight, mine_consensus

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
    # --- earned_weight: young + few reviews outweighs old + many --------------------------
    young = earned_weight(review_count=20, shop_years=0)
    old = earned_weight(review_count=4000, shop_years=8)
    check("a young low-review ranker outweighs an old high-review one",
          young > old, f"young={young} old={old}")
    check("a brand-new zero-review ranker gets close to full weight",
          earned_weight(review_count=0, shop_years=0) > 0.9,
          f"got {earned_weight(0, 0)}")
    check("an established listing is discounted but never zero — its tags aren't worthless",
          0 < old < 0.3, f"got {old}")

    # Established on EITHER axis is enough to discount: a viral young shop (many reviews)
    # and a tenured quiet shop (old) both have a non-tag explanation for ranking.
    check("young but heavily reviewed is discounted (review velocity, not tags)",
          earned_weight(review_count=3000, shop_years=0) < 0.3,
          f"got {earned_weight(3000, 0)}")
    check("old but lightly reviewed is discounted (tenure, not tags)",
          earned_weight(review_count=10, shop_years=9) < 0.4,
          f"got {earned_weight(10, 9)}")

    # --- missing data is not fabricated ----------------------------------------------------
    print()
    check("both fields missing -> a neutral weight, neither favoured nor punished",
          earned_weight(None, None) == 0.5, f"got {earned_weight(None, None)}")
    check("one field present is used on its own, not discarded",
          earned_weight(review_count=0, shop_years=None) > 0.5
          and earned_weight(review_count=5000, shop_years=None) < 0.5)

    # --- mine_consensus: the young ranker's tags rise -----------------------------------------
    print()
    # Two established listings agree on generic tags; one young ranker adds a specific one.
    listings = [
        {"review_count": 5000, "shop_years": 9,
         "tags": ["gift", "necklace", "jewelry", "silver"]},
        {"review_count": 3200, "shop_years": 7,
         "tags": ["gift", "necklace", "jewelry", "present"]},
        {"review_count": 15, "shop_years": 0,
         "tags": ["gift", "necklace", "coquette bow", "silver"]},
    ]
    result = mine_consensus(listings, limit=10, min_listings=2)
    tags = result["consensus_tags"]
    check("tags appearing in only one listing are still filtered out (robustness)",
          "coquette bow" not in tags and "present" not in tags,
          f"got {tags}")
    check("among 2+ listing tags, 'silver' (shared with the young ranker) beats "
          "'jewelry' (only the old ones)",
          tags.index("silver") < tags.index("jewelry"),
          f"got {tags}")
    check("every consensus tag reports how many listings carried it",
          all(t in result["support"] for t in tags))
    check("the weighting is disclosed, not silent",
          result["weighting"] == "earned_rank_evidence")

    # --- a pool with no young rankers still works, just flags it ----------------------------------
    print()
    old_only = [
        {"review_count": 5000, "shop_years": 9, "tags": ["a", "b", "c"]},
        {"review_count": 4000, "shop_years": 8, "tags": ["a", "b", "d"]},
    ]
    r = mine_consensus(old_only, min_listings=2)
    # a and b are genuinely tied (both in 2 listings, equal weight), so their relative
    # order is arbitrary — asserting a specific one would be the N-01 error in miniature.
    check("an all-established pool returns consensus but warns the signal is confounded",
          set(r["consensus_tags"]) == {"a", "b"} and r["all_confounded"] is True,
          f"got {r}")

    # --- degenerate inputs ---------------------------------------------------------------------------
    print()
    check("no listings yields empty consensus, not a crash",
          mine_consensus([], min_listings=2)["consensus_tags"] == [])
    check("listings with no tags yields empty consensus",
          mine_consensus([{"review_count": 1, "shop_years": 1, "tags": []}],
                         min_listings=1)["consensus_tags"] == [])

    # --- string review counts (private API shape) ------------------------------------------------------
    print()
    check("a string review count like '3,456' is parsed, not treated as text",
          earned_weight(review_count="3,456", shop_years=0)
          == earned_weight(review_count=3456, shop_years=0))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
