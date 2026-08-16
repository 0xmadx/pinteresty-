"""DISCOVER — candidates without typing a keyword (the calendar's other half).

Until now the system dated and judged terms the operator supplied. That is a checker
with a calendar bolted on. The front door is Etsy telling *us* what is moving.

`trending-search-terms-v2` returns a category's rising terms with real search volumes,
and per its own docstring does not consume the daily quota. Verified live 2026-08-15
across a probe of 15 taxonomy ids: **only seven are populated**, four terms each.

    1     Accessories            badge reel 218k, keychain 116k, bag charm 81k
    66    Art & Collectibles     back to school 211k, needlepoint canvas 62k, fall png 44k
    199   Bath & Beauty          press on nails 218k, birthday gift 78k
    323   Books, Movies & Music
    891   Home & Living          home decor 310k, personalized gift 209k
    1429  Shoes
    1633  Weddings               wedding gifts 272k, wedding 156k

The id list is empirical, not documented — several plausible ids (Jewelry, Clothing,
Craft Supplies) returned nothing, so it is a parameter rather than a constant.

⚠️ **These are Etsy's picks, not the top terms by volume.** Etsy chose to surface them,
by criteria it does not publish. That is a selection effect of exactly the kind B-01
warns about: treating this list as "what is trending" rather than "what Etsy is
promoting" would quietly inherit someone else's agenda as market truth. Every candidate
carries `basis="etsy_curated"` so the bias travels with the data.

**Two fields that are NOT a front door, contrary to earlier notes in this repo.**
`similar_search_terms` and `market_gap_recommendations` were recorded as free unread
signals when the snake_case bug was found. Probed on `felt garland`, `mom necklace` and
`christmas ornament`, all three returned `total_results_count: 0` and a null gap block.
The keys are in the response schema; Etsy returns nothing in them. Corrected here so
nothing is built on them again.
"""
# Empirically populated top-level categories. Others returned zero terms.
TRENDING_TAXONOMIES = {
    1: "Accessories",
    66: "Art & Collectibles",
    199: "Bath & Beauty",
    323: "Books, Movies & Music",
    891: "Home & Living",
    1429: "Shoes",
    1633: "Weddings",
}


def trending_candidates(api, taxonomy_ids=None):
    """Rising terms across categories, deduped, highest volume first.

    A term appearing in two categories keeps the higher volume and records both, since
    breadth across categories is itself a signal.
    """
    taxonomy_ids = taxonomy_ids or list(TRENDING_TAXONOMIES)
    seen = {}
    for tid in taxonomy_ids:
        payload = api.get_trending_terms(taxonomy_id=tid)
        if not payload:
            continue
        category = payload.get("category_name") or TRENDING_TAXONOMIES.get(tid)
        for entry in payload.get("search_terms") or []:
            term = entry.get("search_term")
            volume = entry.get("search_volume")
            if not term:
                continue
            existing = seen.get(term)
            if existing:
                existing["categories"].append(category)
                if volume and (existing["volume"] or 0) < volume:
                    existing["volume"] = volume
                continue
            seen[term] = {
                "term": term,
                # None, not 0: a term Etsy surfaced without a volume is unmeasured,
                # and 0 would sort it last as though nobody searches it (N-02).
                "volume": volume,
                "categories": [category],
                # Etsy chose this list. It is not the top of the market by volume.
                "basis": "etsy_curated",
            }
    return sorted(seen.values(), key=lambda c: c["volume"] or -1, reverse=True)


def winnability(data):
    """Can this shop plausibly rank here? Demand per listing, and the intent behind it.

    **Market size is not opportunity.** Measured live 2026-08-15:

        home decor          310,467 searches / 2,160,627 listings = 0.14   cvr 0.00005
        backpack name tag    69,874 searches /    25,031 listings = 2.79   cvr 0.00279

    `backpack name tag` has 19x the demand per listing and 56x the conversion rate.
    Ranked by volume it sits seventeenth, under three terms this shop can never reach.

    Returns the ratio itself rather than a score. A composite number would rank the
    list just as well and tell the operator nothing about why — and "you cannot rank
    here" is a conclusion they need to be able to check.
    """
    volume, supply, cvr = data.get("volume"), data.get("supply"), data.get("cvr")
    if not volume or not supply:
        # Absent is not zero: an unsized term is unknown, and a 0 ratio would sort it
        # alongside terms measured to be hopeless (N-02).
        return {"demand_per_listing": None, "basis": "unmeasured",
                "detail": "volume or supply missing"}

    ratio = volume / supply
    # Thresholds are deliberately coarse and named, not tuned. They separate "a wall"
    # from "a chance" for a shop with no ranking authority; they are not a prediction.
    if ratio >= 1.0:
        verdict, reason = "winnable", "more searches than listings — a new listing can surface"
    elif ratio >= 0.25:
        verdict, reason = "contested", "several listings per search — possible, not easy"
    else:
        verdict, reason = "wall", f"{supply:,} listings against {volume:,} searches"

    return {
        "demand_per_listing": round(ratio, 3),
        "volume": volume,
        "supply": supply,
        "cvr": cvr,
        "verdict": verdict,
        "reason": reason,
        "basis": "measured",
    }


def rank_by_opportunity(candidates, fetch):
    """Re-rank candidates by winnability, not by market size.

    `fetch` returns parsed results-data for a term. Terms that cannot be sized keep
    their place at the end rather than being dropped — unmeasured is not hopeless.
    """
    out = []
    for candidate in candidates:
        data = fetch(candidate["term"])
        out.append({**candidate,
                    "winnability": winnability(data) if data else
                    {"demand_per_listing": None, "basis": "fetch_failed"}})
    # Sort on the ratio, then CVR as the tiebreak: of two equally crowded terms the
    # one whose searchers actually buy is the better bet.
    return sorted(
        out,
        key=lambda c: (c["winnability"]["demand_per_listing"] is not None,
                       c["winnability"].get("demand_per_listing") or 0,
                       c["winnability"].get("cvr") or 0),
        reverse=True)


def expand_seed(api, seed):
    """One seed keyword → its long-tail neighbourhood, each sized for winnability.

    Wraps `get_similar_keywords` (the LLM keyword endpoint, ~118 edges per seed) into
    the candidate shape the rest of DISCOVER uses. Each edge already carries its own
    search_volume and avg_total_listings, so winnability is computable without a second
    call per term — which is what makes recursion affordable.

    This is the answer to the narrowness of the curated front door. `trending_candidates`
    returns 28 head terms Etsy chose to promote; a single seed here returns a hundred
    long-tail terms Etsy did NOT promote, which is exactly where the winnable ground
    lives (see the etsy-seo-and-opportunity skill).

    The endpoint caches server-side: the first call for a seed computes the run, later
    calls return it in `cached_data` instantly. Combined with the local RequestCache,
    the second hunt over a seed is effectively free — the self-learning flywheel, but
    the cache is Etsy's and ours rather than something we had to build.
    """
    from etsy.api.private.api import edge_term

    edges = api.get_similar_keywords(seed)
    if not edges:
        return []
    out = []
    for edge in edges:
        term = edge_term(edge)
        if not term or term == seed:
            continue
        out.append({
            "term": term,
            "volume": edge.get("search_volume"),
            "supply": edge.get("avg_total_listings"),
            "categories": [f"expanded from '{seed}'"],
            # NOT etsy_curated: these are the algorithm's neighbours of a seed WE chose,
            # so the curation bias is ours and known, not Etsy's promotional agenda.
            "basis": "seed_expansion",
            "seed": seed,
        })
    return out


def rank_expanded(candidates):
    """Rank already-sized candidates by winnability, with no extra fetch.

    `expand_seed` edges carry their own volume and supply, so their winnability is
    computable directly — the whole point of the LLM endpoint returning metrics inline.
    A separate `fetch`-based path (`rank_by_opportunity`) exists for candidates that
    arrive unsized, like the trending front door.
    """
    out = [{**c, "winnability": winnability(c)} for c in candidates]
    return sorted(
        out,
        key=lambda c: (c["winnability"]["demand_per_listing"] is not None,
                       c["winnability"].get("demand_per_listing") or 0,
                       c["winnability"].get("cvr") or 0),
        reverse=True)


def attach_moments(candidates, calendar_rows):
    """Tag each candidate with the seasonal moment it belongs to, if any.

    This is the join that makes the front door a *calendar*: "back to school" and
    "fall png" are not merely popular, they are popular *now* and have a deadline.

    Containment on content words, most specific wins — a candidate matching no moment
    is evergreen, which is a fact about it rather than a gap in the data.
    """
    from etsy.analytics.term_join import content_words

    out = []
    for candidate in candidates:
        words = content_words(candidate["term"])
        best, best_size = None, 0
        for row in calendar_rows or []:
            needed = content_words(row.get("moment") or "")
            if needed and needed <= words and len(needed) > best_size:
                best, best_size = row, len(needed)
        out.append({
            **candidate,
            "moment": best["moment"] if best else None,
            "list_by": best["list_by"] if best else None,
            "state": best["state"] if best else None,
            "is_late": best.get("is_late") if best else None,
            # An evergreen term has no deadline. Saying so beats leaving the field
            # blank and letting a reader assume it was simply not checked.
            "timing": "seasonal" if best else "evergreen",
        })
    return out


def render(candidates, limit=20):
    icon = {"winnable": "🟢", "contested": "🟡", "wall": "🔴"}
    lines = []
    for c in candidates[:limit]:
        volume = f"{c['volume']:>8,}" if c["volume"] is not None else "       ?"
        when = ""
        if c.get("timing") == "seasonal":
            when = f"  → {c['moment']} by {c['list_by']}"
            if c.get("is_late"):
                when += " ⚠️LATE"

        win = c.get("winnability")
        if win and win.get("demand_per_listing") is not None:
            # The ratio is shown, not a score: "you cannot rank here" is a conclusion
            # the operator has to be able to check.
            head = (f"{icon[win['verdict']]} {win['demand_per_listing']:>6.2f}/listing "
                    f"cvr {win.get('cvr') or 0:.5f}")
        else:
            head = f"⚪ {'unsized':>14}          "
        lines.append(f"{head}  {volume}  {c['term']:<28}{when}")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(prog="discover")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seasonal-only", action="store_true")
    parser.add_argument("--by-volume", action="store_true",
                        help="rank by market size instead of winnability (rarely useful)")
    args = parser.parse_args(argv)

    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.analytics.calendar import build
    from pinterest.endpoints.api import PinterestTrendsAPI

    api = EtsyPrivateAPI()
    candidates = trending_candidates(api)
    with PinterestTrendsAPI() as pin:
        rows = build(pin.moments_calendar(country="US"))

    tagged = attach_moments(candidates, rows)
    if args.seasonal_only:
        tagged = [c for c in tagged if c["timing"] == "seasonal"]

    if not args.by_volume:
        def fetch(term):
            raw = api.get_results_data(term)
            return parse_results_data(raw) if raw else None
        tagged = rank_by_opportunity(tagged[:args.limit], fetch)

    print(f"{len(tagged)} candidates — Etsy's curated picks, not the top of the market. "
          f"Ranked by {'volume' if args.by_volume else 'winnability'}.\n")
    print(render(tagged, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
