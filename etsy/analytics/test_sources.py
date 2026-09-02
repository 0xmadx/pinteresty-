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

    print(chr(10) + "scout — discover, size, rank in one call")
    # Named `scout`, not `hunt`: etsy/analytics/hunt.py has existed since
    # 2026-08-25 and is a different pipeline. Pinned below.
    # Injected sizer: the sizing half is compare's, covered by its own 61 assertions.
    # What matters here is that provenance survives the join and a cut is declared.
    def fake_sizer(terms, mode="cheap"):
        ts = [t.strip() for t in terms.split(",")]
        return {"ok": True, "ranked": [{"term": ts[0], "score": 0.9}],
                "rankable": {"ok": True},
                "floors": {"min_pool_to_score": 3},
                "spent": {"private_requests_upper_bound": len(ts)},
                "rows": [{"term": t, "demand_per_listing": 0.5,
                          "verdict": "contested"} for t in ts]}

    h = src.scout("badge reel", sources=("etsy_suggest", "pinterest_prefix"),
                 fetchers=stub, sizer=fake_sizer)
    # 6, not 5: SUGGEST and PINTEREST share NOTHING — the overlap in this
    # fixture () is between EXPAND and PINTEREST, and EXPAND
    # is not one of the two doors opened here.
    check("every discovered term is sized", h["sized"] == 6, h["sized"])
    # The join that makes the table worth reading: two different questions, both
    # answered, neither collapsed into the other.
    row = next(r for r in h["rows"] if r["term"] == "cute badge reel")
    check("provenance survives the join into the sized table",
          row["found_by"] == ["pinterest_prefix"], row)
    check("and winnability rides beside it, not merged into it",
          row["verdict"] == "contested" and row["source_count"] == 1, row)
    check("the ranking comes through", h["ranked"] is not None)
    check("the seller-account cost is declared for BOTH stages",
          "compare" in h["spent"]["spends_seller_account"], h["spent"])

    # A cut is a cut. Naming the dropped terms is the difference between a slice and
    # a slice presented as the whole neighbourhood.
    cut = src.scout("badge reel", sources=("etsy_suggest", "etsy_expand",
                                          "pinterest_prefix"),
                   fetchers=stub, sizer=fake_sizer, limit=3)
    check("over the limit it sizes only the top N", cut["sized"] == 3, cut["sized"])
    check("and NAMES what it did not size, rather than counting it",
          len(cut["not_sized"]) == cut["found_total"] - 3 and cut["not_sized"],
          cut["not_sized"])
    check("the note warns the cut is by corroboration, not by merit",
          "least" in cut["note"] and "re-run" in cut["note"])
    check("least-corroborated are the ones dropped",
          all(t not in [c["term"] for c in cut["rows"][:1]] for t in cut["not_sized"]))

    # Discovery failing and discovery finding nothing are different claims, and
    # neither should spend a sizing call.
    empty = src.scout("x", sources=("etsy_suggest",),
                     fetchers={"etsy_suggest": lambda s: []}, sizer=fake_sizer)
    check("nothing discovered means nothing sized", empty["rows"] == [])
    check("...and it does not read as 'these are walls'",
          "no candidate survived discovery" in empty["note"], empty["note"])

    def broken_sizer(terms, mode="cheap"):
        return {"ok": False, "error": "SessionDown"}

    fell = src.scout("badge reel", sources=("etsy_suggest",), fetchers=stub,
                    sizer=broken_sizer)
    check("a sizing failure is NOT reported as an empty market",
          "unmeasured" in fell["note"] and "not walls" in fell["note"], fell["note"])
    check("and the sizing error is surfaced", fell["sizing_error"] == "SessionDown")


    # --- the NAME, pinned ------------------------------------------------------------
    #
    # This function shipped as `hunt` for about an hour. etsy/analytics/hunt.py has
    # existed since 2026-08-25 and is a DIFFERENT pipeline: Etsy trending terms ->
    # calendar -> profit gate -> listing blueprint, seeded from nothing. This one is
    # seeded from a term you supply and stops at a ranked table.
    #
    # Two functions with one name in one package is how a caller imports the wrong
    # thing and gets a plausible answer to a question it did not ask — which is this
    # project's whole failure mode, arriving through the import system instead of
    # through a parser.
    print(chr(10) + "the name")
    import importlib
    old = importlib.import_module("etsy.analytics.hunt")
    check("the OLDER hunt pipeline still exists and is untouched",
          hasattr(old, "main"))
    check("it is a DIFFERENT thing — seeded from trending, not from a term",
          "discover" in (old.__doc__ or "").lower(), (old.__doc__ or "")[:60])
    check("this module exposes scout, not hunt", hasattr(src, "scout"))
    check("and does NOT re-export hunt, which would restore the ambiguity",
          not hasattr(src, "hunt"))

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
