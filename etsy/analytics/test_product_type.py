"""Product-type detection (D-22), and the one refusal that is easy to miss.

A wrong type applies the wrong margin floor, asks gap questions the product cannot
answer, and mis-states whether demand or the operator's hands is the binding
constraint — three confident wrong answers from one mistake.

Offline: synthetic pages built from the markers measured live on 2026-08-15.

    .venv/Scripts/python.exe -m etsy.analytics.test_product_type
"""
from etsy.analytics.product_type import (DIGITAL, MIN_PAGE_BYTES, PERSONALIZED,
                                         PHYSICAL, detect_from_html, majority_type)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


def page(*fragments, size=MIN_PAGE_BYTES + 1000):
    """A page big enough to be real, carrying the given markers."""
    body = "".join(fragments)
    return body + ("x" * max(0, size - len(body)))


DIGITAL_MARKUP = '<p>Digital download</p><span>Instant Download</span>'
PERSONALIZATION_MARKUP = '<input id="personalization-instructions" />'


# --- the three types, from markers measured on real pages -------------------------
r = detect_from_html(page(DIGITAL_MARKUP))
check("digital markers -> digital", r["product_type"] == DIGITAL, r)
check("and it is measured", r["basis"] == "measured", r)

r = detect_from_html(page(PERSONALIZATION_MARKUP))
check("a personalization field -> personalized", r["product_type"] == PERSONALIZED, r)

r = detect_from_html(page("<p>Handmade felt garland</p>"))
check("no markers -> physical", r["product_type"] == PHYSICAL, r)
check("but the basis says it was inferred from absence",
      r["basis"] == "measured_by_absence", r)
# Naming it differently from the positive cases matters: absence is weaker evidence
# and the caller should be able to tell.

# --- precedence when a listing is both --------------------------------------------
r = detect_from_html(page(DIGITAL_MARKUP, PERSONALIZATION_MARKUP))
check("personalized beats digital", r["product_type"] == PERSONALIZED, r)
# A personalized printable is real. Personalized wins because someone edits the file
# per order, so the weekly capacity ceiling binds and 0.50 is the honest floor.
# Calling it digital would promise unlimited volume at 0.70 on work done by hand.

# --- THE refusal ------------------------------------------------------------------
r = detect_from_html("<html>blocked</html>")
check("a truncated page is not physical", r["product_type"] is None, r)
check("and says why", r["basis"] == "page_too_small", r)
# This is the easy one to get wrong. A blocked or truncated response carries no
# markers either — identical to a genuine physical listing. Defaulting to physical
# would quietly apply the 0.35 floor to a digital product whose real floor is 0.70.

check("an empty page is refused", detect_from_html("")["product_type"] is None)
check("None is refused", detect_from_html(None)["product_type"] is None)

# --- typing a NICHE from its listings ----------------------------------------------
def r_of(t):
    return {"product_type": t}


res = majority_type([r_of(DIGITAL)] * 8 + [r_of(PHYSICAL)] * 2)
check("a dominated niche gets a type", res["product_type"] == DIGITAL, res)
check("with its share reported", res["share"] == 0.8, res)

res = majority_type([r_of(DIGITAL)] * 5 + [r_of(PHYSICAL)] * 5)
check("an evenly split niche is refused", res["product_type"] is None, res)
check("no_dominant_type is named", res["basis"] == "no_dominant_type", res)
# Half digital and half physical has no single answer, and picking the larger half
# applies one margin floor to products that do not share it.

res = majority_type([r_of(DIGITAL), r_of(DIGITAL)])
check("a thin sample is refused", res["product_type"] is None, res)
check("insufficient_sample is named", res["basis"] == "insufficient_sample", res)

res = majority_type([r_of(None), r_of(None), r_of(DIGITAL)])
check("unclassified listings do not count toward the sample",
      res["product_type"] is None, res)
# Counting a refusal as evidence would let three failed fetches decide a niche.

res = majority_type([r_of(PERSONALIZED)] * 3)
check("a unanimous thin-but-sufficient sample passes",
      res["product_type"] == PERSONALIZED and res["share"] == 1.0, res)
check("a unanimous result is not marginal", res["is_marginal"] is False, res)

# Both real niches measured live landed exactly on 0.6, so the flag is not academic.
res = majority_type([r_of(DIGITAL)] * 3 + [r_of(PERSONALIZED)] * 2)
check("a bare majority is flagged marginal", res["is_marginal"] is True, res)
check("but still returns the type", res["product_type"] == DIGITAL, res)
# 40% of that niche has a different cost structure and a different margin floor, so
# the verdict is right for most of the niche rather than for the niche.

# --- resolve_product_type: deterministic first, LLM only as fallback (D-27) --------
from etsy.analytics.blueprint_support import resolve_product_type  # noqa: E402


class FakePublic:
    """Serves a fixed SERP + per-listing product types."""

    def __init__(self, types):
        self._types = types  # list of product_type strings

    def get_public_search(self, term):
        return {"cards": [{"listing_id": str(i), "is_ad": False}
                          for i in range(len(self._types))]}

    def get_listing_data(self, listing_id):
        return {"tags": ["t"], "breadcrumb": ["C"],
                "product_type": self._types[int(listing_id)]}


class FakeLLM:
    def __init__(self, answer):
        self.answer = answer
        self.called = False

    def classify_product_type(self, term):
        self.called = True
        return self.answer


# A clear page-one majority is trusted and the LLM is never consulted.
llm = FakeLLM("physical")
r = resolve_product_type(FakePublic([DIGITAL, DIGITAL, DIGITAL, PHYSICAL]), "x", llm=llm)
check("a measured majority wins", r["product_type"] == DIGITAL, r)
check("and the LLM is NOT called when detection is confident", llm.called is False, llm.called)

# A split page-one falls back to the LLM — and the basis says so.
llm = FakeLLM("personalized")
r = resolve_product_type(FakePublic([DIGITAL, PHYSICAL, PERSONALIZED]), "x", llm=llm)
check("a split sample falls back to the LLM", r["product_type"] == PERSONALIZED, r)
check("the LLM was consulted", llm.called is True)
check("and the basis flags it as a guess", r["basis"] == "llm_fallback", r)
# A verdict resting on an LLM guess must be distinguishable from one resting on
# measurement — the '?' in the hunt output comes from this basis.

# No LLM and a split sample → no type, and therefore no verdict.
r = resolve_product_type(FakePublic([DIGITAL, PHYSICAL, PERSONALIZED]), "x", llm=None)
check("without an LLM a split sample stays undetermined", r["product_type"] is None, r)

# The LLM refusing ('unknown' → None) does not become a defaulted type.
llm = FakeLLM(None)
r = resolve_product_type(FakePublic([DIGITAL, PHYSICAL, PERSONALIZED]), "x", llm=llm)
check("an unsure LLM leaves the type None, never defaulted", r["product_type"] is None, r)
# "I am not sure" must never silently become "physical" and apply the 0.35 floor.

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
