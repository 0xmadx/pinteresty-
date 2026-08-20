"""The home index: the digest surfaces blockers first, and never invents urgency.

The whole reason this page exists is that scattered files hid the two things the
operator most needs to see: what is blocked on them (which makes everything else
provisional), and what is actually due. So the tests are about the digest's honesty
— that blockers come first, that a quiet week says so, and that the cockpit links
resolve to files the index actually generates.

    .venv/Scripts/python.exe -m etsy.ui.test_home
"""
from datetime import datetime, timezone

from etsy.ui import home

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


def digest(**kw):
    base = {
        "blockers": ["Fees are DEFAULTS — every profit verdict is provisional.",
                     "No launches recorded — the LEARN loop cannot start."],
        "due_now": [{"moment": "thanksgiving", "list_by": "2026-08-26",
                     "state": "list_now", "evidence": []}],
        "worth_a_look": [{"term": "custom family name necklace",
                          "demand_per_listing": 1.744, "verdict": "winnable",
                          "seed": "mom necklace"}],
        "terms": ["mom necklace", "felt garland"],
    }
    base.update(kw)
    return base


def main():
    print()
    h = home.render_html(digest(), now=NOW)

    # --- blockers come first, and are stated plainly ---------------------------------
    check("the blocked-on-you card exists", "Blocked on you" in h)
    check("blockers are listed, not summarised into a badge",
          "every profit verdict is provisional" in h)
    check("blockers sit ABOVE the opportunities — provisional gates everything",
          h.index("Blocked on you") < h.index("Worth a look"))

    # --- a clean slate is not faked into a blocker -------------------------------------
    print()
    clean = home.render_html(digest(blockers=[]), now=NOW)
    check("no blockers renders an explicit all-clear, not a blank card",
          "Nothing blocked on you" in clean)
    check("and does not show the blocked styling",
          'class="card blocked"' not in clean)

    # --- urgency is reported, never invented ------------------------------------------
    print()
    quiet = home.render_html(digest(due_now=[], worth_a_look=[]), now=NOW)
    check("a week with no deadline says so", "No deadline is here" in quiet)
    check("and no winnable terms says so, with a way to look",
          "No winnable terms discovered" in quiet and "discover" in quiet)
    check("nothing is fabricated to fill the space",
          "custom family name" not in quiet)

    # --- the due list carries the honest 'nothing aimed at it' ------------------------
    print()
    check("a due moment with no watched term says nothing is aimed at it",
          "nothing watched aimed at it" in h)

    # --- worth-a-look shows winnability, from the seed, and links onward --------------
    print()
    check("a discovered term shows its ratio", "1.744" in h)
    check("and the seed it came from", "mom necklace" in h)
    check("with a link to the full Discover screen", 'href="discover.html"' in h)

    # --- cockpit links resolve to files the writer generates --------------------------
    print()
    check("every watched term gets a cockpit link",
          'href="cockpit-mom-necklace.html"' in h
          and 'href="cockpit-felt-garland.html"' in h)
    check("the slug matches cockpit_page's, so the link is not dead",
          home._cockpit_slug("Mom Necklace") == "mom-necklace")

    # --- the standing screens are reachable -------------------------------------------
    print()
    check("the calendar is linked", 'href="calendar.html"' in h)
    check("the discover screen is linked", 'href="discover.html"' in h)
    check("the .ics feed is linked", 'href="calendar.ics"' in h)

    # --- themes, escaping, determinism -------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))
    nasty = home.render_html(digest(terms=["<script>x</script>"]), now=NOW)
    check("a watched term name cannot inject markup", "<script>x" not in nasty)
    check("the same digest renders identically twice",
          home.render_html(digest(), now=NOW) == home.render_html(digest(), now=NOW))

    check("the footer says nothing here is a recommendation",
          "Nothing here is a recommendation" in h)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
