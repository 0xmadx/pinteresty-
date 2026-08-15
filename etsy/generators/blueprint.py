"""The SEO blueprint — the last mile from "this niche is winnable" to a listing.

Everything upstream answers *what* and *when*. This answers *how do I list it*: a
title, thirteen tags, a price, the gap to exploit, and what to fix in the photos.
Copy-paste output, not a dashboard.

Built from what page-one actually does — competitor tags are fetched from live listings
(`get_listing_data` returns 13 per listing) rather than invented by a model. Nothing
here guesses a keyword.

Three things it refuses to do, all of which the naive version gets wrong:

**It will not hand you an invalid tag.** Etsy caps a tag at 20 characters. A real
page-one listing measured 2026-08-15 ranks with `first day school sign girl` — 26
characters. Etsy silently truncates or rejects; copying the winners blind loses the
tag and nobody notices. Every tag here is validated and over-long ones are reported
with what was cut.

**It will not fill all 13 slots with consensus.** Tags shared by every page-one listing
are what makes you *relevant*; they are also the most crowded ground on the term, and
copying them exactly is B-01 as a strategy — you enter where the incumbents are
strongest and have nothing they lack. The mix is deliberate and labelled.

**It will not recommend a price that loses money.** The market band is an input to the
price, not the decision. If the band's midpoint fails the margin floor, that is said
plainly rather than smoothed over.
"""
MAX_TAGS = 13            # Etsy's hard limit
MAX_TAG_CHARS = 20       # Etsy's hard limit; longer tags are rejected/truncated
MAX_TITLE_CHARS = 140

# Etsy weights the front of the title most heavily, and buyers read the first few
# words in a crowded grid. Both point the same way: lead with the exact phrase.
TITLE_LEAD_WORDS = 8


def validate_tag(tag):
    """Is this a tag Etsy will actually accept? Returns (ok, reason)."""
    if not tag or not tag.strip():
        return False, "empty"
    text = tag.strip()
    if len(text) > MAX_TAG_CHARS:
        return False, f"{len(text)} chars — Etsy's limit is {MAX_TAG_CHARS}"
    if "," in text:
        return False, "commas split tags in Etsy's editor"
    return True, None


def build_tags(term, consensus_tags, gap_phrases=(), long_tail=()):
    """Thirteen tags: relevance from consensus, findability from difference.

    `consensus_tags` should come from `tag_mining.mine_consensus` — measured off
    page-one listings, weighted toward earned rankings.

    The split is the point. All-consensus makes a listing indistinguishable from the
    incumbents on their own turf; all-difference makes it irrelevant to the query. Each
    tag carries where it came from so the operator can shift the balance.
    """
    chosen, seen, rejected = [], set(), []

    def add(tag, source):
        if len(chosen) >= MAX_TAGS:
            return
        text = (tag or "").strip().lower()
        # `seen` records every tag CONSIDERED, not only those kept. A term that is both
        # the primary phrase and a consensus tag would otherwise be judged twice and
        # appear twice in `rejected`, inflating the "N tags exceed the limit" warning
        # the operator uses to decide how much of page one is unusable.
        if not text or text in seen:
            return
        seen.add(text)
        ok, reason = validate_tag(text)
        if not ok:
            rejected.append({"tag": text, "reason": reason, "source": source})
            return
        chosen.append({"tag": text, "source": source})

    # The exact term first — it is what the demand was measured on.
    add(term, "primary")
    # Then the ground the incumbents share, so the listing is relevant at all.
    for tag in consensus_tags or []:
        add(tag, "consensus")
    # Then the differentiators: an unserved attribute is where a new listing can win.
    for phrase in gap_phrases or []:
        add(phrase, "gap")
    for phrase in long_tail or []:
        add(phrase, "long_tail")

    sources = {}
    for entry in chosen:
        sources[entry["source"]] = sources.get(entry["source"], 0) + 1

    return {
        "tags": [entry["tag"] for entry in chosen],
        "detail": chosen,
        "rejected": rejected,
        "sources": sources,
        "filled": len(chosen),
        # Under-filling is a real finding, not a formatting problem: it means there was
        # not enough measured material, and inventing filler would be the one thing
        # this module refuses to do.
        "is_complete": len(chosen) == MAX_TAGS,
    }


def build_title(term, tags, product_type=None, differentiator=None):
    """A title that leads with the phrase demand was measured on.

    Etsy weights the front of the title and buyers read the first few words in a
    crowded grid — both point the same way. Everything after the lead is secondary
    phrasing, not keyword stuffing: repeating the same words in different orders is
    what Etsy penalises and what makes a listing read as spam to a human.
    """
    lead = term.strip()
    parts = [lead[:1].upper() + lead[1:]]

    if differentiator:
        parts.append(differentiator.strip())

    # Two supporting phrases, skipping anything already contained in the lead.
    supporting = []
    lead_words = set(lead.lower().split())
    for tag in tags or []:
        if len(supporting) >= 2:
            break
        if tag == lead or set(tag.split()) <= lead_words:
            continue
        supporting.append(tag)
    parts.extend(t[:1].upper() + t[1:] for t in supporting)

    if product_type == "personalized":
        parts.append("Personalized")

    title = " | ".join(parts)[:MAX_TITLE_CHARS]
    return {
        "title": title,
        "length": len(title),
        "lead_phrase": lead,
        "reason": (f"leads with '{lead}' — the phrase the demand was measured on, and "
                   f"the words a buyer sees first in the grid"),
        "supporting": supporting,
    }


def recommend_price(price_low, price_high, verdict_for_price):
    """A price that both matches the market and clears the margin floor.

    `verdict_for_price` takes a price and returns a `profit.verdict()` dict.

    Walks the band from its midpoint upward. If nothing in the band clears the floor,
    that is reported — a listing priced to lose money is not a recommendation, and
    quietly returning the midpoint anyway is exactly how a plausible wrong number
    reaches the operator.
    """
    if price_low is None or price_high is None:
        return {"price": None, "basis": "no_price_band",
                "reason": "Etsy returned no median band — cannot price, not rejected"}

    mid = (price_low + price_high) / 2
    candidates = [round(mid, 2), round((mid + price_high) / 2, 2), round(price_high, 2)]
    for price in candidates:
        verdict = verdict_for_price(price)
        if verdict["go"]:
            return {
                "price": price,
                "basis": "measured_band_clearing_floor",
                "margin": verdict["margin"],
                "profit_per_unit": verdict["profit_per_unit"],
                "at_band_top": price >= price_high,
                "reason": (f"${price} sits in the market band ${price_low}-${price_high} "
                           f"and clears the {verdict['margin_floor']:.0%} floor"),
            }

    top = verdict_for_price(round(price_high, 2))
    return {
        "price": None,
        "basis": "band_below_floor",
        "market_band": [price_low, price_high],
        "margin_at_band_top": top["margin"],
        "reason": (f"even at the top of the market band (${price_high}) the margin is "
                   f"{top['margin']:.1%}, below the {top['margin_floor']:.0%} floor — "
                   f"this niche does not pay at market prices"),
    }


# What actually moves the click, as opposed to the impression. Tags and titles win the
# impression; these win the click, and this repo measures them least (see the
# etsy-seo-and-opportunity skill).
CTR_CHECKLIST = [
    "First photo readable at thumbnail size — Etsy's grid is small and mobile-first",
    "Price positioned against the band, not below it: undercutting reads as lower quality",
    "Show the product in use, not only on white — context is what stops the scroll",
    "Review count is social proof the photo cannot fake; early reviews compound",
]


def build(term, data, consensus, verdict_for_price, product_type=None,
          gap_phrases=(), long_tail=(), differentiator=None):
    """Assemble the blueprint. Every field carries where it came from."""
    tags = build_tags(term, consensus.get("consensus_tags") if consensus else [],
                      gap_phrases, long_tail)
    title = build_title(term, tags["tags"], product_type, differentiator)
    price = recommend_price(data.get("price_low"), data.get("price_high"),
                            verdict_for_price)

    warnings = []
    if not tags["is_complete"]:
        warnings.append(
            f"only {tags['filled']}/{MAX_TAGS} tags had measured support — the rest "
            f"would have to be invented, which this refuses to do")
    if tags["rejected"]:
        warnings.append(
            f"{len(tags['rejected'])} competitor tag(s) exceed Etsy's {MAX_TAG_CHARS}-char "
            f"limit and were dropped — copying page one blind would have lost them")
    if consensus and consensus.get("all_confounded"):
        warnings.append(
            "every source listing is confounded (established shops) — these tags may "
            "reflect shop authority rather than tag quality (B-01)")
    if tags["sources"].get("consensus", 0) >= MAX_TAGS - 1:
        warnings.append(
            "almost every tag is consensus — this lists you where incumbents are "
            "strongest with nothing they lack; add a differentiator")

    return {
        "term": term,
        "product_type": product_type,
        "title": title,
        "tags": tags,
        "price": price,
        "market": {"volume": data.get("volume"), "supply": data.get("supply"),
                   "cvr": data.get("cvr"), "wow_change": data.get("wow_change")},
        "ctr_checklist": CTR_CHECKLIST,
        "warnings": warnings,
    }


def render(bp):
    """Copy-paste output. The point of the whole module."""
    lines = [f"═══ {bp['term']}" + (f"  ({bp['product_type']})" if bp["product_type"] else ""),
             "", f"TITLE ({bp['title']['length']}/{MAX_TITLE_CHARS} chars)",
             f"  {bp['title']['title']}", f"  ↳ {bp['title']['reason']}", ""]

    tags = bp["tags"]
    lines.append(f"TAGS ({tags['filled']}/{MAX_TAGS})   " +
                 "  ".join(f"{k}:{v}" for k, v in sorted(tags["sources"].items())))
    for entry in tags["detail"]:
        lines.append(f"  {entry['tag']:<24} [{entry['source']}]")
    for bad in tags["rejected"]:
        lines.append(f"  ✗ {bad['tag']:<22} dropped — {bad['reason']}")

    price = bp["price"]
    lines.append("")
    lines.append("PRICE")
    lines.append(f"  {'$' + str(price['price']) if price['price'] else 'NO PRICE CLEARS THE FLOOR'}")
    lines.append(f"  ↳ {price['reason']}")

    market = bp["market"]
    if market["volume"]:
        lines.append("")
        lines.append(f"MARKET  {market['volume']:,} searches · {market['supply']:,} listings"
                     f" · wow {market['wow_change']}%")

    lines.append("")
    lines.append("CLICK (tags win the impression; these win the click)")
    lines.extend(f"  · {item}" for item in bp["ctr_checklist"])

    if bp["warnings"]:
        lines.append("")
        lines.append("WARNINGS")
        lines.extend(f"  ⚠️  {w}" for w in bp["warnings"])
    return "\n".join(lines)
