"""The Cockpit screen: the layout IS the argument.

Three source panels come before the verdict, physically. A reader cannot reach the
conclusion without passing the evidence, and a disagreement between sources is a
banner rather than a footnote. These tests pin that ordering, because it is the
thing most easily lost in a later redesign.

    .venv/Scripts/python.exe -m etsy.ui.test_cockpit_page
"""
from datetime import datetime, timezone

from etsy.ui import cockpit_page as page

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


def state(**kw):
    base = {
        "keyword": "christmas ornament", "product_type": "personalized",
        "timing": {"basis": "measured", "moment": "christmas", "state": "list_by",
                   "list_by": "2026-09-16", "peak": "2026-12-09", "is_late": False,
                   "reason": "deadline in 3.8 weeks"},
        "demand": {"basis": "measured", "measured_at": "2026-08-19T12:00:00+00:00",
                   "volume": 25477, "cvr": 0.00027, "cvr_basis": "measured",
                   "price_low": 7.2, "price_high": 8.8, "readings": 1,
                   "trend": {"basis": "unmeasured", "note": "one reading"}},
        "supply": {"basis": "measured", "listings": 1405731,
                   "demand_per_listing": 0.0181, "is_wall": True,
                   "competition": {"basis": "measured", "organic_sample": 6,
                       "ranked_ids": 41, "withheld": 2,
                       "decisive": [{"dimension": "quality", "value": "star_seller",
                                     "share": 1.0, "low": 0.61, "high": 1.0}],
                       "upgrade": "2 dimension(s) could not be called from 6 "
                                  "listings; 41 ranked listings are available.",
                       "median_delivery": "15-21 days", "fast_share": 0.02}},
        "profit": None,
        "combined": {"call": "no", "blockers": ["supply overwhelms demand"],
                     "conflicts": ["Pinterest times this well but Etsy says you "
                                   "cannot rank here"],
                     "basis": "provisional — fees and costs are defaults"},
    }
    base.update(kw)
    return base


def main():
    print()
    h = page.render_html(state(), now=NOW)

    # --- the ordering is the argument ------------------------------------------------
    check("Pinterest comes first", h.index("Pinterest") < h.index("Etsy Private"))
    check("then demand, then competition",
          h.index("Etsy Private") < h.index("Etsy Public"))
    check("and the VERDICT comes last — after all three",
          h.index("Etsy Public") < h.index("Verdict:"))
    check("the disagreement sits above the verdict, not in a footnote",
          h.index("Sources disagree") < h.index("Verdict:"))

    # --- provenance is visible and distinguishable -------------------------------------
    print()
    guessed = page.render_html(state(demand={**state()["demand"],
                                             "cvr_basis": "default"}), now=NOW)
    check("a DEFAULT cvr is called a guess on the surface",
          "DEFAULT — a guess" in guessed)
    check("and styled as derived, not measured",
          'class="derived"' in guessed, "no derived class")
    check("derived has a styling rule of its own, so it does not merely say 'derived'",
          "dd.derived .basis" in h, "no dedicated rule for derived provenance")
    check("the verdict states it is provisional", "provisional" in h)

    # --- page-one competition, when present ------------------------------------------
    check("a decisive saturation dimension appears in the supply panel",
          "star_seller" in h and "61%" in h, "saturation not rendered")
    check("the page-one interval is shown, so it does not read as a market share",
          "page-one sample" in h)
    check("the upgrade path is surfaced when the sample is thin",
          "ranked listings are available" in h)
    check("the délai — median delivery — reaches the decision screen",
          "median delivery" in h and "15-21 days" in h)
    check("with the fast-ship share, the opening POD cannot reach",
          "2% ship within a week" in h)

    # --- a wall is unmissable ------------------------------------------------------------
    print()
    check("the wall is stated in words, not only as a number",
          "cannot rank here" in h)
    rankable = page.render_html(
        state(supply={"basis": "measured", "listings": 25031,
                      "demand_per_listing": 2.79, "is_wall": False},
              combined={"call": "yes", "blockers": [], "conflicts": [],
                        "basis": "provisional"}), now=NOW)
    check("a rankable term does not show the wall banner",
          "cannot rank here" not in rankable)
    check("and with no blockers it says so rather than showing an empty list",
          "Nothing blocking" in rankable)

    # --- refusals get weight, not small print --------------------------------------------
    print()
    refused = page.render_html(state(demand={
        **state()["demand"],
        "trend": {"basis": "refused",
                  "note": "the only reading 6.9 days back fell back to a default CVR"}}),
        now=NOW)
    check("a refused trend is rendered as its own block, not a footnote",
          'class="refused"' in refused)
    check("with its reason intact", "fell back to a default CVR" in refused)

    # --- empty states -----------------------------------------------------------------------
    print()
    untimed = page.render_html(state(timing={"basis": "unmeasured",
                                             "note": "no dated moment — untimed"}), now=NOW)
    check("an untimed term says untimed rather than showing a blank date",
          "untimed" in untimed and "list by" not in untimed.lower().split("footer")[0]
          .split("panels")[-1][:400])
    never = page.render_html(state(demand={"basis": "unmeasured",
                                           "note": 'never measured. settings_store term add "x"'}),
                             now=NOW)
    check("an unmeasured term shows no invented volume",
          "searches/mo" not in never)

    # --- themes and escaping -----------------------------------------------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is a media query on tokens", "prefers-color-scheme:dark" in h)
    check("an explicit light choice still wins", ':root:not([data-theme="light"])' in h)
    check("body paints its own ground",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))
    nasty = page.render_html(state(keyword="<script>alert(1)</script>"), now=NOW)
    check("the keyword cannot inject markup", "<script>alert" not in nasty)

    # --- deterministic ------------------------------------------------------------------------
    print()
    check("the same state renders identically twice",
          page.render_html(state(), now=NOW) == page.render_html(state(), now=NOW))
    slug = page._slug("Christmas Ornament / 2026!")
    check("the filename is a safe slug, with trailing separators trimmed",
          slug == "christmas-ornament---2026", slug)
    check("and it contains nothing that could escape a path",
          all(ch.isalnum() or ch == "-" for ch in slug), slug)

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
