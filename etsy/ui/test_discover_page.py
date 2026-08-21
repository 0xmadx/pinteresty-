"""The Discover screen ranks by winnability and folds walls honestly.

The whole point of this screen is D-31 made visible: the winnable ground is in the
long tail, not the head terms, so the pool must lead with demand-per-listing and
NOT with search volume. And a pool of a thousand walls must not bury the seven
terms that matter — but the walls are folded, not filtered, so the count of what
was hidden is always shown.

    .venv/Scripts/python.exe -m etsy.ui.test_discover_page
"""
from datetime import datetime, timezone

from etsy.ui import discover_page as page

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


def cand(term, ratio, verdict, volume=1000, supply=500, seed="mom necklace",
         moment=None, list_by=None):
    return {"term": term, "demand_per_listing": ratio, "verdict": verdict,
            "volume": volume, "supply": supply, "seed": seed, "moment": moment,
            "list_by": list_by, "timing": "seasonal" if moment else "evergreen"}


def main():
    pool = [
        cand("custom family name necklace", 1.744, "winnable", volume=11642, supply=6675),
        cand("christmas eve box", 0.28, "contested", moment="christmas",
             list_by="2026-09-16"),
        cand("nana necklace", 0.429, "contested"),
    ] + [cand(f"wall term {i}", 0.01, "wall") for i in range(400)]

    h = page.render_html(pool, now=NOW)

    # --- winnability leads, volume does not ------------------------------------------
    print()
    check("the winnable term is in the table",
          "custom family name necklace" in h)
    body = h[h.index("<tbody>"):h.index("</tbody>")]
    check("it appears ABOVE the higher-volume contested one — ranked by ratio",
          body.index("custom family name necklace") < body.index("christmas eve box"))
    # personalized gift had 230k volume but a worse ratio; a volume sort would float
    # a big wall to the top. Confirm no wall reaches the table at all.
    check("no wall term is in the table body", "wall term" not in body)

    # --- walls are folded, not filtered ----------------------------------------------
    print()
    check("the wall count is shown, so the pool reads as larger than the table",
          "400 more term(s)" in h, "fold count missing")
    check("and it says folded, not filtered", "folded away, not filtered" in h)
    check("the summary counts winnable/contested against the whole pool",
          "3 winnable or contested of 403" in h, "summary wrong")

    # --- a no-intent term is folded APART from the walls (D-43) ----------------------
    # A term with traffic and no buyers fails for the opposite reason to a wall, and
    # the operator reads them differently: "someone else owns this" vs "nobody wants
    # this". Collapsing them into one count hides which wall was hit.
    print()
    mixed = pool[:3] + [cand("aspirational trend", 10.0, "weak_intent",
                             volume=50000, supply=5000)]
    hm = page.render_html(mixed, now=NOW)
    mbody = hm[hm.index("<tbody>"):hm.index("</tbody>")]
    check("a no-intent term does not reach the table, despite a 10.0 ratio",
          "aspirational trend" not in mbody)
    # This is the whole point: ranked on demand-per-listing alone it would LEAD.
    check("it is counted separately from the walls",
          "weak purchase intent" in hm, hm[hm.index('class="fold"'):][:300])
    check("and the wall count does not absorb it",
          "1 more term(s) are walls" not in hm)

    # --- the seasonal join -------------------------------------------------------------
    print()
    check("a seasonal term shows its moment and deadline",
          "Christmas" in h and "list by 2026-09-16" in h)
    check("the summary notes how many are seasonal", "1 seasonal" in h)

    # --- empty and all-wall states ------------------------------------------------------
    print()
    empty = page.render_html([], now=NOW)
    check("an empty pool explains how to fill it", "discover" in empty)
    check("and shows no fabricated rows", "<tbody>" not in empty)

    all_walls = page.render_html([cand(f"w{i}", 0.02, "wall") for i in range(50)],
                                 now=NOW)
    check("a pool of only walls says so plainly, not with a blank table",
          "every\n          discovered term is a wall" in all_walls
          or "every discovered term is a wall" in all_walls.replace("\n", " ")
          .replace("  ", " "))
    check("and still reports the count folded", "50 more" in all_walls
          or "50 " in all_walls)

    # --- provenance and honesty ---------------------------------------------------------
    print()
    check("each term shows the seed it was expanded from",
          "mom necklace" in h)
    check("the footer says this is where to look, not what to make",
          "where to look, not what to make" in h)
    check("nothing is called a recommendation",
          "recommendation until the Cockpit" in h)

    # --- themes and escaping -------------------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))
    nasty = page.render_html([cand("<script>x</script>", 2.0, "winnable")], now=NOW)
    check("a term name cannot inject markup", "<script>x" not in nasty)

    # --- wide table does not scroll the page --------------------------------------------
    check("the table sits in an overflow-x container so the body never scrolls",
          '.tablewrap{overflow-x:auto}' in h.replace(" ", ""))

    # --- deterministic ------------------------------------------------------------------
    check("the same pool renders identically twice",
          page.render_html(pool, now=NOW) == page.render_html(pool, now=NOW))

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
