"""The Cockpit screen — one candidate, rendered.

    .venv/Scripts/python.exe -m etsy.ui.cockpit_page "christmas ornament"
    -> etsy/data/ui/cockpit-christmas-ornament.html

Same reasoning as the calendar screen: no read API exists, so this is a generated
page rather than a React view. See `etsy/ui/calendar_page.py` for the full note.

The layout is the argument. Three source panels sit side by side, each with its
own reading, and the verdict comes LAST and below them. That ordering is B-05 made
physical: a reader cannot reach the conclusion without passing the evidence, and a
disagreement between sources is a banner rather than a footnote.
"""
import html
import os
from datetime import datetime, timezone

from etsy.analytics import profit
from etsy.engines import cockpit

OUT_DIR = os.path.join("etsy", "data", "ui")


def _slug(keyword):
    return "".join(c if c.isalnum() else "-" for c in keyword.lower()).strip("-")


def _panel(title, subtitle, body, state="ok"):
    return f'''
      <section class="panel {state}">
        <div class="panel-head">
          <span class="panel-title">{title}</span>
          <span class="panel-sub">{subtitle}</span>
        </div>
        {body}
      </section>'''


def _timing_panel(t):
    if t["basis"] != "measured":
        return _panel("Pinterest", "when",
                      f'<p class="empty">{html.escape(t["note"])}</p>', "unknown")
    late = '<span class="flag">late</span>' if t.get("is_late") else ""
    return _panel("Pinterest", "when", f'''
        <div class="big">{html.escape(t["moment"]).title()}{late}</div>
        <dl class="facts">
          <div><dt>List by</dt><dd>{t["list_by"]}</dd></div>
          <div><dt>Peak</dt><dd>{t.get("peak") or "—"}</dd></div>
        </dl>
        <p class="note">{html.escape(t["reason"])}</p>''')


def _demand_panel(d):
    if d["basis"] != "measured":
        return _panel("Etsy Private", "demand",
                      f'<p class="empty">{html.escape(d["note"])}</p>', "unknown")

    cvr_default = d.get("cvr_basis") != "measured"
    cvr_cls = "derived" if cvr_default else "measured"
    cvr_note = "DEFAULT — a guess" if cvr_default else "measured"
    band = (f'${d["price_low"]}–{d["price_high"]}' if d.get("price_low")
            else "no price returned")

    tr = d["trend"]
    if tr["basis"] == "measured":
        arrow = "▲" if tr["change"] > 0 else "▼"
        noise = ' <span class="note">(within noise)</span>' if not tr["material"] else ""
        trend = (f'<p class="trend"><strong>{arrow} {abs(tr["change"]):.0%}</strong> '
                 f'over {tr["days"]} days — {tr["from"]:,} → {tr["to"]:,}{noise}</p>')
    else:
        # A refused comparison is the more interesting case and gets the same
        # weight as a measured one, not a smaller font.
        trend = f'<p class="refused">{html.escape(tr["note"])}</p>'

    return _panel("Etsy Private", "demand", f'''
        <div class="big">{d["volume"]:,}<span class="unit"> searches/mo</span></div>
        <dl class="facts">
          <div><dt>CVR</dt><dd class="{cvr_cls}">{d["cvr"]:.5f} <span
            class="basis">{cvr_note}</span></dd></div>
          <div><dt>Median band</dt><dd>{band}</dd></div>
        </dl>
        {trend}
        <p class="note">{d["readings"]} reading(s)</p>''')


def _supply_panel(s):
    if s["basis"] != "measured":
        return _panel("Etsy Public", "competition",
                      f'<p class="empty">{html.escape(s["note"])}</p>', "unknown")
    wall = s.get("is_wall")
    return _panel("Etsy Public", "competition", f'''
        <div class="big">{s["listings"]:,}<span class="unit"> listings</span></div>
        <dl class="facts">
          <div><dt>Demand per listing</dt>
            <dd class="{'bad' if wall else 'good'} derived">
              {s["demand_per_listing"]:.3f}
              <span class="basis">derived</span></dd></div>
        </dl>
        {'<p class="wall">You cannot rank here — supply overwhelms demand.</p>'
         if wall else '<p class="note">Rankable on the demand/supply ratio.</p>'}''',
                  "bad" if wall else "good")


def render_html(state, now=None):
    now = now or datetime.now(timezone.utc)
    c = state["combined"]
    kw = html.escape(state["keyword"])

    conflicts = "".join(
        f'<div class="conflict"><strong>Sources disagree</strong>'
        f'<p>{html.escape(x)}</p></div>' for x in c["conflicts"])
    blockers = "".join(f"<li>{html.escape(b)}</li>" for b in c["blockers"])

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{kw} — cockpit</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9; --line:#D5DCD7;
  --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65;
  --good:#2F6B45; --bad:#9E3B26; --bad-bg:#F6E3DD; --derived:#5B4C8A;
  --warn:#8A6417; --warn-bg:#F3EAD3;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28; --line:#2B3835;
  --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0;
  --good:#7CB795; --bad:#E68469; --bad-bg:#33201B; --derived:#A996DC;
  --warn:#D9B762; --warn-bg:#2C2617;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:1040px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 26px}}

.panels{{display:grid;gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(268px,1fr));margin-bottom:20px}}
.panel{{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:15px 16px;border-top:3px solid var(--line)}}
.panel.good{{border-top-color:var(--good)}}
.panel.bad{{border-top-color:var(--bad)}}
.panel.unknown{{border-top-color:var(--ink-3)}}
.panel-head{{display:flex;align-items:baseline;gap:8px;margin-bottom:10px}}
.panel-title{{font-weight:650;letter-spacing:-.01em}}
.panel-sub{{font-size:11px;letter-spacing:.08em;text-transform:uppercase;
  color:var(--ink-3)}}
.big{{font-size:27px;font-weight:700;letter-spacing:-.02em;
  font-variant-numeric:tabular-nums;line-height:1.15;margin-bottom:9px}}
.unit{{font-size:13px;font-weight:400;color:var(--ink-3)}}
.flag{{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--bad);border:1px solid var(--bad);padding:2px 6px;border-radius:4px;
  margin-left:8px;vertical-align:middle}}
.facts{{margin:0 0 9px;display:flex;flex-direction:column;gap:6px}}
.facts div{{display:flex;justify-content:space-between;gap:10px;align-items:baseline}}
.facts dt{{font-size:12px;color:var(--ink-3)}}
.facts dd{{margin:0;font-weight:600;font-variant-numeric:tabular-nums;text-align:right}}
.facts dd.good{{color:var(--good)}} .facts dd.bad{{color:var(--bad)}}
.basis{{display:block;font-size:10.5px;font-weight:400;color:var(--ink-3)}}
/* derived must not look like measured */
dd.derived .basis{{color:var(--derived);font-style:italic}}
.note{{font-size:12.5px;color:var(--ink-3);margin:0}}
.trend{{font-size:13px;color:var(--ink-2);margin:0 0 6px}}
.refused{{font-size:12.5px;color:var(--warn);background:var(--warn-bg);
  border-radius:5px;padding:7px 9px;margin:0 0 6px}}
.wall{{font-size:12.5px;color:var(--bad);background:var(--bad-bg);
  border-radius:5px;padding:7px 9px;margin:0}}
.empty{{font-size:13px;color:var(--ink-2);margin:0}}

.conflict{{background:var(--warn-bg);border:1px solid var(--warn);
  border-radius:8px;padding:13px 15px;margin-bottom:14px}}
.conflict strong{{color:var(--warn);display:block;font-size:12px;
  letter-spacing:.07em;text-transform:uppercase;margin-bottom:4px}}
.conflict p{{margin:0;font-size:13.5px;color:var(--ink-2)}}

.verdict{{background:var(--surface);border:1px solid var(--line);
  border-left:4px solid var(--{'bad' if c["call"] == "no" else 'good'});
  border-radius:8px;padding:16px 18px}}
.verdict h2{{margin:0 0 8px;font-size:20px;letter-spacing:-.01em}}
.verdict ul{{margin:0 0 8px;padding-left:20px;color:var(--ink-2);font-size:13.5px}}
.verdict li{{margin-bottom:3px}}
.provisional{{font-size:12px;color:var(--derived);font-style:italic;margin:0}}
footer{{margin-top:28px;padding-top:15px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12.5px;max-width:74ch}}
</style></head><body><div class="wrap">
<h1>{kw}</h1>
<p class="stamp">{state["product_type"]} product · generated
  {now.strftime("%Y-%m-%d %H:%M UTC")} · read from the database, no live calls</p>

<div class="panels">
  {_timing_panel(state["timing"])}
  {_demand_panel(state["demand"])}
  {_supply_panel(state["supply"])}
</div>

{conflicts}

<div class="verdict">
  <h2>Verdict: {c["call"]}</h2>
  {f"<ul>{blockers}</ul>" if blockers else "<p>Nothing blocking on the measured evidence.</p>"}
  <p class="provisional">{html.escape(c["basis"])}</p>
</div>

<footer>
  The three panels come first on purpose: each source is read on its own before
  anything combines them, because they fail differently. Pinterest can time a term
  nobody searches; Etsy Private can report healthy volume for a term with two
  million listings. When they disagree, that is the finding — not something to
  average away.
</footer>
</div></body></html>'''


def write(keyword, out_dir=OUT_DIR, state=None, now=None, **kw):
    state = state or cockpit.build(keyword, **kw)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"cockpit-{_slug(keyword)}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(state, now=now))
    return path


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="cockpit_page")
    parser.add_argument("keyword")
    parser.add_argument("--type", default=profit.PERSONALIZED,
                        choices=list(profit.PRODUCT_TYPES))
    args = parser.parse_args(argv)
    path = write(args.keyword, product_type=args.type)
    print(f"[+] {path}   <- open in a browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
