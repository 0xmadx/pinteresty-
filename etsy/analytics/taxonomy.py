"""Where a listing lives in Etsy's category tree — read from breadcrumbs.

`get_listing_data` returns a breadcrumb on every listing fetch and the blueprint work
discarded it. It is the listing's taxonomy path, and it answers a question the blueprint
could not: **which category should this be listed under?**

Measured live 2026-08-15 on `felt garland`, the answer is not obvious — page one splits
across two different top-level categories:

    Home & Living          → Home Decor    → Wall Decor / Seasonal Decor
    Paper & Party Supplies → Party Supplies → Party Decor → Garlands, Flags & Bunting

That split is a finding, not noise. Competitors made different deliberate choices, the
categories carry different attribute filters, and the less crowded one is a positioning
opportunity. Collapsing it to a single "winner" would hide the most useful thing in it.

It also fixes a guess. `trending-search-terms-v2` is keyed by `taxonomy_id`, and probing
15 plausible ids found only 7 populated — `Paper & Party Supplies` was never among them
because nobody knew its id. Breadcrumbs name the categories that actually exist, from
listings already being fetched.
"""
from collections import Counter

# Below this share, page one genuinely disagrees about where the product belongs.
DOMINANT_SHARE = 0.6


def category_consensus(breadcrumbs, min_sample=3):
    """Where page one files this product, and whether it agrees with itself.

    `breadcrumbs` is a list of lists — one path per listing, as returned by
    `get_listing_data`.

    Refuses on a thin sample rather than declaring a category from two listings: the
    category decides which attribute filters exist and how the listing is browsed, so a
    wrong answer is expensive and a coin-toss is not an answer.
    """
    paths = [tuple(b) for b in (breadcrumbs or []) if b]
    if len(paths) < min_sample:
        return {"primary": None, "basis": "insufficient_sample",
                "counted": len(paths), "needed": min_sample}

    tops = Counter(path[0] for path in paths)
    winner, count = tops.most_common(1)[0]
    share = count / len(paths)

    full = Counter(paths)
    best_path, best_count = full.most_common(1)[0]

    return {
        "primary": winner,
        "primary_share": round(share, 3),
        "full_path": list(best_path),
        "full_path_share": round(best_count / len(paths), 3),
        "top_levels": dict(tops),
        "counted": len(paths),
        # A split is the interesting case: two categories mean two sets of attribute
        # filters, two browse paths, and usually two crowding levels.
        "is_split": share < DOMINANT_SHARE,
        "basis": "measured",
    }


def positioning_note(consensus):
    """What the category split means for where to list. Plain language, or None."""
    if not consensus or not consensus.get("primary"):
        return None
    if not consensus["is_split"]:
        return (f"page one agrees: {consensus['primary']} "
                f"({consensus['primary_share']:.0%} of sampled listings)")

    ranked = sorted(consensus["top_levels"].items(), key=lambda kv: -kv[1])
    names = " vs ".join(f"{name} ({n})" for name, n in ranked)
    return (f"page one is split — {names}. Two categories mean two sets of attribute "
            f"filters and two browse paths; the thinner one is usually the less "
            f"crowded place to list.")


def known_categories(breadcrumbs):
    """Every category path seen, deepest first — the real tree, from real listings.

    Built by observation rather than by guessing `taxonomy_id` integers, which is how
    `Paper & Party Supplies` was missed entirely.
    """
    seen = set()
    for path in breadcrumbs or []:
        for depth in range(1, len(path) + 1):
            seen.add(tuple(path[:depth]))
    return sorted(seen, key=lambda p: (-len(p), p))


def collect_breadcrumbs(public_api, term, sample=6):
    """Breadcrumbs for the organic page-one listings of a term. Public tier (D-29).

    Ads are excluded for the same reason as in tag mining: a promoted listing bought
    its position, so its category choice is not evidence about what ranks.
    """
    serp = public_api.get_public_search(term)
    if not serp or not serp.get("cards"):
        return []
    organic = [c for c in serp["cards"] if not c.get("is_ad")][:sample]
    out = []
    for card in organic:
        data = public_api.get_listing_data(card["listing_id"]) or {}
        crumb = data.get("breadcrumb") or []
        if crumb:
            out.append(crumb)
    return out
