"""Offline tests for the listing-page parsers. No network, no database.

Two regressions and one correction:

  1. `listing_api` defaulted `favorites` and `in_cart` to **0**. A threshold-gated
     badge that Etsy did not render then read as "nobody wants this" instead of
     "below the display threshold" (N-02).
  2. The only cart pattern was `people's carts`, which does not match Etsy's current
     `In 136 carts`. A single wording is a silent single point of failure.
  3. `core/database.py` recorded "Etsy does not publish a creation date". True of the
     shop grid where it was measured; FALSE of the listing page, which carries
     `Listed on Aug 29, 2026`. That mistaken belief closed off honeymoon detection.

The canary matters more than any single pattern here. A reworded badge and a genuinely
quiet listing produce the identical `None`, and only one of them is a bug — so a
healthy page where NOTHING matched is reported as a parser alert, never as an absence.

Run:  python -m etsy.api.public.test_listing_page
"""
import sys
from datetime import date

from etsy.api.public.api import (MIN_LISTING_PAGE_BYTES, RENEWAL_REVIEW_THRESHOLD,
                                 listing_age, parse_listed_on, parse_listing_live)

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


def _page(body, size=MIN_LISTING_PAGE_BYTES + 1000):
    """A body padded to a plausible listing-page size, so the guard does not fire."""
    return body + ("<!-- pad -->" * ((size - len(body)) // 12 + 1))


def main():
    # --- listing age: the honeymoon signal, one regex from HTML we already cache ----
    print("\nlisted_on")
    check("reads the date out of og:description",
          parse_listed_on('<meta property="og:description" content="Listed on Aug 29, '
                          '2026. Handmade felt garland">') == "2026-08-29")
    check("and out of the page body",
          parse_listed_on("<p>Listed on Dec 1, 2024</p>") == "2024-12-01")
    check("single-digit days parse", parse_listed_on("Listed on Jan 7, 2025") == "2025-01-07")
    check("ISO so it sorts and subtracts",
          parse_listed_on("Listed on Nov 15, 2025") == "2025-11-15")
    # "could not read it" and "it is new" are the two readings a honeymoon check must
    # never confuse, so an unparseable date is None and never today.
    check("a page without the phrase yields None, NOT today",
          parse_listed_on("<html>no date anywhere</html>") is None)
    check("a malformed month is refused rather than guessed",
          parse_listed_on("Listed on Xyz 40, 2026") is None)
    check("tolerates None", parse_listed_on(None) is None)

    # --- THE RENEWAL TRAP -----------------------------------------------------------
    #
    # Measured live 2026-09-01 on listing 1864690497 (KvYshopUS): 7,700 reviews, and
    # the page says `Listed on Sep 1, 2026` — that day, in og:description AND in the
    # body. Etsy auto-renews listings roughly every four months and the displayed date
    # moves with the renewal, so a four-year-old best-seller and a genuinely new
    # listing print the identical string.
    #
    # Read as an age this would have called that listing brand new. The parser was
    # correct; the MEANING was wrong, which is the harder half and the reason this
    # block exists.
    print("\nlisting_age — the date resets on renewal")
    today = date(2026, 9, 1)

    renewed = listing_age("2026-09-01", review_count=7700, now=today)
    check("a same-day date with 7,700 reviews is NOT called new",
          renewed["honeymoon"] is None, renewed)
    check("it is named as suspected renewal, not as an age",
          renewed["basis"] == "renewal_suspected", renewed["basis"])
    check("and the note says the true age is unknown and greater",
          "UNKNOWN" in renewed["note"])

    fresh = listing_age("2026-08-25", review_count=0, now=today)
    check("a young date with no reviews may still be a honeymoon candidate",
          fresh["honeymoon"] is True, fresh)
    check("but its age is a LOWER bound, never an age",
          fresh["age_days_lower_bound"] == 7 and "LOWER bound" in fresh["note"])

    old = listing_age("2024-01-10", review_count=3, now=today)
    check("an old date is plainly not a honeymoon", old["honeymoon"] is False)
    check("the bound still counts the days", old["age_days_lower_bound"] == 965, old)

    # honeymoon must be tri-state. A bare boolean would have to pick a side for the
    # renewed case, and either choice is a claim the data does not support.
    check("honeymoon is three-valued: True / False / None-for-unknown",
          {renewed["honeymoon"], fresh["honeymoon"], old["honeymoon"]} == {None, True, False})

    check("no date at all is unmeasured, NOT 'not a honeymoon'",
          listing_age(None)["basis"] == "unmeasured"
          and listing_age(None)["honeymoon"] is None)
    check("an unparseable date is refused rather than coerced",
          listing_age("last Tuesday")["basis"] == "unparseable")
    # A young date with a handful of reviews is genuinely ambiguous; the threshold is
    # deliberately low so the answer is "unknown" rather than a flattering "new".
    check("even a modest review count contradicts a same-week date",
          listing_age("2026-08-30", review_count=RENEWAL_REVIEW_THRESHOLD,
                      now=today)["honeymoon"] is None)

    # --- the volatile trio ----------------------------------------------------------
    print("\nlisting_live — the wordings")
    modern = parse_listing_live(_page("<div>In 136 carts</div>"))
    check("Etsy's CURRENT wording parses — the old regex missed this entirely",
          modern["in_cart"] == 136, modern["in_cart"])
    legacy = parse_listing_live(_page("<div>In 20 people's carts</div>"))
    check("and the older possessive wording still does", legacy["in_cart"] == 20)
    curly = parse_listing_live(_page("<div>In 20 people’s carts</div>"))
    check("including with a curly apostrophe", curly["in_cart"] == 20)
    check("thousands separators survive",
          parse_listing_live(_page("<div>In 1,204 carts</div>"))["in_cart"] == 1204)

    full = parse_listing_live(_page(
        "<div>In 136 carts</div><div>1,890 favorites</div>"
        "<div>23 bought in the past 24 hours</div>"), listing_id="111")
    check("favourites parse", full["favorites"] == 1890, full["favorites"])
    check("the 24h bought badge parses", full["bought_24h"] == 23, full["bought_24h"])
    check("the listing id rides along", full["listing_id"] == "111")
    check("a full read is not an alert", full["parser_alert"] is False)
    # The badge is a single best day; x30 projects it across a month. The note has to
    # say so, because the number itself looks like a rate.
    check("the note calls bought_24h an upper bound", "upper bound" in full["note"])

    # --- N-02: absent is BELOW THE THRESHOLD, never zero -----------------------------
    print("\nlisting_live — absent is not zero")
    quiet = parse_listing_live(_page("<div>In 5 carts</div>"))
    check("an unrendered badge is None, not 0 — this is the whole regression",
          quiet["favorites"] is None and quiet["bought_24h"] is None, quiet)
    check("and *_present says we looked",
          quiet["in_cart_present"] is True and quiet["favorites_present"] is False)
    check("the note names the threshold, not zero", "threshold" in quiet["note"])

    # --- the canary: a reworded badge must not read as a quiet listing ---------------
    print("\nlisting_live — the canary")
    silent = parse_listing_live(_page("<div>totally new wording nobody predicted</div>"))
    check("a healthy page matching NOTHING raises a parser alert",
          silent["parser_alert"] is True, silent)
    check("the alert tells the reader to suspect the parser first",
          "reworded badge" in silent["note"])
    check("and it still refuses to emit a number",
          silent["in_cart"] is None and silent["favorites"] is None)
    check("one match is enough to clear the alert",
          parse_listing_live(_page("<div>7 favorites</div>"))["parser_alert"] is False)

    # --- a blocked page is not a quiet listing ---------------------------------------
    print("\nlisting_live — refusing a page that is not a listing")
    blocked = parse_listing_live("<html>Are you a robot?</html>", listing_id="222")
    check("an undersized page is REFUSED, not read as three absences",
          blocked["basis"] == "page_too_small", blocked["basis"])
    check("it claims nothing at all",
          blocked["in_cart"] is None and blocked["favorites"] is None
          and blocked["bought_24h"] is None)
    check("and does not raise a parser alert — the parser was never the problem",
          "parser_alert" not in blocked or not blocked.get("parser_alert"))
    check("the byte count is reported so the reader can judge",
          blocked["bytes"] < MIN_LISTING_PAGE_BYTES)
    check("an empty page is refused rather than crashing",
          parse_listing_live("")["basis"] == "page_too_small")
    check("None is refused too", parse_listing_live(None)["basis"] == "page_too_small")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
