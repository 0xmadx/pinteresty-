"""2. Seasonal content calendar — "what to post about, and when".

`moment/available` is the only endpoint on the whole surface that is forward-looking. It
returns, per moment: when interest takes off, when it peaks, how long the peak lasts, the
same three numbers for last year, and a phase label. That is a publishing calendar that
needs no modelling on our side — the dates are given, the lead time is subtraction.

Two things this adds on top of the raw calendar:

  * `drift` — this year's takeoff against last year's + 365 days, the only sanity check
    available on Pinterest's forward prediction. Measured on US 2026-07-27: every
    approaching moment drifts exactly 0 days, i.e. the prediction IS last year's date plus
    365. Worth knowing before treating it as a forecast — for the moments already past this
    cycle Pinterest echoes the same timestamp into both blocks, and `drift` is None rather
    than a fake -365.
  * `.ics` export — the output of a calendar product is a calendar, not a table.

Region coverage is narrower than it looks, and the rule is not the one in §3 of the README.
Measured on 2026-07-27:

    US CA BR MX IT ES FR DE   single country  -> moments AND takeoff/peak timestamps
    GB+IE  DE+AT+CH  MX+AR+CO+CL   grouped    -> moment names only, EVERY takeoff null
    JP                                        -> 200 with an empty list
    AU NL IE GB ZZ                            -> 400

So a grouped region returns a calendar with no dates in it, and there is no way to get UK
timings at all: `GB` and `IE` are both rejected and `GB+IE` carries no timestamps. Moments
with no takeoff are still returned by `plan()`, flagged `basis="occurrence"` and status
`"no ramp data"` — dropping them made a whole region silently return an empty calendar,
which reads identically to "nothing is coming up".

    .venv/Scripts/python.exe pinterest/products/content_calendar.py US --ics
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.local_math import launch_plan

OUT_DIR = Path(__file__).resolve().parents[1] / "data"

# How far ahead of takeoff content has to exist to be indexed by the ramp. Pinterest's own
# seller guidance is 6-8 weeks; 6 is the aggressive end and is what we default to.
LEAD_WEEKS = 6


def _dt(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc) if ms else None


def plan(api, country="US", lead_weeks=LEAD_WEEKS, with_terms=False, now=None):
    """Every moment for a region as a dated publishing plan, soonest deadline first.

    `with_terms` costs one extra request per moment: `top_trends_filtered` accepts
    `moments=<name>` and re-ranks the table inside that moment, which turns "Halloween is
    approaching" into "these are the Halloween terms moving right now". The moment
    vocabulary is per-region and validated server-side, so the names must come from this
    same calendar — a name from another region is a 400, not an empty result.
    """
    moments = api.moments_calendar(country) or []
    now = now or datetime.now(timezone.utc)
    rows = []
    for m in moments:
        p = launch_plan(m, lead_weeks, now) or _dateless(m)
        p["country"] = country
        if not p.get("takeoff"):
            rows.append(p)
            continue
        p["basis"] = "takeoff"
        p["occurrence"] = (_dt(m.get("next_occurrence_ms")).date().isoformat()
                           if m.get("next_occurrence_ms") else None)
        p["drift_days"] = p.pop("takeoff_drift_days")
        p["status"] = _status(p, m, now)
        if with_terms:
            table = api.top_trends("seasonal", country=country, moments=[m["moment"]])
            p["terms"] = [r["term"] for r in (table or {}).get("values", [])][:10]
        rows.append(p)
    # Dateless rows sort last on their occurrence date — they still belong in the output,
    # just below everything with a real deadline.
    return sorted(rows, key=lambda r: (r["list_by"] is None,
                                       r["list_by"] or r.get("occurrence") or "9999"))


def _dateless(moment):
    """A moment the region gives no takeoff for.

    Returned rather than dropped: silently emitting an empty calendar for a whole region
    is the worst outcome here, because it looks identical to "nothing is coming up".
    `next_occurrence_ms` is NOT used as a substitute — measured against the moments that
    have both, the takeoff-to-occurrence gap ranges from 16 to 468 days, because the
    occurrence field sometimes points at next year's date while takeoff points at this
    cycle's. There is no constant to subtract.
    """
    occurrence = _dt(moment.get("next_occurrence_ms"))
    return {
        "moment": moment.get("moment"),
        "phase": moment.get("phase"),
        "basis": "occurrence",
        "list_by": None,
        "takeoff": None,
        "peak": None,
        "peak_length_days": moment.get("peak_length_days"),
        "weeks_left": None,
        "drift_days": None,
        "occurrence": occurrence.date().isoformat() if occurrence else None,
        "status": "no ramp data",
    }


def _status(p, moment, now):
    """What a planner actually needs to read off the row.

    'late' is the case worth surfacing: the moment has not taken off yet, but the window in
    which publishing still gets indexed before the ramp has already closed.
    """
    takeoff = _dt(moment.get("takeoff_ms"))
    if moment.get("phase") == "ended":
        return "ended"
    if p["weeks_left"] > 0:
        return "on time" if p["weeks_left"] > 2 else "closing"
    return "late" if takeoff and takeoff > now else "in flight"


def upcoming(rows, weeks=12):
    """Just the moments whose listing deadline falls inside the planning horizon."""
    return [r for r in rows
            if r["weeks_left"] is not None and 0 <= r["weeks_left"] <= weeks]


def to_ics(rows, path=None):
    """Two all-day events per moment: the listing deadline and the takeoff itself.

    Written by hand rather than with a library — the format is six lines of boilerplate and
    the alternative is a dependency for string concatenation. Times are dates (VALUE=DATE),
    so no timezone handling is needed at all.
    """
    path = Path(path or OUT_DIR / "pinterest_content_calendar.ics")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//pinterest-trends//content-calendar//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Pinterest trend moments"]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for r in rows:
        for kind, date in (("PUBLISH BY", r["list_by"]), ("TAKEOFF", r["takeoff"])):
            if not date:
                continue
            compact = date.replace("-", "")
            end = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y%m%d")
            lines += [
                "BEGIN:VEVENT",
                f"UID:{kind.replace(' ', '')}-{r['moment']}-{compact}@pinterest-trends",
                f"DTSTAMP:{stamp}",
                f"DTSTART;VALUE=DATE:{compact}",
                f"DTEND;VALUE=DATE:{end}",
                f"SUMMARY:{kind}: {r['moment']}",
                f"DESCRIPTION:phase {r['phase']} | peak {r['peak']} "
                f"({r['peak_length_days']}d) | drift vs last year {r['drift_days']}d",
                "END:VEVENT",
            ]
    lines.append("END:VCALENDAR")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return path


def report(country="US", ics=False, with_terms=False):
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}  |  region {country}\n")
        rows = plan(api, country, with_terms=with_terms)
        print(f"{'moment':18} {'publish by':12} {'takeoff':12} {'wks':>5}  {'drift':>6}  status")
        for r in rows:
            drift = f"{r['drift_days']:+d}d" if r["drift_days"] is not None else "   n/a"
            weeks = f"{r['weeks_left']:>5}" if r["weeks_left"] is not None else "    -"
            print(f"{r['moment']:18} {r['list_by'] or '-':12} {r['takeoff'] or '-':12} "
                  f"{weeks}  {drift:>6}  {r['status']}")
            if r.get("terms"):
                print(f"    terms: {', '.join(r['terms'][:6])}")
        if ics:
            print(f"\nSaved {to_ics(rows)}")
        return rows


if __name__ == "__main__":
    args = sys.argv[1:]
    country = next((a for a in args if not a.startswith("-")), "US")
    report(country, ics="--ics" in args, with_terms="--terms" in args)
