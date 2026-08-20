"""The Calendar screen renders only what was measured.

The `ui-builder` skill's rule is that faking data in the UI is the same sin as the
backend returning a plausible wrong number: "an empty state that says 'rank
tracking starts once you log a launch' is honest; a chart of invented ranks is a
lie the user will trust."

So these tests are mostly about what must NOT appear on the page — a number
without its provenance, an estimate styled like a measurement, or a placeholder
where an empty state belongs.

    .venv/Scripts/python.exe -m etsy.ui.test_calendar_page
"""
from datetime import datetime, timezone

from etsy.analytics import calendar as cal
from etsy.ui import calendar_page as page

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


def measured_term(**kw):
    base = dict(term="christmas ornament", basis="measured",
                measured_at="2026-08-19T23:00:00+00:00",
                volume=25477, supply=1405731, demand_per_listing=0.0181,
                is_wall=True, cvr=0.00031, cvr_basis="measured",
                price_low=7.2, price_high=8.8, profitable=True, margin=0.61,
                profit_basis="provisional")
    base.update(kw)
    return base


def row(**kw):
    base = dict(moment="christmas", state=cal.LIST_BY, list_by="2026-09-16",
                peak="2026-12-09", reason="deadline in 3.9 weeks", is_late=False,
                evidence=[measured_term()], actionable=False)
    base.update(kw)
    return base


def main():
    # --- every number arrives with its provenance ---------------------------------
    print()
    h = page.render_html([row()], now=NOW)
    check("a measured value is labelled measured", 'class="src-meta measured"' in h)
    check("a derived value is labelled derived", 'class="src-meta derived"' in h)
    check("the two are styled differently, not just labelled",
          ".src-meta.derived{" in h.replace(" ", "") or
          ".src-meta.derived {" in h, "derived has no distinct rule")
    check("freshness reaches the screen",
          any(w in h for w in ("today", "yesterday", "days ago")), "no age shown")
    stale = page.render_html([row(evidence=[measured_term(
        measured_at="2026-07-01T00:00:00+00:00")])], now=NOW)
    check("a 50-day-old reading says so, and does not look as current as a fresh one",
          "50 days ago" in stale, "stale reading not aged")
    check("the same data renders identically twice — `now` is threaded, not read "
          "from the clock mid-render",
          page.render_html([row()], now=NOW) == page.render_html([row()], now=NOW))
    check("a provisional profit verdict says so on the surface",
          "provisional" in h and "defaults" in h)

    # --- the three sources are never blended (B-05) --------------------------------
    print()
    check("Etsy Private demand is its own reading", "Etsy Private" in h)
    check("Etsy Public supply is its own reading", "Etsy Public" in h)
    check("and the ratio is shown as derived FROM them, not instead of them",
          h.index("Etsy Private") < h.index("Etsy Public") < h.index("Ratio"))

    # --- a wall is called a wall ----------------------------------------------------
    print()
    check("an unrankable term says so plainly", "Can&#x27;t rank here" in h or
          "Can't rank here" in h, "no wall verdict")
    rankable = page.render_html([row(evidence=[measured_term(is_wall=False,
                                                             demand_per_listing=2.79)])],
                                now=NOW)
    check("a rankable one does not", "Rankable" in rankable)

    # --- empty states teach, they do not fake --------------------------------------
    print()
    nothing = page.render_html([row(evidence=[])], now=NOW)
    check("a dated moment with no term explains what that means",
          "haven" in nothing and "no opportunity" in nothing)
    check("and shows no numbers at all for it",
          "searches/mo" not in nothing, "invented a figure")

    never = page.render_html([row(evidence=[{"term": "christmas garland",
                                             "basis": "unmeasured",
                                             "note": "never measured"}])], now=NOW)
    check("an unmeasured term says UNKNOWN, never zero",
          "unknown" in never.lower() and "not" in never.lower())
    check("and tells the operator what unlocks it", "settings_store term add" in never)

    check("an empty calendar explains how to fill it",
          "trends_bridge" in page.render_html([], now=NOW))

    # --- both themes are defined, and nothing is dark-only ---------------------------
    print()
    check("a light palette exists on bare :root", ":root {" in h)
    check("dark is defined via prefers-color-scheme", "prefers-color-scheme:dark" in h)
    check("the explicit light choice still wins", ':root:not([data-theme="light"])' in h)
    check("body paints its own background, not the host's",
          "body{margin:0;background:var(--ground)" in h.replace(" ", ""))

    # --- escaping --------------------------------------------------------------------
    print()
    nasty = page.render_html([row(moment="<script>alert(1)</script>",
                                  evidence=[measured_term(term="a & b <b>")])], now=NOW)
    check("a moment name cannot inject markup", "<script>alert" not in nasty)
    check("a term name is escaped too", "&amp;" in nasty and "<b>" not in nasty)

    # --- the .ics export ---------------------------------------------------------------
    print()
    ics = page.render_ics([row()], now=NOW)
    check("it is a valid calendar envelope",
          ics.startswith("BEGIN:VCALENDAR") and ics.rstrip().endswith("END:VCALENDAR"))
    check("the deadline becomes the event date", "DTSTART;VALUE=DATE:20260916" in ics)
    check("the summary names the moment", "SUMMARY:List by — Christmas" in ics)
    check("lines are CRLF-terminated as the spec requires", "\r\n" in ics)

    passed_row = row(state=cal.PASSED, moment="easter")
    check("a passed moment is NOT put in the operator's calendar",
          "easter" not in page.render_ics([passed_row], now=NOW).lower())
    untimed = row(state=cal.UNTIMED, moment="independence day")
    check("nor is one we cannot time — a reminder to do nothing is noise",
          "independence" not in page.render_ics([untimed], now=NOW).lower())

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
