"""The Discover screen — the ranked candidate pool, terms the operator never typed.

    .venv/Scripts/python.exe -m etsy.ui.discover_page
    -> etsy/data/ui/discover.html

Reads the latest discover_sweep from the database (no live calls, same contract as
the other screens). Each watched seed is expanded into ~120 long-tail neighbours,
every one sized for winnability, and the pool is ranked by DEMAND PER LISTING, not
by search volume (D-31) — because a term with two million listings is a wall
however large its traffic.

WHAT LEADS, AND WHAT IS FOLDED AWAY
-----------------------------------
The winnable and contested terms lead, in full. The walls — usually the vast
majority — are folded into a single honest count rather than listed. A screen that
opens with four hundred dead-ends buries the seven that matter, and "these are all
walls" is worth exactly one line, not four hundred.

That fold is a display choice, not a filter: every candidate is stored (see
discover_sweep), and the count of what was hidden is shown, so the reader knows
the pool is larger than what leads.

THE JOIN THAT MAKES IT A CALENDAR
---------------------------------
A discovered term naming a seasonal moment carries its list-by date. "christmas
eve box" is not merely a contested niche; it is one with a deadline. Evergreen
terms say so, rather than leaving the field blank and letting a reader assume it
was not checked.
"""
import html
import os
from datetime import datetime, timezone

OUT_DIR = os.path.join("etsy", "data", "ui")

VERDICT_META = {
    "winnable": ("Winnable", "good", "more searches than listings — a new listing "
                 "can surface"),
    "contested": ("Contested", "warn", "several listings per search — possible, "
                  "not easy"),
    "wall": ("Wall", "bad", "supply overwhelms demand"),
    # Distinct from a wall on purpose (D-43). A wall has too many competitors; this
    # has too few buyers. Ranking effort fixes neither, but the operator reads them
    # differently — "someone else owns this" vs "nobody wants this".
    "weak_intent": ("Weak intent", "bad", "converts far below the other terms "
                    "measured beside it — searched more than it is bought"),
}


def _row(r):
    verdict = r.get("verdict") or "wall"
    _, cls, _ = VERDICT_META.get(verdict, VERDICT_META["wall"])
    term = html.escape(r["term"])
    seed = html.escape(r.get("seed") or "")
    ratio = r.get("demand_per_listing")
    ratio_txt = f"{ratio:.3f}" if ratio is not None else "—"
    moment = ""
    if r.get("moment"):
        m = html.escape(r["moment"]).title()
        by = f" · list by {r['list_by']}" if r.get("list_by") else ""
        moment = f'<span class="moment">{m}{by}</span>'

    vol = f"{r['volume']:,}" if r.get("volume") else "—"
    sup = f"{r['supply']:,}" if r.get("supply") else "—"

    # Pinterest's axis, reported beside Etsy's rather than folded into the verdict.
    # An untracked term shows "—" with a title saying so: Pinterest covers under half
    # this pool, and a dash must never be read as "flat" (N-02).
    mom_v, mom_pct = r.get("momentum"), r.get("momentum_mom")
    if mom_v:
        icon = {"rising": "&#128200;", "fading": "&#128201;", "flat": "&#8594;"}
        pct = f" {mom_pct * 100:+.0f}%" if mom_pct is not None else ""
        m_cls = {"rising": "good", "fading": "bad"}.get(mom_v, "")
        trend = (f'<span class="trend {m_cls}" title="Pinterest, month-over-month">'
                 f'{icon.get(mom_v, "")}{pct}</span>')
    else:
        trend = ('<span class="trend none" title="Pinterest does not track this '
                 'term — unknown, not flat">&mdash;</span>')

    return f'''
      <tr class="{cls}">
        <td class="term">{term}{moment}</td>
        <td class="ratio {cls}">{ratio_txt}</td>
        <td class="num">{vol}</td>
        <td class="num">{sup}</td>
        <td class="num">{trend}</td>
        <td class="seed">{seed}</td>
      </tr>'''


def render_html(pool, now=None):
    now = now or datetime.now(timezone.utc)

    good = [r for r in pool if r.get("verdict") in ("winnable", "contested")]
    rejected = [r for r in pool if r.get("verdict") not in ("winnable", "contested")]
    # Counted apart, because they are folded away for opposite reasons and the
    # operator should be able to see WHICH wall they hit (D-43).
    weak_intent = [r for r in rejected if r.get("verdict") == "weak_intent"]
    walls = [r for r in rejected if r.get("verdict") != "weak_intent"]
    seasonal = [r for r in good if r.get("moment")]

    if pool:
        rows = "".join(_row(r) for r in good)
        body = f'''
        <table>
          <thead><tr>
            <th>Term</th><th>Demand / listing</th><th>Searches</th>
            <th>Listings</th><th>Pinterest</th><th>From seed</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>''' if good else '''
        <p class="empty">Nothing in this pool is winnable or contested — every
          discovered term is a wall. That is a real answer about these seeds: their
          neighbourhoods are saturated. Add a different watched term to expand
          somewhere new.</p>'''
        folds = []
        if walls:
            folds.append(f'{len(walls):,} more term(s) are walls — too many listings '
                         f'to rank against')
        if weak_intent:
            folds.append(f'{len(weak_intent):,} have traffic but weak purchase intent '
                         f'— they convert far below the other terms measured beside '
                         f'them, however few competitors they have')
        fold = (f'<p class="fold">{" · ".join(folds)}. All folded away, not '
                f'filtered.</p>' if folds else "")
        summary = (f"{len(good)} winnable or contested of {len(pool):,} discovered"
                   + (f", {len(seasonal)} seasonal" if seasonal else ""))
    else:
        body = '''
        <p class="empty">No candidates discovered yet. The weekly discover sweep
          expands your watched terms into their long-tail neighbourhoods:</p>
        <code>python -m core.scheduler --force discover</code>'''
        fold = ""
        summary = "empty pool"

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discover — terms worth a look</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9; --line:#D5DCD7;
  --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65;
  --good:#2F6B45; --good-bg:#E1EDE5; --warn:#8A6417; --warn-bg:#F3EAD3;
  --bad:#9E3B26; --seasonal:#3A5A8A;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28; --line:#2B3835;
  --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0;
  --good:#7CB795; --good-bg:#1B2A21; --warn:#D9B762; --warn-bg:#2C2617;
  --bad:#E68469; --seasonal:#8AAEDC;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:920px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}}
.sub{{color:var(--ink-2);margin:0 0 6px;max-width:64ch}}
.sub strong{{color:var(--ink)}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 24px}}
.tablewrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th{{text-align:left;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);font-weight:600;padding:0 12px 8px;border-bottom:2px solid var(--line)}}
th:nth-child(2),th:nth-child(3),th:nth-child(4){{text-align:right}}
td{{padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:baseline}}
tr.good td{{background:var(--good-bg)}}
.term{{font-weight:600}}
.moment{{display:block;font-size:11.5px;font-weight:500;color:var(--seasonal);
  margin-top:2px}}
.ratio{{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}}
.ratio.good{{color:var(--good)}} .ratio.warn{{color:var(--warn)}}
.ratio.bad{{color:var(--bad)}}
.num{{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink-2)}}
.seed{{font-size:12.5px;color:var(--ink-3)}}
/* Pinterest's axis. `.none` is deliberately muted and dashed — an untracked term is
   unknown, and must not read with the same weight as a measured flat. */
.trend{{font-size:12.5px;font-variant-numeric:tabular-nums}}
.trend.good{{color:var(--good)}}
.trend.bad{{color:var(--bad)}}
.trend.none{{color:var(--ink-3);opacity:.55}}
.fold{{margin:16px 0 0;font-size:13px;color:var(--ink-3);background:var(--surface-2);
  border-radius:6px;padding:11px 13px}}
.empty{{color:var(--ink-2);font-size:14px;max-width:64ch}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;
  background:var(--surface);border:1px solid var(--line);padding:3px 7px;
  border-radius:4px;display:inline-block;margin-top:6px}}
footer{{margin-top:28px;padding-top:15px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12.5px;max-width:70ch}}
</style></head><body><div class="wrap">
<h1>Terms worth a look</h1>
<p class="sub">Your watched terms, expanded into their long-tail neighbourhoods and
  ranked by <strong>demand per listing</strong> — not by search volume. A term with
  two million listings is a wall however large its traffic.</p>
<p class="stamp">Generated {now.strftime("%Y-%m-%d %H:%M UTC")} · {summary} · from the
  database, no live calls</p>
<div class="tablewrap">{body}</div>
{fold}
<footer>
  These are terms you did not type. The strongest here was found by expanding a seed
  that is itself a wall — the winnable ground is in the long tail, not the head
  terms. Nothing is a recommendation until the Cockpit checks its demand, timing
  and profit; this is where to look, not what to make.
</footer>
</div></body></html>'''


def write(out_dir=OUT_DIR, pool=None, now=None, limit=2000):
    from core.database import MarketDatabase
    pool = MarketDatabase().latest_discovered(limit) if pool is None else pool
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "discover.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(pool, now=now))
    return path


def main():
    path = write()
    print(f"[+] {path}   <- open in a browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
