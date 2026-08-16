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
    """Tags, breadcrumbs AND product type in one SERP pass.

    All three come off the same listing fetches — the pages are fetched once and every
    field that can be read from them is. Fetching the same pages again for each field
    would be the obvious waste, and all three were previously discarded from calls
    already being made.
    """
    from etsy.analytics.product_type import majority_type
    from etsy.analytics.taxonomy import category_consensus

    serp = public_api.get_public_search(term)
    if not serp or not serp.get("cards"):
        return ({"consensus_tags": [], "basis": "serp_unavailable"}, None,
                {"product_type": None, "basis": "serp_unavailable"})

    organic = [c for c in serp["cards"] if not c.get("is_ad")][:sample]
    listings, breadcrumbs, types = [], [], []
    for card in organic:
        data = public_api.get_listing_data(card["listing_id"]) or {}
        if data.get("breadcrumb"):
            breadcrumbs.append(data["breadcrumb"])
        if data.get("product_type"):
            types.append({"product_type": data["product_type"]})
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

    return consensus, category_consensus(breadcrumbs), majority_type(types)


def resolve_product_type(public_api, term, llm=None):
    """The term's product type — deterministic first (D-22), LLM only as fallback (D-27).

    Order matters and is the whole point:
      1. `majority_type` over page-one listings — measured, checkable, trusted
      2. only if that is split or thin, an LLM classification of the term string
      3. if neither is confident, None — the caller must not judge, because a wrong
         type applies the wrong margin floor

    Returns {product_type, basis} so a downstream verdict can show whether the type was
    measured or guessed.
    """
    _, _, detected = material_for_term(public_api, term)
    if detected.get("product_type"):
        return {"product_type": detected["product_type"], "basis": detected["basis"]}

    if llm is not None:
        guess = llm.classify_product_type(term)
        if guess:
            return {"product_type": guess, "basis": "llm_fallback"}

    return {"product_type": None, "basis": detected.get("basis", "undetermined")}


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
