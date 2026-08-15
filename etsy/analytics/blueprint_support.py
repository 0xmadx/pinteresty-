"""Fetching the raw material a blueprint is built from.

Kept separate from `blueprint.py` so that module stays pure and offline-testable — it
assembles, it does not fetch. This is the one part that touches the network.

Tags come from the listings currently ranking for the term. Verified live: the shop
grid carries no tags, but `get_listing_data` returns 13 per listing, which is exactly
Etsy's cap. Public tier only (D-29) — a competitor's listing page is public, and the
seller session must never be spent on it.
"""
DEFAULT_SAMPLE = 6


def material_for_term(public_api, term, sample=DEFAULT_SAMPLE):
    """Tags AND breadcrumbs in one SERP pass — both come off the same listing fetches.

    Kept together because fetching the page twice to read two fields off it is the
    obvious waste, and breadcrumbs were being discarded from calls already being made.
    """
    from etsy.analytics.taxonomy import category_consensus

    serp = public_api.get_public_search(term)
    if not serp or not serp.get("cards"):
        return ({"consensus_tags": [], "basis": "serp_unavailable"}, None)

    organic = [c for c in serp["cards"] if not c.get("is_ad")][:sample]
    listings, breadcrumbs = [], []
    for card in organic:
        data = public_api.get_listing_data(card["listing_id"]) or {}
        if data.get("breadcrumb"):
            breadcrumbs.append(data["breadcrumb"])
        if data.get("tags"):
            listings.append({"tags": data["tags"],
                             "review_count": card.get("review_count"),
                             "shop_years": card.get("shop_years_on_etsy")})

    from etsy.analytics.tag_mining import mine_consensus
    if listings:
        consensus = mine_consensus(listings, limit=MAX_MINED)
        consensus["sampled_listings"] = len(listings)
        consensus["basis"] = "measured"
    else:
        consensus = {"consensus_tags": [], "basis": "no_tags_parsed"}

    return consensus, category_consensus(breadcrumbs)


def consensus_for_term(public_api, term, sample=DEFAULT_SAMPLE):
    """Consensus tags from the organic page-one listings for `term`.

    Ads are excluded deliberately: a promoted listing bought its position, so its tags
    are evidence of a budget rather than of what ranks. Including them would put paid
    placement into a signal about organic search.

    Returns `mine_consensus`'s shape, or a refusal when the SERP could not be read —
    never an empty tag list dressed as consensus.
    """
    from etsy.analytics.tag_mining import mine_consensus

    serp = public_api.get_public_search(term)
    if not serp or not serp.get("cards"):
        return {"consensus_tags": [], "basis": "serp_unavailable",
                "detail": "no SERP cards returned — cannot mine tags"}

    organic = [c for c in serp["cards"] if not c.get("is_ad")][:sample]
    listings = []
    for card in organic:
        data = public_api.get_listing_data(card["listing_id"]) or {}
        tags = data.get("tags") or []
        if not tags:
            continue          # a listing whose tags did not parse is not evidence of none
        listings.append({
            "tags": tags,
            # tag_mining weights toward rankings that look EARNED rather than bought by
            # shop age, so both fields matter and both are legitimately absent sometimes.
            "review_count": card.get("review_count"),
            "shop_years": card.get("shop_years_on_etsy"),
        })

    if not listings:
        return {"consensus_tags": [], "basis": "no_tags_parsed",
                "detail": f"{len(organic)} organic listings, none yielded tags"}

    result = mine_consensus(listings, limit=MAX_MINED)
    result["sampled_listings"] = len(listings)
    result["basis"] = "measured"
    return result


# More than Etsy's 13, because over-long tags will be dropped by the blueprint's
# validator and a short list would leave slots unfilled for no reason.
MAX_MINED = 24
