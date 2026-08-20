"""The home index — one entry point that ties the screens together.

    .venv/Scripts/python.exe -m etsy.ui.home
    -> etsy/data/ui/index.html   (open this; everything links from here)

Until now the UI was scattered files — calendar.html, discover.html, a cockpit per
term — and the operator had to know which to open. This is the front page: the two
standing screens, a cockpit for every watched term, and a short "what needs a look"
digest pulled from the same database the screens read.

It renders every watched term's cockpit as a side effect, so opening the index is
enough to have a fresh page for each. All database-only; no live calls, same
contract as the screens it links.

WHAT THE DIGEST SURFACES, AND WHY IN THIS ORDER
-----------------------------------------------
1. What is BLOCKED on the operator — unconfirmed settings, no launches. These gate
   the trustworthiness of everything below, so they come first and are stated
   plainly rather than buried.
2. What is due NOW — moments whose list-by deadline is here.
3. What is worth a look — the winnable terms Discover found.

The digest never invents urgency. A quiet week says so; it does not manufacture a
"top pick" to fill the space.
"""
import html
import os
from datetime import datetime, timezone

from etsy.analytics import calendar as cal

OUT_DIR = os.path.join("etsy", "data", "ui")


def _settings_blockers():
    """The operator-only gates, read from settings. Each makes verdicts provisional."""
    from core.settings_store import load
    settings = load()
    out = []
    # `basis()` is the accessor; a bare `.confirmed` attribute does not exist, and
    # reading one via getattr would make this blocker fire forever even after the
    # operator confirmed everything (which it did, silently, until 2026-08-20).
    if settings.basis()["basis"] != "operator":
        missing = ", ".join(settings.basis()["unconfirmed"])
        out.append(f"Fee/cost inputs are DEFAULTS — every profit verdict is "
                   f"provisional until confirmed ({missing}). "
                   f"settings_store set <field> <value>.")
    shops = settings.shop_names()
    if shops and len(shops) < 3:
        out.append(f"Only {len(shops)} competitor shop(s) tracked, and tracking only "
                   f"winners teaches what winners do — add one in the low hundreds "
                   f"of sales (B-01).")
    return out


def _due_now(db_path, lead_weeks, now):
    from etsy.engines.calendar_engine import latest_moments
    rows = cal.build(latest_moments(db_path), terms=[], lead_weeks=lead_weeks, now=now)
    return [r for r in rows if r["state"] == cal.LIST_NOW]


def _worth_a_look(db_path, limit=6):
    from core.database import MarketDatabase
    pool = MarketDatabase(db_path).latest_discovered(2000)
    return [r for r in pool if r.get("verdict") in ("winnable", "contested")][:limit]


def _launches(db_path):
    """How far the LEARN loop is from starting. 0 launches is the headline number."""
    try:
        from core.graph_db import GraphDB
        return GraphDB().launch_count()
    except Exception:
        return None


def _cockpit_slug(keyword):
    from etsy.ui.cockpit_page import _slug
    return _slug(keyword)


def build_digest(db_path, terms, lead_weeks, now):
    blockers = list(_settings_blockers())
    launches = _launches(db_path)
    if launches == 0:
        blockers.append("No launches recorded — the LEARN loop cannot start, and "
                        "the scorer stays uncalibrated until 10 launches exist.")
    return {
        "blockers": blockers,
        "due_now": _due_now(db_path, lead_weeks, now),
        "worth_a_look": _worth_a_look(db_path),
        "terms": terms,
    }


def render_html(digest, now=None):
    now = now or datetime.now(timezone.utc)

    blockers = "".join(f"<li>{html.escape(b)}</li>" for b in digest["blockers"])
    blockers_block = (f'''
      <section class="card blocked">
        <h2>Blocked on you</h2>
        <p class="lead">These gate the trustworthiness of everything below.</p>
        <ul>{blockers}</ul>
      </section>''' if digest["blockers"] else '''
      <section class="card ok">
        <h2>Nothing blocked on you</h2>
        <p class="lead">Settings confirmed, shops tracked, launches recorded.</p>
      </section>''')

    due = digest["due_now"]
    if due:
        items = "".join(
            f'<li><strong>{html.escape(r["moment"]).title()}</strong> — '
            f'list by {r["list_by"]}'
            + (f' · {html.escape(", ".join(e["term"] for e in r["evidence"]))}'
               if r.get("evidence") else " · nothing watched aimed at it")
            + '</li>' for r in due)
        due_block = f'<section class="card"><h2>Due now</h2><ul>{items}</ul></section>'
    else:
        due_block = ('<section class="card"><h2>Due now</h2>'
                     '<p class="lead">No deadline is here this week.</p></section>')

    look = digest["worth_a_look"]
    if look:
        items = "".join(
            f'<li><strong>{html.escape(r["term"])}</strong> '
            f'<span class="ratio">{r["demand_per_listing"]:.3f}</span> '
            f'<span class="meta">{r.get("verdict","")} · from '
            f'{html.escape(r.get("seed") or "")}</span></li>' for r in look)
        look_block = (f'<section class="card"><h2>Worth a look</h2>'
                      f'<p class="lead">Discovered terms you did not type, ranked by '
                      f'winnability.</p><ul class="terms">{items}</ul>'
                      f'<p class="more"><a href="discover.html">All discovered '
                      f'terms →</a></p></section>')
    else:
        look_block = ('<section class="card"><h2>Worth a look</h2>'
                      '<p class="lead">No winnable terms discovered yet. '
                      '<a href="discover.html">Run discover →</a></p></section>')

    cockpits = "".join(
        f'<li><a href="cockpit-{_cockpit_slug(t)}.html">{html.escape(t)}</a></li>'
        for t in digest["terms"])

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market intelligence — home</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9; --line:#D5DCD7;
  --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65;
  --accent:#14666E; --bad:#9E3B26; --bad-bg:#F6E3DD; --good:#2F6B45;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28; --line:#2B3835;
  --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0;
  --accent:#5FBCC4; --bad:#E68469; --bad-bg:#33201B; --good:#7CB795;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:920px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:32px;letter-spacing:-.02em;margin:0 0 4px}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 22px}}
.nav{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:26px}}
.nav a{{background:var(--surface);border:1px solid var(--line);border-radius:8px;
  padding:12px 18px;text-decoration:none;color:var(--ink);font-weight:600;
  border-bottom:3px solid var(--accent)}}
.nav a:hover{{background:var(--surface-2)}}
.nav a span{{display:block;font-size:12px;font-weight:400;color:var(--ink-3);
  margin-top:1px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin-bottom:16px}}
.card.blocked{{border-left:4px solid var(--bad)}}
.card.ok{{border-left:4px solid var(--good)}}
.card h2{{margin:0 0 4px;font-size:17px;letter-spacing:-.01em}}
.lead{{margin:0 0 10px;color:var(--ink-2);font-size:13.5px}}
.card ul{{margin:0;padding-left:20px}}
.card li{{margin-bottom:5px;color:var(--ink-2);font-size:14px}}
.card li strong{{color:var(--ink)}}
.blocked li{{color:var(--ink)}}
.terms li{{list-style:none;margin-left:-20px;display:flex;gap:9px;
  align-items:baseline;flex-wrap:wrap}}
.ratio{{font-weight:700;color:var(--good);font-variant-numeric:tabular-nums}}
.meta{{font-size:12px;color:var(--ink-3)}}
.more{{margin:10px 0 0;font-size:13px}}
a{{color:var(--accent)}}
.cockpits{{columns:2;column-gap:24px}}
.cockpits li{{list-style:none;margin-bottom:4px}}
footer{{margin-top:24px;padding-top:14px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px;max-width:70ch}}
</style></head><body><div class="wrap">
<h1>Market intelligence</h1>
<p class="stamp">Home · generated {now.strftime("%Y-%m-%d %H:%M UTC")} · everything
  reads the database, rebuilt daily by the scheduler</p>

<nav class="nav">
  <a href="calendar.html">Calendar<span>what to list, and by when</span></a>
  <a href="discover.html">Discover<span>terms worth a look</span></a>
  <a href="market.html">Market<span>competitor shop window</span></a>
  <a href="calendar.ics">Calendar feed<span>.ics for your calendar app</span></a>
</nav>

{blockers_block}
{due_block}
{look_block}

<section class="card">
  <h2>Candidates</h2>
  <p class="lead">A cockpit for every watched term — three sources, then a verdict.</p>
  <ul class="cockpits">{cockpits}</ul>
</section>

<footer>
  Nothing here is a recommendation. The Cockpit weighs one candidate's demand,
  timing, competition and profit; Discover shows where to look. Every profit
  figure is provisional until the operator's real fees and costs are confirmed.
</footer>
</div></body></html>'''


def write(out_dir=OUT_DIR, db_path="market_intelligence.db", lead_weeks=6,
          now=None, render_cockpits=True):
    """Render the index, and a fresh cockpit for every watched term."""
    from core.settings_store import load
    from etsy.ui import cockpit_page, market_page

    terms = load().terms()
    os.makedirs(out_dir, exist_ok=True)

    # The competitor window, refreshed alongside the index.
    try:
        market_page.write(out_dir=out_dir, db_path=db_path, now=now)
    except Exception as e:
        print(f"[!] market page not rendered: {e}")

    if render_cockpits:
        for term in terms:
            try:
                cockpit_page.write(term, out_dir=out_dir)
            except Exception as e:
                print(f"[!] cockpit for '{term}' not rendered: {e}")

    digest = build_digest(db_path, terms, lead_weeks, now)
    path = os.path.join(out_dir, "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(digest, now=now))
    return {"index": path, "cockpits": len(terms)}


def main():
    result = write()
    print(f"[+] {result['index']}   <- open this; everything links from here")
    print(f"    {result['cockpits']} cockpit page(s) refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
