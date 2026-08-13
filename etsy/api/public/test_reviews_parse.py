"""Offline tests for the review-rating parse. No network.

The regression this guards: the parser used to default an unfound rating to 5, so a
markup change made every review look positive and the flaw analysis reported a flawless
product. A rating is measured or None — never fabricated.

Run:  python -m etsy.api.public.test_reviews_parse
"""
import sys

from etsy.api.public.reviews_api import parse_reviews_html

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


REVIEW = "This arrived broken and the seller never answered my messages at all."
PRAISE = "Absolutely beautiful piece, exactly as pictured and shipped fast too."


def main():
    # --- ratings are read from the markup when present -----------------------------------
    html = f"""
    <div class="review">
      <span class="screen-reader-only">1 out of 5 stars</span>
      <p>{REVIEW}</p>
    </div>
    <div class="review">
      <span class="screen-reader-only">5 out of 5 stars</span>
      <p>{PRAISE}</p>
    </div>
    """
    out = parse_reviews_html(html)
    check("two reviews extracted", len(out) == 2, f"got {len(out)}")
    by_text = {r["text"]: r for r in out}
    check("a 1-star review is measured as 1, not defaulted to 5",
          by_text[REVIEW]["rating"] == 1, f"got {by_text[REVIEW]['rating']}")
    check("a 5-star review is measured as 5",
          by_text[PRAISE]["rating"] == 5, f"got {by_text[PRAISE]['rating']}")
    check("measured ratings carry rating_basis='measured'",
          all(r["rating_basis"] == "measured" for r in out))

    # --- the star text can sit a couple of levels up --------------------------------------
    print()
    nested = f"""
    <li class="review-item">
      <div class="header"><span>3 out of 5 stars</span></div>
      <div class="body"><div class="inner"><p>{REVIEW}</p></div></div>
    </li>
    """
    out = parse_reviews_html(nested)
    check("star text in a sibling branch is still found via ancestors",
          out and out[0]["rating"] == 3, f"got {out}")

    # --- THE regression: no star text anywhere --------------------------------------------
    print()
    bare = f"<div><p>{REVIEW}</p><p>{PRAISE}</p></div>"
    out = parse_reviews_html(bare)
    check("with no star text, rating is None — NEVER a fabricated 5",
          all(r["rating"] is None for r in out),
          f"got {[r['rating'] for r in out]}")
    check("and the basis says so", all(r["rating_basis"] == "unparsed" for r in out))
    check("so a failed parse yields zero reviews rated >= 4",
          sum(1 for r in out if (r["rating"] or 0) >= 4) == 0)

    # --- noise handling --------------------------------------------------------------------
    print()
    noisy = """
    <p>short</p>
    <p>2 out of 5 stars but this line is the star label itself and not a review body</p>
    """
    out = parse_reviews_html(noisy)
    check("short fragments and the star-label line itself are not reviews",
          len(out) == 0, f"got {out}")
    check("empty html yields an empty list, not a crash", parse_reviews_html("") == [])

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
