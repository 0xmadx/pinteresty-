"""The Market screen — the competitor shop window.

    .venv/Scripts/python.exe -m etsy.ui.market_page
    -> etsy/data/ui/market.html

The screen the operator asked for directly: "a window to competitor shop names,
and whether the shop you're tracking listed the thing you watch." It answers two
questions per tracked shop:

  1. How fast is the shop growing? — the daily sales delta, which is BOUNDED, not
     a rate, because Etsy's counter is quantised (D and below_resolution).
  2. What did they list that you watch, and is it working? — their listings that
     match a watched term, ranked by review velocity.

WHAT IT REFUSES
---------------
**The sales delta is a bound, never a rate.** Etsy's shop counter steps by 100 at
scale, so a shop showing 25,100 across five days has "not moved" only in the sense
that it sold fewer than one counter step. The screen shows "fewer than N/day", the
honest reading, never "0/day".

**Review velocity is a floor.** Reviews undercount sales by an unknown factor, so
a listing gaining reviews is selling AT LEAST that fast. Listings too new or too
thinly observed to rate say so, at the end, rather than being dropped — the newest
launches are exactly the ones worth seeing early.

**The bias is stated on the page.** Both tracked shops are stars, and tracking
only winners teaches what winners do, not what works (B-01). A screen that ranks
competitor listings without saying so would quietly train the operator on
survivors.
"""
import html
import os
from datetime import datetime, timezone

OUT_DIR = os.path.join("etsy", "data", "ui")


def _shop_block(shop, latest, rate_bound, matched):
    name = html.escape(shop)
    sales = f'{latest["total_sales"]:,}' if latest and latest.get("total_sales") else "—"
    reviews = f'{latest["total_reviews"]:,}' if latest and latest.get("total_reviews") else "—"

    if rate_bound is not None:
        rate = (f'<span class="bound">fewer than {rate_bound:.0f}/day</span>'
                f'<span class="basis">bound — Etsy\'s counter is quantised</span>')
    else:
        rate = ('<span class="bound">—</span>'
                '<span class="basis">not enough readings for a delta</span>')

    if matched:
        rows = "".join(_listing_row(m) for m in matched)
        table = f'''
        <table>
          <thead><tr><th>Their listing (matches a term you watch)</th>
            <th>Matches</th><th>Reviews/day</th><th>Reviews</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>'''
    else:
        table = ('<p class="empty">Nothing this shop lists matches a term you '
                 'watch — or the match has not been swept yet.</p>')

    return f'''
      <section class="shop">
        <div class="shop-head">
          <h2>{name}</h2>
          <dl class="shop-stats">
            <div><dt>Lifetime sales</dt><dd>{sales}</dd></div>
            <div><dt>Reviews</dt><dd>{reviews}</dd></div>
            <div><dt>Sales / day</dt><dd class="rate">{rate}</dd></div>
          </dl>
        </div>
        {table}
      </section>'''


def _listing_row(m):
    title = html.escape((m.get("title") or "untitled")[:70])
    term = html.escape(m.get("matched_term") or "")
    v = m.get("velocity") or {}
    if v.get("basis") == "measured":
        vel = f'{v["velocity"]:.2f}<span class="basis">floor · {v["reviews_gained"]}' \
              f' over {v["window_days"]}d</span>'
        cls = "measured"
    else:
        vel = f'<span class="basis">{html.escape(v.get("basis", "—").replace("_", " "))}</span>'
        cls = "pending"
    reviews = (f'{v["total_reviews"]:,}' if v.get("total_reviews") is not None
               else (f'{m["total_reviews"]:,}' if m.get("total_reviews") is not None
                     else "—"))
    return f'''
      <tr class="{cls}">
        <td class="title">{title}</td>
        <td class="term">{term}</td>
        <td class="vel">{vel}</td>
        <td class="num">{reviews}</td>
      </tr>'''


def render_html(shops_data, now=None, all_stars=True):
    now = now or datetime.now(timezone.utc)

    if not shops_data:
        body = '''
        <section class="shop">
          <p class="empty">No competitor shops tracked yet. Add one and the daily
            sweep starts recording its inventory and growth:</p>
          <code>settings_store shop add SHOPNAME</code>
        </section>'''
    else:
        body = "".join(
            _shop_block(d["shop"], d["latest"], d["rate_bound"], d["matched"])
            for d in shops_data)

    bias = ('''
      <div class="bias">
        <strong>Survivor warning</strong> — every tracked shop is a star seller.
        Ranking their listings teaches what winners do, not what works. Add a shop
        in the low hundreds of sales so failure is visible too (B-01).
      </div>''' if all_stars and shops_data else "")

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Market — competitor shop window</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9; --line:#D5DCD7;
  --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65;
  --accent:#14666E; --good:#2F6B45; --warn:#8A6417; --warn-bg:#F3EAD3;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28; --line:#2B3835;
  --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0;
  --accent:#5FBCC4; --good:#7CB795; --warn:#D9B762; --warn-bg:#2C2617;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:960px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:30px;letter-spacing:-.02em;margin:0 0 4px}}
.sub{{color:var(--ink-2);margin:0 0 6px;max-width:64ch}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 22px}}
.bias{{background:var(--warn-bg);border:1px solid var(--warn);border-radius:8px;
  padding:12px 15px;margin-bottom:20px;font-size:13.5px;color:var(--ink-2)}}
.bias strong{{color:var(--warn);text-transform:uppercase;font-size:12px;
  letter-spacing:.06em}}
.shop{{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:18px 20px;margin-bottom:16px}}
.shop-head{{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;
  align-items:flex-start;margin-bottom:14px}}
.shop-head h2{{margin:0;font-size:19px;letter-spacing:-.01em}}
.shop-stats{{display:flex;gap:22px;margin:0}}
.shop-stats div{{display:flex;flex-direction:column}}
.shop-stats dt{{font-size:10.5px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3);margin:0}}
.shop-stats dd{{margin:0;font-weight:700;font-variant-numeric:tabular-nums;
  font-size:17px}}
.rate .bound{{display:block;font-size:14px;color:var(--warn);font-weight:600}}
.basis{{display:block;font-size:10.5px;font-weight:400;color:var(--ink-3)}}
.tablewrap,table{{width:100%}}
table{{border-collapse:collapse;font-size:13.5px}}
th{{text-align:left;font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;
  color:var(--ink-3);padding:0 10px 7px;border-bottom:2px solid var(--line)}}
th:nth-child(3),th:nth-child(4){{text-align:right}}
td{{padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:baseline}}
tr.pending td{{color:var(--ink-3)}}
.title{{font-weight:500;color:var(--ink)}}
.term{{color:var(--accent);font-size:12.5px}}
.vel{{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}}
.num{{text-align:right;font-variant-numeric:tabular-nums;color:var(--ink-2)}}
.empty{{color:var(--ink-2);font-size:13.5px;margin:0}}
code{{font-family:ui-monospace,Menlo,monospace;font-size:12.5px;
  background:var(--surface-2);border:1px solid var(--line);padding:3px 7px;
  border-radius:4px;display:inline-block;margin-top:6px}}
footer{{margin-top:24px;padding-top:14px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px;max-width:72ch}}
</style></head><body><div class="wrap">
<h1>Competitor shop window</h1>
<p class="sub">The shops you track, and which of their listings match a term you
  watch — ranked by review velocity, which is a <strong>floor</strong> on how fast
  they sell.</p>
<p class="stamp">Generated {now.strftime("%Y-%m-%d %H:%M UTC")} · from the database,
  no live calls</p>
{bias}
{body}
<footer>
  Sales per day is a BOUND, not a rate: Etsy's shop counter steps by 100 at scale,
  so "fewer than 21/day" is the honest reading when it has not visibly moved.
  Review velocity is a FLOOR: reviews undercount sales, so a listing gaining
  reviews sells at least that fast. Listings too new to rate say so rather than
  reading as zero.
</footer>
</div></body></html>'''


def gather(db_path="market_intelligence.db"):
    """Assemble the per-shop data from the database. No live calls."""
    from core.database import MarketDatabase
    from core.settings_store import load
    from etsy.analytics import competitor_tracker as ct

    db = MarketDatabase(db_path)
    shops = load().shop_names()
    out = []
    for shop in shops:
        latest = db.latest_shop_observation(shop)
        history = db.get_shop_history(shop)
        bound = None
        if history:
            last = history[-1]
            if last.get("basis") == "below_resolution":
                bound = last.get("sales_per_day_upper")
            elif last.get("sales_per_day") is not None:
                bound = last.get("sales_per_day")
        ranked = ct.rank_by_outcome(db, shop)
        matched = [r for r in ranked if r.get("matched_term")]
        out.append({"shop": shop, "latest": latest, "rate_bound": bound,
                    "matched": matched})
    return out


def write(out_dir=OUT_DIR, db_path="market_intelligence.db", now=None):
    data = gather(db_path)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "market.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(data, now=now))
    return path


def main():
    print(f"[+] {write()}   <- open in a browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
