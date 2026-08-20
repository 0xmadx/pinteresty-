"""Saturation measured from listing pages — the sample that makes it decisive.

`card_saturation` counts the same attributes from the SERP cards, at zero cost,
and is usually indecisive: only ~9 organic cards render, and a share from nine
observations has an interval wide enough to span both the thin and crowded
thresholds. Nothing about that is fixable by better arithmetic. It needs a bigger
sample.

`organic_listing_ids` now supplies one. It returned `[]` on every page for the
life of the project — a regex whose proximity constraint never held — and since
2026-08-20 returns the full ranked list, 39–51 ids. Opening those pages gives
n≈45 instead of n≈9, at one request each.

WHAT IT COSTS, STATED UP FRONT
------------------------------
One request per listing. A 40-listing sample is 40 public requests for ONE
keyword, against 1 for the card version. That is the whole trade: cheap and
usually indecisive, or expensive and usually decisive. `sample_size` is therefore
a caller's decision, never a default that quietly spends forty requests.

WHERE EACH FIELD COMES FROM, AND WHY IT MATTERS
-----------------------------------------------
The listing page carries the same attributes in two very different qualities:

  rating, reviews, price, origin   LD+JSON `Product` — structured, reliable
  star seller, free shipping       HTML markers — prose, and weaker evidence

They are labelled accordingly. A marker match is a claim that some string appeared
on the page; that is real evidence and it is not the same thing as a parsed field,
so `basis` distinguishes them and a caller can decline the weaker one.

IT IS A DIFFERENT INSTRUMENT, NOT JUST A BIGGER ONE
---------------------------------------------------
Measured live on "personalized towel": the 6-card sample put free shipping at 33%
(interval 10–70%, indecisive) and the 25-listing sample at 64% (45–80%, decisive).

It is tempting to read that as the small sample having been wrong. Be careful —
the card reads a parsed `free_shipping` field, while the page match is a prose
marker, so the two are measuring in different ways and could each be right about
something slightly different. The sample size is what makes the second decisive;
it is not proof that the first was mistaken. When they disagree this much, that
disagreement is itself the finding and belongs in the report.

THE TRAP THIS INHERITS
----------------------
`Product.aggregateRating.reviewCount` is not always the LISTING's. On some pages
it holds the SHOP's total — measured during the competitor-tracker work, where 7
of 12 listings from one shop returned 4,580 against a shop showing 4.6k. Recorded
as-is, each would have looked like a listing that gained an entire shop's review
history overnight: seven fabricated runaway winners inside the one dataset built
to be unbiased.

So a review count at or above `SHOP_TOTAL_SHARE` of the shop's own total is
REFUSED, not recorded — and refused means `None`, which is unmeasured, not zero.
"""
from etsy.analytics import card_saturation

# A listing claiming this share of its shop's entire review history is almost
# certainly reporting the shop's number, not its own.
SHOP_TOTAL_SHARE = 0.90

# Costs one request each, so it is small by default and the caller raises it
# deliberately. 40 is where the interval usually becomes decisive.
DEFAULT_SAMPLE = 12


def parse_listing(html, shop_total_reviews=None):
    """Attributes of one listing, each with the quality of its own evidence.

    Pure function — the fetch is in `sample()`, so this is testable offline against
    a saved page.
    """
    import json
    import re

    out = {"rating": None, "reviews": None, "price": None,
           "star_seller": None, "free_shipping": None,
           "rating_basis": "absent", "marker_basis": "absent"}
    if not html:
        return out

    # --- structured, and therefore trusted -------------------------------------
    m = re.search(r'"aggregateRating"\s*:\s*(\{[^}]*\})', html)
    if m:
        try:
            agg = json.loads(m.group(1))
            rating = float(agg.get("ratingValue"))
            reviews = int(agg.get("reviewCount"))
            # The shop-total contamination guard.
            if (shop_total_reviews and reviews >= shop_total_reviews * SHOP_TOTAL_SHARE):
                out["rating"] = rating
                out["reviews"] = None
                out["rating_basis"] = "refused_shop_total_contamination"
            else:
                out["rating"], out["reviews"] = rating, reviews
                out["rating_basis"] = "measured"
        except (ValueError, TypeError, KeyError):
            out["rating_basis"] = "unparseable"

    m = re.search(r'"price"\s*:\s*"?([\d.]+)', html)
    if m:
        try:
            out["price"] = float(m.group(1))
        except ValueError:
            pass

    # --- prose markers, and therefore weaker ------------------------------------
    # A match means the string appeared on the page. That is evidence, and it is
    # not a parsed field; `marker_basis` keeps the difference visible so a caller
    # can decline to use it.
    out["star_seller"] = bool(re.search(r"\bStar Seller\b", html))
    out["free_shipping"] = bool(re.search(r"\bFREE shipping\b", html, re.I))
    out["marker_basis"] = "marker"
    return out


def sample(public_api, listing_ids, sample_size=DEFAULT_SAMPLE, shop_total_reviews=None):
    """Open up to `sample_size` listings and read their attributes.

    Takes the ids in RANK ORDER rather than at random: the top of the ranking is
    what a buyer actually meets, and it is the population every saturation claim
    here is about. A random sample of all 51 would answer a different question than
    the one being asked, and answer it worse — the tail is not what competes.

    A listing that fails to fetch is skipped and counted, never recorded as an
    absence of attributes.
    """
    rows, failed = [], 0
    for listing_id in list(listing_ids)[:sample_size]:
        try:
            html = public_api.session.request(
                "GET", f"https://www.etsy.com/listing/{listing_id}",
                headers=getattr(public_api, "headers", {}), platform="etsy").text
        except Exception:
            failed += 1
            continue
        row = parse_listing(html, shop_total_reviews)
        row["listing_id"] = str(listing_id)
        # These are all organic by construction: they come from the ranked organic
        # id list, so no ad filtering is needed or possible here.
        row["is_ad"] = False
        rows.append(row)
    return rows, failed


# The attributes a listing page can support. Deliberately fewer than the card
# version: `percent_discount` is not on the page in any reliable form, so the
# discount dimension stays a card measurement rather than being faked here.
PREDICATES = {
    ("quality", "star_seller"): lambda c: c.get("star_seller"),
    ("free_shipping", "true"): lambda c: c.get("free_shipping"),
    ("quality", "5_star"): lambda c: (None if c.get("rating") is None
                                      else c["rating"] >= 4.95),
}


def profile(rows, thin=0.05, crowded=0.30):
    """Saturation across the sample, reusing the card module's interval and refusal.

    Same statistics, bigger n — which is the entire point. A share is still
    withheld when its interval straddles a threshold; the difference is that at
    n≈45 it usually does not.
    """
    return {key: card_saturation.measure(rows, pred, thin, crowded)
            for key, pred in PREDICATES.items()}


def read(rows, measured, failed=0):
    """Plain-language lines, leading with what the sample actually is."""
    out = [f"Sampled {len(rows)} listing(s) from the top of the ranking"
           + (f"; {failed} failed to fetch and are excluded" if failed else "")
           + "."]
    contaminated = sum(1 for r in rows
                       if r.get("rating_basis") == "refused_shop_total_contamination")
    if contaminated:
        out.append(f"{contaminated} listing(s) reported their SHOP's review total "
                   f"rather than their own — refused, not recorded as zero.")
    out.extend(card_saturation.read(measured))
    out.append("Star seller and free shipping are prose markers on the page, not "
               "parsed fields — weaker evidence than the ratings above.")
    return out
