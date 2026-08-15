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
    lines = []
    for c in candidates[:limit]:
        volume = f"{c['volume']:>8,}" if c["volume"] is not None else "       ?"
        when = ""
        if c["timing"] == "seasonal":
            when = f"  → {c['moment']} by {c['list_by']}"
            if c.get("is_late"):
                when += " ⚠️LATE"
        cats = ", ".join(dict.fromkeys(c["categories"]))[:34]
        lines.append(f"{volume}  {c['term']:<30} {cats:<36}{when}")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(prog="discover")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seasonal-only", action="store_true")
    args = parser.parse_args(argv)

    from etsy.api.private.api import EtsyPrivateAPI
    from etsy.analytics.calendar import build
    from pinterest.endpoints.api import PinterestTrendsAPI

    candidates = trending_candidates(EtsyPrivateAPI())
    with PinterestTrendsAPI() as pin:
        rows = build(pin.moments_calendar(country="US"))

    tagged = attach_moments(candidates, rows)
    if args.seasonal_only:
        tagged = [c for c in tagged if c["timing"] == "seasonal"]

    print(f"{len(tagged)} candidates — Etsy's curated trending terms, not the top of "
          f"the market by volume\n")
    print(render(tagged, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
