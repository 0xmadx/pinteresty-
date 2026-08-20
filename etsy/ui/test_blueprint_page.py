"""The Blueprint screen renders the generator's honesty faithfully.

The generator (generators/blueprint.py) already refuses to invent tags, copy
over-long ones, or price below the floor. This screen's only job is to show that
honestly — so the tests are about the warnings SURVIVING to the page, and about the
one thing the screen adds: the momentum banner, because a winnable-looking term
crashing week-over-week is the trap the operator most needs to see before listing.

    .venv/Scripts/python.exe -m etsy.ui.test_blueprint_page
"""
from datetime import datetime, timezone

from etsy.ui import blueprint_page as page

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


def bp(wow=-80.3, tags_detail=None, rejected=None, price=None, warnings=None,
       volume=11642, supply=6676):
    return {
        "term": "custom family name necklace", "product_type": "personalized",
        "_sources": 6,
        "title": {"title": "Custom family name necklace | Heart name necklace",
                  "length": 52, "reason": "leads with the exact phrase"},
        "tags": {"filled": 2, "detail": tags_detail if tags_detail is not None else
                 [{"tag": "name necklace", "source": "consensus"},
                  {"tag": "heart name necklace", "source": "consensus"}],
                 "rejected": rejected if rejected is not None else
                 [{"tag": "custom family name necklace", "reason": "27 chars — limit is 20"}]},
        "price": price or {"price": None, "reason": "no median band returned"},
        "market": {"volume": volume, "supply": supply, "cvr": 0.003, "wow_change": wow},
        "ctr_checklist": ["First photo readable at thumbnail size",
                          "Price positioned against the band"],
        "warnings": warnings if warnings is not None else
        ["only 2/13 tags had measured support",
         "4 competitor tag(s) exceed Etsy's 20-char limit"],
    }


def main():
    print()
    h = page.render_html(bp(), now=NOW)

    # --- the momentum banner is the screen's own contribution --------------------------
    check("a term crashing week-over-week gets a DANGER momentum banner",
          'class="momentum danger"' in h, "no danger banner")
    check("and the banner says a good ratio on falling demand is a trap",
          "collapsing week-over-week" in h)
    check("the percentage is shown", "-80%" in h)

    rising = page.render_html(bp(wow=12), now=NOW)
    check("a rising term is not flagged as danger",
          'class="momentum danger"' not in rising and 'class="momentum good"' in rising)
    check("a mild dip is a warn, not a danger",
          'class="momentum warn"' in page.render_html(bp(wow=-8), now=NOW))
    no_wow = page.render_html(bp(wow=None), now=NOW)
    check("no momentum data shows no banner, rather than a fake 0%",
          'class="momentum' not in no_wow)

    # --- the generator's refusals survive to the page ---------------------------------
    print()
    check("the tag count says only measured support", "only measured support" in h)
    check("a rejected over-long tag is shown, struck through, with the reason",
          "<s>custom family name necklace</s>" in h and "limit is 20" in h)
    check("the warnings block is rendered — it is the useful part when thin",
          "only 2/13 tags" in h and "20-char limit" in h)

    # --- price that loses money is stated, not smoothed -------------------------------
    print()
    check("no price says so plainly", "No price clears the floor" in h)
    priced = page.render_html(bp(price={"price": 42.0, "reason": "band midpoint clears"}),
                              now=NOW)
    check("a real price shows the dollar amount", "$42.0" in priced)
    check("and is styled as good, not danger", 'class="price good"' in priced)

    # --- a genuinely strong blueprint has no warning block ----------------------------
    print()
    strong = page.render_html(bp(wow=5, warnings=[],
                                 rejected=[],
                                 price={"price": 38.0, "reason": "clears"}), now=NOW)
    check("no warnings means no warning block, not an empty one",
          '<div class="warnblock">' not in strong)

    # --- copy affordance --------------------------------------------------------------
    print()
    check("the title sits in a selectable copy box",
          'class="copy"' in h and "user-select:all" in h)
    check("tags are individually selectable chips", 'class="chip' in h)

    # --- themes, escaping, determinism ------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))
    nasty = page.render_html(bp(tags_detail=[{"tag": "<script>x</script>",
                                              "source": "consensus"}]), now=NOW)
    check("a tag cannot inject markup", "<script>x" not in nasty)
    check("the same blueprint renders identically twice",
          page.render_html(bp(), now=NOW) == page.render_html(bp(), now=NOW))
    check("the slug is filesystem-safe",
          page._slug("Custom / Name!") == "custom---name")

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
