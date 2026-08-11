"""
survivorship.py

Layer: analytics/ (pure functions — no I/O, no imports from other layers)
Purpose: name the denominator. Every listing this system can see is a listing
         that survived; the ones that failed appear in no SERP and never will.

Key decision: what is computed here is a **bound**, not the survivor rate.
`BIASES_AND_BLIND_SPOTS.md` B-01 proposes "total supply vs listings with any
reviews", but that is not computable from a search page — it needs the reviewed
count across the entire population, and a SERP renders roughly 12 cards out of a
supply that is routinely tens of thousands. Worse, those 12 are the *best-ranked*
listings in the niche, so they are the most likely to have sold. Reporting their
reviewed share as "the survivor rate" would overstate it, and overstating a
survivor rate is precisely the error B-01 exists to prevent.

The asymmetry is what makes the bound useful:

    top listings mostly UNREVIEWED -> strong evidence of a graveyard. These are
                                      the listings with the best shot at selling.
                                      If they did not, the tail certainly did not.
    top listings mostly reviewed   -> tells you nothing about the tail. The
                                      winners won; the corpses are still invisible.

So a low share is a real finding and a high share is not a finding at all. The
verdict field encodes that difference so a caller cannot read "1.0" as health.

See DECISION_LOG.md D-09 (count functions, not descriptions) — this is a real
number, deliberately narrow, rather than a confident-looking rate.
"""
from dataclasses import dataclass

# Below this share of reviewed top listings, the niche is a graveyard: even the
# best-placed sellers have no sales to show.
GRAVEYARD_SHARE = 0.35
# Above this, the sample is all winners and says nothing about the tail.
UNINFORMATIVE_SHARE = 0.90
# Fewer parsed cards than this and no verdict is offered at all. A 2-card sample
# reaching "graveyard" would be noise wearing a conclusion.
MIN_SAMPLE = 5


@dataclass(frozen=True)
class SurvivorBound:
    sample_size: int          # cards whose review count could actually be read
    unparsed: int             # cards whose review count could NOT be read
    reviewed: int             # of the parsed cards, how many have >0 reviews
    reviewed_share: float     # reviewed / sample_size — None when nothing parsed
    total_supply: int         # listings competing for the query, if known
    coverage: float           # sample_size / total_supply — how little we saw
    verdict: str              # graveyard | mixed | uninformative | unmeasured
    is_upper_bound: bool      # the population share is at most reviewed_share
    note: str = ""


def survivor_bound(cards, total_supply=None):
    """Bound the share of listings in a niche that ever sold.

    Receives: the `cards` list from `EtsyPublicAPI.parse_search_html` (SERP layer)
              and `total_results` as total_supply.
    Emits: a SurvivorBound for display and for scoring.

    SURVIVORSHIP: this reflects listings that ranked. Failed listings for the same
    query are absent from any SERP and cannot be recovered at any sample size. The
    share below is therefore an upper bound on the population's, never an estimate
    of it.
    """
    parsed = [c.get("review_count") for c in cards
              if c.get("review_count") is not None]
    unparsed = len(cards) - len(parsed)

    # A card whose review count did not parse is unknown, not zero. Counting those as
    # unreviewed would manufacture a graveyard out of a scraping failure — the same
    # not-found/not-checked collapse this codebase keeps having to undo.
    if not parsed:
        return SurvivorBound(
            sample_size=0, unparsed=unparsed, reviewed=0, reviewed_share=None,
            total_supply=total_supply, coverage=None, verdict="unmeasured",
            is_upper_bound=False,
            note="no review counts could be read from this SERP — unmeasured, "
                 "which is not the same as unsold")

    reviewed = sum(1 for rc in parsed if rc > 0)
    share = reviewed / len(parsed)
    coverage = (len(parsed) / total_supply) if total_supply else None

    if len(parsed) < MIN_SAMPLE:
        verdict = "unmeasured"
        note = (f"only {len(parsed)} listing(s) could be read — too few to conclude "
                f"anything about a niche of {total_supply or 'unknown'} listings")
    elif share <= GRAVEYARD_SHARE:
        verdict = "graveyard"
        note = (f"{reviewed} of {len(parsed)} top-ranked listings have any reviews. "
                f"These are the best-ranked listings in the niche — if they have not "
                f"sold, the listings below them have not either")
    elif share >= UNINFORMATIVE_SHARE:
        verdict = "uninformative"
        note = (f"{reviewed} of {len(parsed)} top-ranked listings have reviews, which "
                f"says nothing about the tail: this sample is the winners. The failure "
                f"rate of the remaining {(total_supply - len(parsed)) if total_supply else 'unknown'} "
                f"listings is not observable")
    else:
        verdict = "mixed"
        note = (f"{reviewed} of {len(parsed)} top-ranked listings have reviews")

    return SurvivorBound(
        sample_size=len(parsed), unparsed=unparsed, reviewed=reviewed,
        reviewed_share=round(share, 6), total_supply=total_supply,
        coverage=round(coverage, 8) if coverage is not None else None,
        verdict=verdict, is_upper_bound=True, note=note)


def describe(bound):
    """One plain-language line for the UI. Never claims a rate it cannot support."""
    if bound.verdict == "unmeasured":
        return "Survivor rate: not measurable from this search."
    pct = f"{bound.reviewed_share:.0%}"
    if bound.verdict == "uninformative":
        return (f"{pct} of the top {bound.sample_size} listings have sales — but only "
                f"the winners are visible. The failure rate here is unknown.")
    if bound.verdict == "graveyard":
        return (f"Only {pct} of the top {bound.sample_size} listings have any sales. "
                f"Even the best-placed sellers here are not selling.")
    return (f"{pct} of the top {bound.sample_size} listings have sales "
            f"(survivor data only — failed listings are never visible).")
