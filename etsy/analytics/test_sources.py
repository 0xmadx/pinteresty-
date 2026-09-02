"""Offline tests for multi-door term discovery. No network, no session.

The operator asked for source selection with OR / AND and a synthesis step. The
combine rule is easy; the honest failure handling is not, and that is what most of
these pin.

THE TRAP THIS SUITE EXISTS FOR. An intersection over doors is only meaningful if
every door was asked AND answered. If Pinterest is down and the rule is "all", the
intersection quietly becomes "all the doors that happened to work" — a weaker claim
under a stronger name — and an empty result then reads as *"the doors disagree"*
when it means *"we only asked one door"*. Those are opposite conclusions about the
market, produced by the same empty list (N-02).

Run:  python -m etsy.analytics.test_sources
"""
import sys

from etsy.analytics import sources as src

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


# The measured shapes: Etsy's box returns CHILDREN, its expansion returns SIBLINGS,
# Pinterest returns its own vocabulary. `cute badge reel` is the real overlap —
# Pinterest and Etsy's expansion both know it.
SUGGEST = ["halloween badge reel nurse", "halloween badge reel cute", "badge reel funny"]
EXPAND = ["fall badge reel", "nurse badge reel", "cute badge reel", "badge reel funny"]
PINTEREST = ["badge reel ideas", "cute badge reel", "nurse badge reel"]


def main():
    print("\nunion (OR) — the widest net")
    u = src.combine({"etsy_suggest": SUGGEST, "etsy_expand": EXPAND,
                     "pinterest_prefix": PINTEREST}, mode="any")
    terms = [c["term"] for c in u["candidates"]]
    check("every term from every door survives", len(terms) == 7, terms)
    check("a term seen twice appears ONCE", terms.count("cute badge reel") == 1)
    check("provenance is kept per term",
          set(next(c for c in u["candidates"] if c["term"] == "cute badge reel")["found_by"])
          == {"etsy_expand", "pinterest_prefix"})
    check("most-corroborated sorts first",
          u["candidates"][0]["source_count"] >= u["candidates"][-1]["source_count"])
    check("and the corroboration count is reported", u["corroborated"] == 3, u["corroborated"])
    # Agreement says two populations use the word. It says NOTHING about supply.
    check("the note refuses to let agreement read as winnability",
          "not winnability" in u["note"])

    print("\nintersection (AND) and min_n")
    a = src.combine({"etsy_expand": EXPAND, "pinterest_prefix": PINTEREST}, mode="all")
    check("only terms BOTH doors returned survive",
          {c["term"] for c in a["candidates"]} == {"cute badge reel", "nurse badge reel"},
          [c["term"] for c in a["candidates"]])
    check("`all` requires as many sources as answered", a["required_sources"] == 2)
    three = src.combine({"etsy_suggest": SUGGEST, "etsy_expand": EXPAND,
                         "pinterest_prefix": PINTEREST}, mode="all")
    check("across three doors, nothing is in all three", three["candidates"] == [],
          [c["term"] for c in three["candidates"]])
    m2 = src.combine({"etsy_suggest": SUGGEST, "etsy_expand": EXPAND,
                      "pinterest_prefix": PINTEREST}, mode="min_n", min_n=2)
    check("min_n=2 finds the partially-corroborated terms",
          {c["term"] for c in m2["candidates"]} == {"badge reel funny", "cute badge reel",
                                                    "nurse badge reel"},
          [c["term"] for c in m2["candidates"]])

    print("\nA FAILED DOOR IS NOT A DISAGREEING DOOR")
    # The whole point. Union can proceed on what answered; intersection cannot,
    # because its meaning depends on who was asked.
    partial = src.combine({"etsy_suggest": SUGGEST}, mode="any",
                          failed=["pinterest_prefix"])
    check("union still returns what DID answer", len(partial["candidates"]) == 3)
    check("and names the door that did not", partial["sources_failed"] == ["pinterest_prefix"])

    refused = src.combine({"etsy_suggest": SUGGEST}, mode="all",
                          failed=["pinterest_prefix"])
    check("intersection REFUSES when a door it needed did not answer",
          refused["basis"] == "refused_incomplete_sources", refused["basis"])
    check("it returns no candidates rather than a weaker claim",
          refused["candidates"] == [])
    check("and explains that empty would have meant the opposite thing",
          "we did not ask them all" in refused["note"])
    check("min_n refuses on the same grounds",
          src.combine({"etsy_suggest": SUGGEST}, mode="min_n", min_n=2,
                      failed=["pinterest_prefix"])["basis"] == "refused_incomplete_sources")

    none = src.combine({}, mode="any", failed=["etsy_suggest", "pinterest_prefix"])
    check("every door failing is NOT 'the seed has no neighbours'",
          none["basis"] == "no_source_answered", none["basis"])
    check("...and says so in the note", "nobody answered" in none["note"])

    print("\nnormalisation and refusals")
    cased = src.combine({"a": ["Badge Reel"], "b": ["  badge  reel "]}, mode="all")
    check("case and whitespace do not defeat the intersection",
          len(cased["candidates"]) == 1, cased["candidates"])
    check("an empty door answer is answered-with-nothing, not a failure",
          src.combine({"a": [], "b": PINTEREST}, mode="any")["returned"] == 3)
    check("a bad mode is refused rather than defaulting to union",
          src.combine({"a": SUGGEST}, mode="sideways")["basis"] == "bad_mode")

    print("\ndiscover_terms — the entry point")
    # Injected fetchers: the doors are thin wrappers over clients covered elsewhere,
    # and stubbing them keeps the seller account out of this suite entirely.
    stub = {"etsy_suggest": lambda s: SUGGEST,
            "pinterest_prefix": lambda s: PINTEREST,
            "etsy_expand": lambda s: EXPAND}
    d = src.discover_terms("badge reel", sources=("etsy_suggest", "pinterest_prefix"),
                           fetchers=stub)
    check("it opens only the doors asked for", set(d["sources_ok"]) ==
          {"etsy_suggest", "pinterest_prefix"}, d["sources_ok"])
    check("per-door counts are reported", d["per_source_count"]["etsy_suggest"] == 3)
    # The operator must be able to see the price before paying it.
    check("the cost of each door is stated", "2 public requests" in str(d["cost"]))
    check("and which doors spend the SELLER account is called out separately",
          d["spends_seller_account"] == [], d["spends_seller_account"])
    check("adding etsy_expand flags the seller cost",
          src.discover_terms("x", sources=("etsy_suggest", "etsy_expand"),
                             fetchers=stub)["spends_seller_account"] == ["etsy_expand"])
    check("the default doors are the FREE ones",
          "etsy_expand" not in src.discover_terms.__defaults__[0])

    # A door that raises must be recorded as failed, never as empty.
    def boom(seed):
        raise RuntimeError("pinterest is down")

    broke = src.discover_terms("x", sources=("etsy_suggest", "pinterest_prefix"),
                               fetchers={**stub, "pinterest_prefix": boom})
    check("a raising door is recorded as FAILED, not as returning nothing",
          broke["sources_failed"] == ["pinterest_prefix"], broke["sources_failed"])
    check("and the error is kept for diagnosis", "pinterest is down" in str(broke["errors"]))
    check("a raising door forces an intersection to refuse",
          src.discover_terms("x", sources=("etsy_suggest", "pinterest_prefix"),
                             mode="all",
                             fetchers={**stub, "pinterest_prefix": boom})["basis"]
          == "refused_incomplete_sources")
    check("an unknown door is refused, not silently skipped",
          src.discover_terms("x", sources=("astrology",), fetchers=stub)["basis"]
          == "unknown_source")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
