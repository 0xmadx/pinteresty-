"""Per-listing sampling: the bigger n, and the contamination it must refuse.

The card version of this measurement is honest and usually indecisive — nine
observations cannot separate thin from crowded. This module buys a decisive sample
at one request per listing, which makes the cost real and the guards more
important, not less: a forty-listing sample that quietly includes seven shop-level
review totals is worse than nine clean ones.

    .venv/Scripts/python.exe -m etsy.analytics.test_listing_sample
"""
from etsy.analytics.listing_sample import (DEFAULT_SAMPLE, PREDICATES,
                                           SHOP_TOTAL_SHARE, parse_listing, profile,
                                           read, sample)

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def page(rating="4.9", reviews=33, price="21.95", star=True, free=False):
    bits = [f'"aggregateRating": {{"@type":"AggregateRating","ratingValue":"{rating}",'
            f'"reviewCount":{reviews}}}',
            f'"price": "{price}"']
    if star:
        bits.append("<p>Star Seller</p>")
    if free:
        bits.append("<span>FREE shipping</span>")
    return "<html>" + " ".join(bits) + "</html>"


class FakeSession:
    """Serves canned pages; records what was requested."""

    def __init__(self, pages, fail_on=()):
        self.pages = pages
        self.fail_on = set(str(x) for x in fail_on)
        self.requested = []

    def request(self, method, url, **kw):
        lid = url.rstrip("/").split("/")[-1]
        self.requested.append(lid)
        if lid in self.fail_on:
            raise RuntimeError("network")

        class R:
            text = self.pages.get(lid, "")
        return R()


class FakeAPI:
    def __init__(self, pages, fail_on=()):
        self.session = FakeSession(pages, fail_on)
        self.headers = {}


def main():
    # --- structured fields are parsed, not matched --------------------------------
    print()
    r = parse_listing(page())
    check("the rating is read from the structured block", r["rating"] == 4.9, r)
    check("so is the review count", r["reviews"] == 33, r)
    check("and the price", r["price"] == 21.95, r)
    check("basis says measured", r["rating_basis"] == "measured", r["rating_basis"])

    # --- the shop-total trap ---------------------------------------------------------
    # Measured for real during the competitor-tracker work: 7 of 12 listings from one
    # shop returned 4,580 against a shop showing 4.6k. Recorded as-is, each would
    # have looked like a runaway winner.
    print()
    r = parse_listing(page(reviews=4580), shop_total_reviews=4600)
    check("a listing claiming its shop's whole review history is REFUSED",
          r["reviews"] is None, r)
    check("and the refusal is named, not silent",
          r["rating_basis"] == "refused_shop_total_contamination", r["rating_basis"])
    check("the rating survives — only the count was contaminated", r["rating"] == 4.9)
    ok = parse_listing(page(reviews=33), shop_total_reviews=4600)
    check("a plausible count passes through untouched", ok["reviews"] == 33, ok)
    edge = parse_listing(page(reviews=int(4600 * SHOP_TOTAL_SHARE)),
                         shop_total_reviews=4600)
    check("the threshold is inclusive — exactly 90% is refused",
          edge["reviews"] is None, edge)

    # --- weak evidence is labelled weak ------------------------------------------------
    print()
    r = parse_listing(page(star=True, free=True))
    check("star seller is found", r["star_seller"] is True)
    check("free shipping is found", r["free_shipping"] is True)
    check("both are labelled as MARKERS, not parsed fields",
          r["marker_basis"] == "marker", r["marker_basis"])
    r = parse_listing(page(star=False, free=False))
    check("their absence is False, which for a marker is a real reading",
          r["star_seller"] is False and r["free_shipping"] is False)

    # --- nothing is invented from nothing ----------------------------------------------
    print()
    empty = parse_listing("")
    check("an empty page yields no rating", empty["rating"] is None, empty)
    check("and no price", empty["price"] is None)
    check("with basis absent, not zero", empty["rating_basis"] == "absent")
    broken = parse_listing('"aggregateRating": {"ratingValue":"oops"}')
    check("an unparseable block says so rather than guessing",
          broken["rating_basis"] == "unparseable", broken["rating_basis"])

    # --- sampling: rank order, bounded, failures counted --------------------------------
    print()
    ids = [str(i) for i in range(100, 140)]
    api = FakeAPI({i: page() for i in ids})
    rows, failed = sample(api, ids, sample_size=10)
    check("it stops at the requested sample size — 40 requests is not a default",
          len(rows) == 10 and len(api.session.requested) == 10, len(rows))
    check("and takes them in RANK order, not at random",
          api.session.requested == ids[:10], api.session.requested[:3])
    check("the default sample is small enough to be safe",
          DEFAULT_SAMPLE <= 12, DEFAULT_SAMPLE)

    api = FakeAPI({i: page() for i in ids}, fail_on=ids[:3])
    rows, failed = sample(api, ids, sample_size=10)
    check("a listing that fails to fetch is counted, not recorded as blank",
          failed == 3 and len(rows) == 7, (failed, len(rows)))

    # --- the payoff: a bigger n decides what nine could not ------------------------------
    print()
    nine = [{"is_ad": False, "star_seller": i < 3, "rating": 4.5, "free_shipping": False}
            for i in range(9)]
    forty = [{"is_ad": False, "star_seller": i < 20, "rating": 4.5, "free_shipping": False}
             for i in range(40)]
    p9, p40 = profile(nine), profile(forty)
    key = ("quality", "star_seller")
    check("at n=9 a third-ish share cannot be placed",
          p9[key]["can_discriminate"] is False, p9[key])
    check("at n=40 a clear share CAN be placed — the reason to spend the requests",
          p40[key]["can_discriminate"] is True, p40[key])
    check("and the interval is much tighter",
          (p40[key]["high"] - p40[key]["low"]) < (p9[key]["high"] - p9[key]["low"]) / 1.5)

    # A bigger sample is not a magic wand. A share sitting ON a threshold still
    # cannot be placed, because the interval straddles the line wherever it is
    # centred — and pretending otherwise is how "32.5%, definitely crowded" gets
    # reported from a measurement that says no such thing.
    on_line = [{"is_ad": False, "star_seller": i < 13, "rating": 4.5,
                "free_shipping": False} for i in range(40)]
    check("a share sitting exactly on the crowded threshold still refuses at n=40",
          profile(on_line)[key]["can_discriminate"] is False, profile(on_line)[key])

    # --- discount is NOT claimed here ------------------------------------------------------
    print()
    check("the discount dimension is absent, because the page has no reliable "
          "field for it — better missing than faked",
          not any(d == "discount" for d, _ in PREDICATES))

    # --- what read() always says -------------------------------------------------------------
    print()
    lines = read(forty, p40, failed=2)
    joined = " ".join(lines)
    check("it leads with the sample size", "Sampled 40" in joined, joined[:90])
    check("failures are disclosed", "2 failed" in joined, joined[:140])
    check("and markers are called weaker evidence than the parsed fields",
          "weaker evidence" in joined, joined[-120:])
    contaminated = [{"is_ad": False, "rating": 4.9,
                     "rating_basis": "refused_shop_total_contamination"}] * 3
    check("refused listings are reported, not hidden",
          "refused" in " ".join(read(contaminated, profile(contaminated))).lower())

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
