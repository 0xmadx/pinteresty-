"""The Market screen: bounds stay bounds, floors stay floors, bias is on the page.

This screen ranks competitor listings, so it is the one most able to launder an
estimate into a fact. The tests are almost entirely about what it refuses to
overstate: a quantised sales counter as a rate, a review velocity as a sales rate,
and a shelf of star sellers as a representative sample.

    .venv/Scripts/python.exe -m etsy.ui.test_market_page
"""
from datetime import datetime, timezone

from etsy.ui import market_page as page

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


NOW = datetime(2026, 8, 20, tzinfo=timezone.utc)


def listing(title, term, basis="measured", velocity=0.21, gained=1, reviews=42):
    v = {"basis": basis}
    if basis == "measured":
        v.update(velocity=velocity, reviews_gained=gained, window_days=4.68,
                 total_reviews=reviews, is_lower_bound=True)
    return {"title": title, "matched_term": term, "velocity": v,
            "total_reviews": reviews}


def shop(name="shopflowerlane", sales=25100, reviews=4600, bound=21.17,
         matched=None):
    return {"shop": name,
            "latest": {"total_sales": sales, "total_reviews": reviews},
            "rate_bound": bound,
            "matched": matched if matched is not None else
            [listing("Birthday Crown", "birthday crown")]}


def main():
    print()
    h = page.render_html([shop()], now=NOW)

    # --- the sales delta is a BOUND, never a rate ------------------------------------
    check("a quantised counter reads as a bound, not a rate",
          "fewer than 21/day" in h, "bound not shown")
    check("and the page says why — the counter is quantised",
          "quantised" in h)
    check("it is NOT rendered as '0/day' or '21/day' flat",
          "21/day" in h and ">21/day<" not in h)

    no_delta = page.render_html([shop(bound=None)], now=NOW)
    check("with too few readings for a delta, it says so rather than showing 0",
          "not enough readings" in no_delta)

    # --- review velocity is a FLOOR -------------------------------------------------
    print()
    check("a measured velocity is labelled a floor", "floor" in h)
    check("with the reviews gained and the window", "1 over 4.68d" in h)
    check("the footer states reviews undercount sales", "undercount sales" in h)

    pending = page.render_html([shop(matched=[
        listing("New listing", "felt garland", basis="insufficient_history")])], now=NOW)
    check("a listing too new to rate shows its reason, not a fake velocity",
          "insufficient history" in pending)
    check("and is not dropped — new launches are worth seeing early",
          "New listing" in pending)

    # --- the survivor bias is ON THE PAGE -------------------------------------------
    print()
    check("all-star shops carry the survivor warning",
          "Survivor warning" in h and "what winners do" in h)
    mixed = page.render_html([shop()], now=NOW, all_stars=False)
    check("a mixed set of shops does not show the warning",
          "Survivor warning" not in mixed)

    # --- the match is the point ------------------------------------------------------
    print()
    check("a listing shows which watched term it matches",
          "birthday crown" in h)
    empty_match = page.render_html([shop(matched=[])], now=NOW)
    check("a shop with no matching listing says so, not a blank table",
          "Nothing this shop lists matches" in empty_match)

    # --- empty and escaping ----------------------------------------------------------
    print()
    empty = page.render_html([], now=NOW)
    check("no tracked shops explains how to add one", "settings_store shop add" in empty)
    nasty = page.render_html([shop(matched=[listing("<script>x</script>", "t")])], now=NOW)
    check("a listing title cannot inject markup", "<script>x" not in nasty)

    # --- themes and determinism ------------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))
    check("the same data renders identically twice",
          page.render_html([shop()], now=NOW) == page.render_html([shop()], now=NOW))

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
