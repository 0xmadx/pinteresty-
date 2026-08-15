"""Is this listing digital, physical, or personalized? (D-22)

Mandatory rather than decorative, because the type changes three things at once:

  * which gap dimensions are even askable — a download has no delivery window
  * which margin floor applies — 0.70 digital / 0.35 physical / 0.50 personalized
  * whether the binding constraint is demand or the operator's hands

A wrong type therefore produces a confident wrong verdict in all three at once.

**This is read off the page, not guessed by a model.** The build plan assumed a single
`is_digital` field would answer it; probing the wire on 2026-08-15 found no such field
anywhere in the public listing HTML. What does exist is structured and cleanly
separating:

    listing                     "Digital download"   personalization field
    printable wall art                  19                     0
    personalized t-shirt                 0                     3
    felt garland                         0                     0

So detection is deterministic. The LLM stays where D-27 put it — available for a
genuinely ambiguous title, never for a number, and never overriding the page.
"""
import re

DIGITAL = "digital"
PHYSICAL = "physical"
PERSONALIZED = "personalized"

# A personalization form field is rendered only when the seller enabled personalization.
_PERSONALIZATION = re.compile(r'id="personalization', re.IGNORECASE)
_DIGITAL = re.compile(r'[Dd]igital (?:file|download|item)|Instant [Dd]ownload')

# Below this a "page" is almost certainly an error, an interstitial or a truncated
# response. Real listing pages measured 534k-564k bytes; the floor is deliberately far
# below that rather than tuned to it.
MIN_PAGE_BYTES = 50_000


def detect_from_html(html):
    """Classify one listing from its page HTML.

    Returns {"product_type", "basis", "evidence"} — or product_type None with a reason.

    The important refusal is the one that is easy to miss: **absence of markers only
    means "physical" on a page that actually rendered.** A truncated or blocked
    response has no markers either, and calling that physical is a plausible wrong
    answer that silently applies the 0.35 floor to a digital product.
    """
    if not html or len(html) < MIN_PAGE_BYTES:
        return {"product_type": None, "basis": "page_too_small",
                "evidence": {"bytes": len(html or "")}}

    personalized = len(_PERSONALIZATION.findall(html))
    digital = len(_DIGITAL.findall(html))
    evidence = {"personalization_fields": personalized, "digital_markers": digital}

    # Precedence when a listing is both — a personalized printable exists. Personalized
    # wins because it carries the constraint that actually binds: someone must edit the
    # file per order, so the weekly capacity ceiling applies and the 0.50 floor is the
    # honest one. Choosing `digital` here would promise unlimited volume at a 0.70
    # floor on work that is done by hand.
    if personalized:
        return {"product_type": PERSONALIZED, "basis": "measured", "evidence": evidence}
    if digital:
        return {"product_type": DIGITAL, "basis": "measured", "evidence": evidence}
    return {"product_type": PHYSICAL, "basis": "measured_by_absence", "evidence": evidence}


def detect(listing_id, session_manager):
    """Fetch a listing and classify it. Public tier only (D-29).

    A failed fetch returns None rather than a type — an unreachable page is not
    evidence of anything, and must never be cached or stored as a classification.
    """
    resp = session_manager.get(
        f"https://www.etsy.com/listing/{listing_id}/", platform="etsy")
    if resp.status_code != 200:
        return {"product_type": None, "basis": "fetch_failed",
                "evidence": {"status": resp.status_code}}
    result = detect_from_html(resp.text)
    result["listing_id"] = str(listing_id)
    return result


def majority_type(results, min_confident=3):
    """The dominant product type across a niche's listings, or a refusal.

    Used to type a KEYWORD rather than a listing: "are the people winning this term
    selling downloads or handmade goods?" — which decides the margin floor a candidate
    is judged against.

    Refuses on a thin or split sample. A niche genuinely half digital and half physical
    has no single answer, and picking the larger half would apply one floor to products
    that do not share it.
    """
    typed = [r["product_type"] for r in results if r.get("product_type")]
    if len(typed) < min_confident:
        return {"product_type": None, "basis": "insufficient_sample",
                "counted": len(typed), "needed": min_confident}

    counts = {t: typed.count(t) for t in set(typed)}
    winner = max(counts, key=counts.get)
    share = counts[winner] / len(typed)
    if share < 0.6:
        return {"product_type": None, "basis": "no_dominant_type",
                "counts": counts, "share": round(share, 3)}
    return {
        "product_type": winner, "basis": "measured_majority",
        "counts": counts, "share": round(share, 3), "counted": len(typed),
        # Measured live: "printable wall art" came back 3 digital / 2 personalized and
        # "felt garland" 3 physical / 1 digital / 1 personalized — both landing exactly
        # on the threshold. At that share the losing types are a large minority with a
        # different cost structure and a different margin floor, so the verdict is
        # right for most of the niche rather than for the niche.
        "is_marginal": share < 0.7,
    }
