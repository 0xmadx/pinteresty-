"""The Calendar screen — the home screen (D-20), rendered to a file.

    .venv/Scripts/python.exe -m etsy.ui.calendar_page
    -> etsy/data/ui/calendar.html   (open it in a browser)
    -> etsy/data/ui/calendar.ics    (import into a real calendar app)

WHY THIS IS A GENERATED PAGE AND NOT A REACT APP
------------------------------------------------
`docs/blueprint/06_ui_structure.md` specifies a React SPA reading
`GET /launch-plans`. **That endpoint does not exist**, and neither does any read
API — the only HTTP server in this repo is `core/cookie_server.py`, which is dead
code nothing imports.

The `ui-builder` skill's first rule is "don't build UI for data the backend
doesn't expose". A SPA here would have nothing to call, so the choice is between
building an HTTP layer plus a node toolchain for one operator checking a page each
morning, or rendering the rows this system already produces.

This renders them. It introduces no server, no build step and no daemon, which
matches how everything else here runs, and it satisfies the read-only contract
absolutely: the page is a file and cannot trigger a fetch by construction. The
scheduler regenerates it daily. When a read API exists, the SPA replaces this
without changing the engine underneath.

WHAT THE PAGE WILL NOT DO
-------------------------
**No mock data, ever.** Every row comes from `calendar_engine.build()`. A moment
with no matching term renders an empty state that says so, rather than a plausible
placeholder.

**Estimates never look like measurements.** A profit verdict computed from default
fees is marked `provisional` on the surface, because `config/settings.json` has
`confirmed: []` and every margin figure is therefore a guess about the operator's
own costs.

**The three sources stay separate (B-05).** Timing is Pinterest, demand and price
are Etsy Private, supply is Etsy Public. They are shown as three readings, not
blended into one number, so a disagreement between them stays visible.

**Freshness travels to the screen.** Each term carries when it was last measured.
A month-old supply count must not look as current as this morning's takeoff date.
"""
import html
import os
from datetime import datetime, timezone

from etsy.analytics import calendar as cal
from etsy.engines import calendar_engine

OUT_DIR = os.path.join("etsy", "data", "ui")

STATE_LABEL = {
    cal.LIST_NOW: ("List now", "now"),
    cal.LIST_BY: ("List by", "soon"),
    cal.WATCHING: ("Watching", "later"),
    cal.UNTIMED: ("Can't tell", "unknown"),
    cal.PASSED: ("Passed", "gone"),
}


def _age(iso, now=None):
    """'3 days ago' — freshness the operator can read at a glance."""
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    days = (( now or datetime.now(timezone.utc)) - then).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


def _term_block(e, now=None):
    """One term, with its three sources kept apart (B-05)."""
    name = html.escape(e["term"])

    if e["basis"] == "unmeasured":
        return f'''
        <div class="term unmeasured">
          <div class="term-name">{name}</div>
          <p class="empty">Never measured. This is <strong>unknown</strong>, not
            zero demand — nothing has looked at it yet.
            <code>settings_store term add "{name}"</code> then run the keyword sweep.</p>
        </div>'''

    ratio = e.get("demand_per_listing")
    wall = e.get("is_wall")
    verdict = ("Can't rank here" if wall else "Rankable")
    vclass = "bad" if wall else "good"

    money = ("clears the margin floor" if e.get("profitable")
             else "fails the margin floor" if e.get("profitable") is False
             else "no measured price")
    mclass = "good" if e.get("profitable") else "bad" if e.get("profitable") is False else "unknown"

    cvr_note = ("measured" if e.get("cvr_basis") == "measured" else "DEFAULT — a guess")

    return f'''
        <div class="term">
          <div class="term-head">
            <span class="term-name">{name}</span>
            <span class="pill {vclass}">{verdict}</span>
          </div>

          <!-- Three sources, deliberately not blended (B-05). -->
          <div class="sources">
            <div class="src">
              <span class="src-label">Etsy Private · demand</span>
              <span class="src-value">{e['volume']:,}<span class="unit"> searches/mo</span></span>
              <span class="src-meta measured">measured · {_age(e.get('measured_at'), now) or 'unknown age'}</span>
            </div>
            <div class="src">
              <span class="src-label">Etsy Public · supply</span>
              <span class="src-value">{e['supply']:,}<span class="unit"> listings</span></span>
              <span class="src-meta measured">measured · estimate, drifts ~0.1%</span>
            </div>
            <div class="src">
              <span class="src-label">Ratio · demand per listing</span>
              <span class="src-value {vclass}">{ratio:.3f}</span>
              <span class="src-meta derived">derived · below 0.20 you cannot rank</span>
            </div>
          </div>

          <div class="money {mclass}">
            <strong>${e['price_low']}–{e['price_high']}</strong> median band —
            {money}
            <span class="provisional">provisional: fees and costs are defaults,
              not yours</span>
          </div>
          <div class="footnote">CVR {e['cvr']:.5f} ({cvr_note})</div>
        </div>'''


def _row(row, now=None):
    label, klass = STATE_LABEL[row["state"]]
    late = '<span class="late">late</span>' if row.get("is_late") else ""
    moment = html.escape(row["moment"]).title()

    if row["evidence"]:
        terms = "".join(_term_block(e, now) for e in row["evidence"])
    else:
        terms = '''
        <div class="term unmeasured">
          <p class="empty">Dated, but nothing you watch belongs to it. That is
            <strong>“we haven’t aimed anything here”</strong>, not “no opportunity”.
            Add a term and it will appear on this row.</p>
        </div>'''

    return f'''
      <article class="row {klass}">
        <header class="row-head">
          <div class="row-title">
            <span class="state">{label}</span>{late}
            <h2>{moment}</h2>
          </div>
          <div class="row-dates">
            <div><span class="k">List by</span><span class="v">{row['list_by']}</span></div>
            <div><span class="k">Peak</span><span class="v">{row.get('peak') or '—'}</span></div>
          </div>
        </header>
        <p class="reason">{html.escape(row['reason'])}</p>
        <div class="terms">{terms}</div>
      </article>'''


def render_html(rows, lead_weeks=6, now=None):
    now = now or datetime.now(timezone.utc)
    actionable = [r for r in rows if r["actionable"]]

    if rows:
        body = "".join(_row(r, now) for r in rows)
        summary = (f"{len(rows)} dated moment(s), {len(actionable)} backed by a "
                   f"measured, rankable term.")
    else:
        body = '''
      <article class="row empty-state">
        <h2>Nothing dated yet</h2>
        <p>The calendar is built from Pinterest takeoff dates. Run the bridge and
           this fills in:</p>
        <code>python -m pinterest.pipelines.trends_bridge</code>
      </article>'''
        summary = "No dated moments."

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calendar — what to list, and by when</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9;
  --line:#D5DCD7; --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65;
  --now:#9E3B26; --now-bg:#F6E3DD;
  --soon:#8A6417; --soon-bg:#F3EAD3;
  --later:#5A6B65; --later-bg:#E6EBE8;
  --good:#2F6B45; --bad:#9E3B26;
  --derived:#5B4C8A;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28;
  --line:#2B3835; --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0;
  --now:#E68469; --now-bg:#33201B;
  --soon:#D9B762; --soon-bg:#2C2617;
  --later:#93A39D; --later-bg:#1E2725;
  --good:#7CB795; --bad:#E68469;
  --derived:#A996DC;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:980px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}}
.sub{{color:var(--ink-2);margin:0 0 6px;max-width:62ch}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 26px}}

.row{{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:16px 18px;margin-bottom:14px}}
.row.now{{border-left:4px solid var(--now)}}
.row.soon{{border-left:4px solid var(--soon)}}
.row.later{{border-left:4px solid var(--later)}}
.row.unknown{{border-left:4px solid var(--ink-3)}}
.row-head{{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
  align-items:flex-start}}
.row-title{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}
.row-title h2{{margin:0;font-size:19px;letter-spacing:-.01em}}
.state{{font-size:11px;letter-spacing:.07em;text-transform:uppercase;
  padding:3px 8px;border-radius:4px;font-weight:600}}
.now .state{{background:var(--now-bg);color:var(--now)}}
.soon .state{{background:var(--soon-bg);color:var(--soon)}}
.later .state,.unknown .state{{background:var(--later-bg);color:var(--later)}}
.late{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--now);border:1px solid var(--now);padding:2px 6px;border-radius:4px}}
.row-dates{{display:flex;gap:20px}}
.row-dates .k{{display:block;font-size:10.5px;letter-spacing:.08em;
  text-transform:uppercase;color:var(--ink-3)}}
.row-dates .v{{font-variant-numeric:tabular-nums;font-weight:600}}
.reason{{color:var(--ink-2);font-size:13.5px;margin:9px 0 14px;max-width:74ch}}

.terms{{display:flex;flex-direction:column;gap:10px}}
.term{{background:var(--surface-2);border-radius:6px;padding:12px 13px}}
.term-head{{display:flex;justify-content:space-between;align-items:center;
  gap:10px;margin-bottom:10px;flex-wrap:wrap}}
.term-name{{font-weight:600}}
.pill{{font-size:11px;padding:2.5px 8px;border-radius:4px;font-weight:600;
  letter-spacing:.03em}}
.pill.good{{background:var(--good);color:var(--surface)}}
.pill.bad{{background:var(--bad);color:var(--surface)}}

.sources{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));
  gap:10px;margin-bottom:11px}}
.src{{display:flex;flex-direction:column;gap:2px}}
.src-label{{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3)}}
.src-value{{font-size:18px;font-weight:650;font-variant-numeric:tabular-nums;
  letter-spacing:-.01em}}
.src-value.good{{color:var(--good)}} .src-value.bad{{color:var(--bad)}}
.unit{{font-size:11.5px;font-weight:400;color:var(--ink-3)}}
.src-meta{{font-size:11px}}
/* measured vs derived must not look alike (rule 2) */
.src-meta.measured{{color:var(--ink-3)}}
.src-meta.derived{{color:var(--derived);font-style:italic}}

.money{{font-size:13px;color:var(--ink-2);padding-top:9px;
  border-top:1px solid var(--line)}}
.money.good strong{{color:var(--good)}} .money.bad strong{{color:var(--bad)}}
.provisional{{display:block;margin-top:3px;font-size:11.5px;color:var(--derived);
  font-style:italic}}
.footnote{{font-size:11.5px;color:var(--ink-3);margin-top:5px}}

.unmeasured .empty,.empty-state p{{color:var(--ink-2);font-size:13px;margin:0;
  max-width:70ch}}
code{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;
  background:var(--surface);border:1px solid var(--line);padding:2px 6px;
  border-radius:4px;display:inline-block;margin-top:6px}}
footer{{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12.5px;max-width:74ch}}
</style></head><body><div class="wrap">
<h1>What to list, and by when</h1>
<p class="sub">Pinterest takeoff dates joined to Etsy demand. Terms are ordered by
  <strong>demand per listing</strong>, never by search volume — a term with two
  million listings is a wall however large its traffic.</p>
<p class="stamp">Generated {now.strftime('%Y-%m-%d %H:%M UTC')} ·
  listing {lead_weeks} weeks before takeoff · {summary}</p>
{body}
<footer>
  Every figure is labelled with where it came from: <span class="src-meta measured">measured</span>
  was read from a source, <span class="src-meta derived">derived</span> was computed from
  measured values. Profit verdicts are <em>provisional</em> until
  <code>config/settings.json</code> holds your real fees, costs and hourly rate —
  until then they use defaults, and a margin built on a guessed fee is wrong in
  the most expensive place. Regenerated daily by the scheduler.
</footer>
</div></body></html>'''


def render_ics(rows, now=None):
    """The list-by deadlines as a real calendar feed.

    Specified in 06_ui_structure.md. Only actionable, dated rows become events —
    an entry for a moment nothing is aimed at would be a reminder to do nothing.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0",
           "PRODID:-//etsy-market-intelligence//calendar//EN", "CALSCALE:GREGORIAN"]
    for r in rows:
        if r["state"] in (cal.PASSED, cal.UNTIMED) or not r.get("list_by"):
            continue
        day = r["list_by"].replace("-", "")
        terms = ", ".join(e["term"] for e in r["evidence"]) or "nothing watched yet"
        out += [
            "BEGIN:VEVENT",
            f"UID:{r['moment'].replace(' ', '-')}-{day}@etsy-market-intelligence",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day}",
            f"SUMMARY:List by — {r['moment'].title()}",
            f"DESCRIPTION:{r['reason']}\\nTerms: {terms}",
            "END:VEVENT",
        ]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def write(out_dir=OUT_DIR, lead_weeks=6, country="US", rows=None, now=None):
    """Render both files. Returns their paths."""
    rows = calendar_engine.build(country=country, lead_weeks=lead_weeks) if rows is None else rows
    os.makedirs(out_dir, exist_ok=True)

    html_path = os.path.join(out_dir, "calendar.html")
    ics_path = os.path.join(out_dir, "calendar.ics")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(rows, lead_weeks=lead_weeks, now=now))
    with open(ics_path, "w", encoding="utf-8") as f:
        f.write(render_ics(rows, now=now))
    return {"html": html_path, "ics": ics_path, "moments": len(rows)}


def main():
    result = write()
    print(f"[+] {result['moments']} moment(s) rendered")
    print(f"    {result['html']}   <- open in a browser")
    print(f"    {result['ics']}    <- import into a calendar app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
