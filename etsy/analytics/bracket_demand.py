"""Is anyone actually buying *inside* this bracket? (D-10's missing half)

`find_gaps` will not call a thin bracket an opportunity until demand is shown to
hold within it. Nothing has ever supplied that, so every bracket in this system's
history has come back `thin_but_unproven` — the honest reading, and a permanently
stuck one. This is the measurement that unsticks it.

THE SOURCE, AND WHY IT IS THE ONLY HONEST ONE
---------------------------------------------
Etsy's private API reports search volume per TERM, never per bracket. There is no
"how many people searched for gift-wrapped mugs" anywhere. So demand inside a
bracket cannot be looked up; it has to be inferred from the listings that occupy
it — and the only per-listing demand evidence the public SERP carries is the
review count.

That evidence is real but narrow, and every limit below is a reason a number here
is refused rather than reported:

**Reviews are LIFETIME, not current.** A listing with 400 reviews proves people
buy this; it does not prove they bought this month. Everything here is labelled
demand *evidence*, never a rate, and it is never multiplied into a projection.

**Only ~12 of 48 slots are server-rendered.** Every figure is a sample of the top
of page one. That is arguably the right sample — it is what a buyer sees — but it
is a sample, and it says so.

**Absent is not zero (N-02).** A card whose review count did not parse is excluded
from the median, not counted as a zero. Counting it would drag a healthy bracket
toward "nobody buys here", which is the exact wrong conclusion.

**Ads are excluded.** A paid slot is evidence someone is spending, not evidence
the bracket converts.

**A bracket too thin to sample is refused.** Two cards cannot establish a median,
and inventing one from two is how a false gap gets shipped.

WHAT MAKES A BRACKET A REAL OPPORTUNITY
---------------------------------------
Thin supply plus demand is a gap. Thin supply plus no demand is an empty cell, and
the two look identical until this runs. The discriminator is the bracket's own
listings: if the few that are there each carry substantial reviews, buyers are
transacting in an underserved bracket. If they carry none, nobody wants it.

The market baseline is reported alongside, so "these listings do better than the
market" stays checkable rather than being folded into a verdict.
"""
from statistics import median

from etsy.analytics import filter_trust

# A listing at or above this has demonstrably sold, repeatedly. Below it, the
# evidence is too thin to call demand — a single review can be a friend.
MIN_MEDIAN_REVIEWS = 5

# Fewer organic cards than this and no median is computed. Refusing is the point:
# a median of two numbers is arithmetic, not evidence.
MIN_SAMPLE = 4


def _organic_reviews(cards):
    """Review counts of the organic listings that reported one.

    Two exclusions, both deliberate: ads (evidence of spending, not of conversion)
    and cards whose count did not parse (unmeasured, and counting them as 0 would
    drag the median toward a false 'nobody buys here').
    """
    return [c["review_count"] for c in (cards or [])
            if not c.get("is_ad") and c.get("review_count") is not None]


def measure(cards, baseline_cards=None):
    """Demand evidence for one bracket, from the listings inside it.

    Returns a dict whose `demand` key is what `find_gaps` consumes: a positive
    number when demand is demonstrated, None when it is not — and None means
    UNMEASURED, never "no demand". `find_gaps` treats both as "not shown", which
    is correct, but the distinction is preserved here so a caller can tell a
    bracket nobody wants from one nobody has looked at.
    """
    reviews = _organic_reviews(cards)
    total_cards = len([c for c in (cards or []) if not c.get("is_ad")])

    if len(reviews) < MIN_SAMPLE:
        return {"demand": None, "basis": "unmeasured",
                "sample": len(reviews), "organic_cards": total_cards,
                "note": (f"only {len(reviews)} organic listing(s) reported a review "
                         f"count; {MIN_SAMPLE} are needed before a median means "
                         f"anything")}

    med = median(reviews)
    baseline = None
    if baseline_cards is not None:
        base_reviews = _organic_reviews(baseline_cards)
        if len(base_reviews) >= MIN_SAMPLE:
            baseline = median(base_reviews)

    demonstrated = med >= MIN_MEDIAN_REVIEWS
    return {
        # The gate value. A number only when demand is genuinely demonstrated, so a
        # bracket cannot become a "gap" on the strength of one review.
        "demand": med if demonstrated else None,
        "basis": "measured" if demonstrated else "insufficient",
        "median_reviews": med,
        "max_reviews": max(reviews),
        "sample": len(reviews),
        "organic_cards": total_cards,
        "market_median_reviews": baseline,
        # Reported, never folded into the verdict — "these listings outperform the
        # market" has to stay checkable.
        "vs_market": (round(med / baseline, 2) if baseline else None),
        "note": (None if demonstrated else
                 f"median of {med} review(s) is below the {MIN_MEDIAN_REVIEWS} "
                 f"needed to call demand demonstrated — thin supply here looks "
                 f"like an empty cell, not an opportunity"),
    }


def read(name, result):
    """One plain-language line about a bracket's demand evidence."""
    if result["basis"] == "untrusted_source":
        # Distinct from unmeasured: we did not fail to look, we refused to. The
        # filter returns a set that is not this bracket, so measuring it would
        # launder an untrusted count into a demand verdict.
        return f"{name}: REFUSED — {result['note']}"
    if result["basis"] == "unmeasured":
        return f"{name}: demand UNMEASURED — {result['note']}"
    if result["basis"] == "insufficient":
        return f"{name}: {result['note']}"
    vs = (f", {result['vs_market']}x the market median"
          if result.get("vs_market") else "")
    return (f"{name}: demand demonstrated — median {result['median_reviews']} "
            f"reviews across {result['sample']} listings{vs}. Lifetime reviews, "
            f"top-of-page sample.")


# --- fetching ---------------------------------------------------------------------------

def fetch(public_api, query, dimension, value, filters, baseline_cards=None):
    """Measure demand inside one bracket. One public request.

    Refuses outright when the filter behind the bracket failed the trust audit: a
    result set that is not a subset of this market cannot tell us anything about
    demand within it, and measuring it anyway would launder an untrusted count into
    a demand verdict — which is worse than the count alone, because a demand
    verdict is what turns a bracket into a launch.
    """
    if not filter_trust.bracket_is_trusted(dimension, value):
        name = filter_trust.filter_for(dimension, value)
        return {"demand": None, "basis": "untrusted_source",
                "note": (f"the '{name}' filter did not pass the trust audit, so the "
                         f"listings it returns are not this bracket's listings")}

    data = public_api.get_public_search(query, filters=filters)
    if not data:
        return {"demand": None, "basis": "unmeasured",
                "note": "the filtered search returned nothing"}
    return measure(data.get("cards"), baseline_cards)


def sweep(public_api, query, brackets):
    """Measure demand for many brackets. `brackets` maps (dimension, value) -> filters.

    The unfiltered SERP is fetched ONCE as the market baseline, so every bracket is
    compared against the same reference rather than each against its own.

    Returns ({(dimension, value): demand_or_None}, {(dimension, value): full_result}) —
    the first goes straight into `find_gaps(demand_by_bracket=...)`, the second
    carries the evidence for a report.
    """
    base = public_api.get_public_search(query) or {}
    baseline_cards = base.get("cards")

    gate, evidence = {}, {}
    for (dimension, value), filters in brackets.items():
        result = fetch(public_api, query, dimension, value, filters, baseline_cards)
        evidence[(dimension, value)] = result
        if result.get("demand"):
            gate[(dimension, value)] = result["demand"]
    return gate, evidence
