"""The last mile: from "this keyword is worth it" to text you can paste into Etsy.

**Why this file exists.** An audit on 2026-09-01 counted the tools and found the
system had **34 ways to find a keyword and zero ways to write a listing** — while
`etsy/generators/blueprint.py` (291 lines, 32 passing tests) had been sitting there
since August building a title, 13 validated tags, a price and a category. Nothing
on the operator's only interface could reach it: `grep generators mcp_server/`
returned nothing. Its one caller was `etsy/analytics/hunt.py`, a terminal command,
and the operator is not a developer.

It had a screen once — `etsy/ui/blueprint_page.py`, whose first line read *"the
last mile, from 'winnable' to a listing you paste"* — and that screen was deleted
with the rest of the UI (D-52) with nothing put in its place.

So the seller was handed a keyword and abandoned at the hardest part of the week:
writing the listing. That is not a missing feature, it is the feature; everything
upstream exists to reach this point.

WHAT THIS DOES NOT DO, stated plainly so nobody is surprised:
  * it does not write your DESCRIPTION — no code in this repo does
  * it does not choose your photos, your design, or your differentiator
  * it does not publish anything

WHAT IT COSTS: one private `results_data` call (your seller account) plus one SERP
pass and a handful of listing fetches on the public tier. Tags are MEASURED from
the listings that actually rank for the term, not invented.
"""
from etsy.analytics import profit


def build_listing_plan(term, profile=None, api=None, public_api=None,
                       settings=None, differentiator=None):
    """Title, 13 tags, a price and a category for one term.

    `profile` is the operator's named cost profile from `config/settings.json`.
    Without it the price cannot be judged — `profit.verdict` defaults every cost to
    ZERO, which answers "is this profitable for a product that costs nothing to
    make?" and always says yes. So a missing profile means the price arrives with
    **no verdict**, never with a flattering one.

    Every field carries where it came from. Tags are mined from the listings that
    RANK for this term, with ads excluded — a promoted listing bought its position,
    so its tags are evidence of a budget, not of what ranks.
    """
    from core.settings_store import load
    from etsy.analytics.blueprint_support import material_for_term
    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.api.public.api import EtsyPublicAPI
    from etsy.generators import blueprint as bp

    settings = settings or load()
    api = api or EtsyPrivateAPI()
    public_api = public_api or EtsyPublicAPI()

    raw = api.get_results_data(term)
    data = parse_results_data(raw) if raw else None
    if not data or not data.get("volume"):
        return {"ok": False, "term": term, "basis": "unmeasured",
                "error": f"no measured demand for '{term}'",
                "fix": "Check the term spelling, or run `compare` first to confirm "
                       "Etsy sizes it at all. A term Etsy will not size cannot be "
                       "planned — that is unmeasured, not zero (N-02)."}

    # One SERP pass buys all three: consensus tags for the copy, the breadcrumb for
    # where to file it, and the detected product type.
    consensus, category, detected_type = material_for_term(public_api, term)

    product_type, kwargs = detected_type, None
    if profile:
        try:
            kwargs = settings.verdict_kwargs(profile)
            product_type = settings.profile(profile)["product_type"]
        except (KeyError, ValueError) as e:
            return {"ok": False, "term": term, "basis": "bad_profile",
                    "error": f"cost profile '{profile}' unusable: {e}",
                    "fix": f"Known profiles: {sorted(getattr(settings, 'product_profiles', {}) or {})}"}

    def verdict_for_price(price):
        if not kwargs:
            # No profile: refuse rather than cost it at zero. The blueprint still
            # gets built — the TITLE and TAGS do not depend on the money — but the
            # price arrives unjudged and says so.
            return None
        return profit.verdict(price=price, demand_units_per_week=0, **kwargs)

    plan = bp.build(term, data, consensus, verdict_for_price,
                    product_type=product_type, category=category,
                    differentiator=differentiator)

    return {
        "ok": True, "term": term, "plan": plan,
        "product_type": product_type,
        "product_type_basis": ("your '%s' profile" % profile if profile
                               else "DETECTED from the ranking listings — pass a "
                                    "profile to override and to price it"),
        "priced": bool(kwargs),
        "price_basis": (f"judged against your '{profile}' costs" if kwargs else
                        "NOT JUDGED — no cost profile given. A price verdict with "
                        "zero costs says every price works. Pass profile=<name>."),
        "tags_basis": "MEASURED from the listings that rank for this term; ads "
                      "excluded, because a promoted listing bought its position and "
                      "its tags are evidence of a budget, not of what ranks",
        "basis": "derived",
        "does_not_include": [
            "the DESCRIPTION — nothing in this system writes one yet",
            "photos, the design itself, or your differentiator",
            "publishing — you list it; this only drafts the text",
        ],
    }
