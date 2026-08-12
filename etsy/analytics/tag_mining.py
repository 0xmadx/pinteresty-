"""
tag_mining.py

Layer: analytics/ (pure functions — no I/O, no imports from other layers)
Purpose: extract consensus tags from competitor listings, weighting toward the
         listings whose ranking is EARNED rather than inherited.

Key decision (bias B-02): the listing generator copies tags from top-ranked
competitors. But a listing may rank because it is four years old with 4,000
reviews and Etsy favours tenure — not because its tags are good. Copying its tags
copies a symptom of ranking, not a cause. A young shop with few reviews that still
ranks is the opposite: its SEO is doing real work, so its tags are the ones worth
copying.

So each listing's contribution is weighted by `earned_weight`: high when the
listing is young and lightly reviewed (ranking must be earned), low when it is old
or heavily reviewed (ranking has a non-tag explanation). Never zero — an
established listing's tags are confounded, not worthless.

This does NOT replace the robustness guard: a tag must still appear in 2+ listings
to reach consensus, so one young outlier cannot dominate. Weighting reorders the
*qualifying* tags; it does not admit unqualified ones. Trading one bias for
another (overfitting to a single new listing) would be no improvement.
"""
from collections import defaultdict

# A listing with this many reviews is half-weighted; far above it, heavily discounted.
# 100 reviews already signals an established seller whose ranking is partly bought by
# review volume rather than tag quality.
REVIEW_HALFLIFE = 100
# A shop this many years old is half-weighted on the tenure axis.
AGE_HALFLIFE = 3.0
# Established listings still contribute this much — their tags are confounded, not wrong.
FLOOR = 0.15
# The neutral weight when nothing is known about a listing's establishment.
UNKNOWN = 0.5


def _to_int(value):
    """'3,456' / '3456' / 3456 -> 3456; anything unreadable -> None. Never fabricates."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(c for c in str(value) if c.isdigit())
    return int(digits) if digits else None


def earned_weight(review_count, shop_years):
    """How much this listing's ranking is EARNED by its SEO rather than inherited.

    Decay on each axis: at zero the axis is full weight, at its halflife it is 0.5,
    asymptoting toward the floor. The two are combined with min() — established on
    *either* axis (tenure OR review volume) is a sufficient non-tag explanation for
    ranking, so the more-established axis governs.

    Missing data is neither rewarded nor punished: an axis we cannot read drops out,
    and if both are missing the weight is neutral (UNKNOWN) rather than an invented 1.0
    that would let an unmeasured listing dominate the consensus.
    """
    reviews = _to_int(review_count)
    years = shop_years if isinstance(shop_years, (int, float)) else _to_int(shop_years)

    axes = []
    if reviews is not None:
        axes.append(REVIEW_HALFLIFE / (REVIEW_HALFLIFE + max(reviews, 0)))
    if years is not None:
        axes.append(AGE_HALFLIFE / (AGE_HALFLIFE + max(years, 0)))

    if not axes:
        return UNKNOWN
    # Weakest link: discount for the axis on which the listing is most established.
    raw = min(axes)
    return round(FLOOR + (1 - FLOOR) * raw, 6)


def _is_confounded(listing):
    """True when this listing's ranking has a strong non-tag explanation."""
    return earned_weight(listing.get("review_count"),
                         listing.get("shop_years")) < 0.35


def mine_consensus(listings, limit=10, min_listings=2):
    """Consensus tags, weighted toward earned rankings.

    Receives: competitor listings, each a dict with `tags` (list) plus `review_count`
              and `shop_years` where available (public SERP cards carry both; private
              cards carry a review count only).
    Emits: {consensus_tags, support, weights_by_tag, all_confounded, weighting}.

    A tag must appear in `min_listings` distinct listings to qualify (robustness); the
    qualifying tags are then ordered by summed earned-weight, so among equally-common
    tags the ones favoured by young rankers rise.
    """
    weight_by_tag = defaultdict(float)
    support = defaultdict(int)
    any_earned = False

    for listing in listings:
        w = earned_weight(listing.get("review_count"), listing.get("shop_years"))
        if not _is_confounded(listing):
            any_earned = True
        # A listing's own duplicate tags must not inflate its support count.
        for tag in set(listing.get("tags") or []):
            weight_by_tag[tag] += w
            support[tag] += 1

    qualifying = [t for t in weight_by_tag if support[t] >= min_listings]
    # Order by earned weight, then by raw support as a stable tie-break.
    qualifying.sort(key=lambda t: (weight_by_tag[t], support[t]), reverse=True)
    consensus = qualifying[:limit]

    return {
        "consensus_tags": consensus,
        "support": {t: support[t] for t in consensus},
        "weights_by_tag": {t: round(weight_by_tag[t], 4) for t in consensus},
        # When no listing in the pool has an earned ranking, the consensus is the best
        # available but every input is confounded — the caller should say so, not present
        # these tags as validated.
        "all_confounded": bool(listings) and not any_earned,
        "weighting": "earned_rank_evidence",
    }
