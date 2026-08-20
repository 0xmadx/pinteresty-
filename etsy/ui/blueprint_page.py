"""The Blueprint screen — the last mile, from "winnable" to a listing you paste.

    .venv/Scripts/python.exe -m etsy.ui.blueprint_page "custom family name necklace"
    -> etsy/data/ui/blueprint-<slug>.html

DELIBERATELY ON DEMAND, NOT A DAILY SWEEP. Every other screen reads the database
and never calls the network, because a dashboard must render instantly. A blueprint
is different: it is a deliberate action taken once, when the operator has decided to
list something, and it needs the CURRENT page-one tags — stale ones would seed the
listing with last month's competition. So this fetches live (demand + ~6 competitor
listings' tags), builds, and renders. It is a command you run, not a page that must
be fresh on open.

WHAT IT WILL NOT DO — inherited from generators/blueprint.py, and the whole point:

  * It will not hand you an invalid tag. Etsy caps a tag at 20 characters; page-one
    winners routinely exceed it, and copying them blind silently loses the tag. Over-
    long ones are shown struck through with the reason, not quietly dropped.
  * It will not fill all 13 slots with consensus. Shared tags make you relevant AND
    are the most crowded ground — 13 of them lists you where incumbents are strongest
    with nothing they lack (B-01). A thin, honest tag set beats a full, borrowed one.
  * It will not price below the floor. If the market band's midpoint loses money,
    it says NO PRICE CLEARS rather than smoothing it over.

The screen's job is to render that honesty faithfully — including the warnings, which
are the most useful part when a candidate is weak.
"""
import html
import os
import urllib.parse
from datetime import datetime, timezone

OUT_DIR = os.path.join("etsy", "data", "ui")


def _slug(term):
    return "".join(c if c.isalnum() else "-" for c in term.lower()).strip("-")


def gather(term, product_type="personalized", cogs=0.0, labor_minutes=0.0,
           shipping_cost=0.0, n_listings=6):
    """Live: demand, competitor tags, and the built blueprint. Returns the bp dict.

    Raises nothing for a thin result — a candidate with few usable tags produces a
    thin blueprint, and that is the honest output, not an error.
    """
    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.api.public.api import EtsyPublicAPI
    from etsy.analytics import profit, tag_mining
    from etsy.generators import blueprint

    priv, pub = EtsyPrivateAPI(), EtsyPublicAPI()
    d = parse_results_data(priv.get_results_data(term)) or {}
    data = {"volume": d.get("volume"), "supply": d.get("supply"), "cvr": d.get("cvr"),
            "price_low": d.get("price_low"), "price_high": d.get("price_high"),
            "wow_change": d.get("wow_change")}

    url = "https://www.etsy.com/search?" + urllib.parse.urlencode(
        {"q": term, "explicit": "1"})
    serp = pub.parse_search_html(
        pub.session.request("GET", url, headers=pub.headers, platform="etsy").text, term)
    cards = [c for c in (serp.get("cards") or []) if not c.get("is_ad")][:n_listings]

    listings = []
    for c in cards:
        ld = pub.get_listing_data(c["listing_id"])
        if ld and ld.get("tags"):
            listings.append({"tags": ld["tags"], "review_count": c.get("review_count"),
                             "shop_years": c.get("shop_years_on_etsy")})

    consensus = tag_mining.mine_consensus(listings)

    def verdict_for_price(p):
        return profit.verdict(price=p, product_type=product_type, cogs=cogs,
                              shipping_cost=shipping_cost, labor_minutes=labor_minutes)

    bp = blueprint.build(term, data, consensus, verdict_for_price=verdict_for_price,
                         product_type=product_type)
    bp["_sources"] = len(listings)
    return bp


def render_html(bp, now=None):
    now = now or datetime.now(timezone.utc)
    term = html.escape(bp["term"])
    title = bp["title"]
    tags = bp["tags"]
    price = bp["price"]
    market = bp["market"]

    # Momentum is a first-class warning here: a winnable-looking term crashing
    # week-over-week is the thing the operator most needs to see before listing.
    wow = market.get("wow_change")
    momentum = ""
    if wow is not None:
        crashing = wow <= -25
        cls = "danger" if crashing else ("warn" if wow < 0 else "good")
        note = (" — this term is collapsing week-over-week; a good ratio on falling "
                "demand is a trap" if crashing else "")
        momentum = (f'<p class="momentum {cls}">Etsy momentum: '
                    f'<strong>{wow:+.0f}%</strong> week-over-week{html.escape(note)}</p>')

    tag_chips = "".join(
        f'<span class="chip {html.escape(e["source"])}">{html.escape(e["tag"])}</span>'
        for e in tags["detail"])
    rejected = "".join(
        f'<li><s>{html.escape(b["tag"])}</s> — {html.escape(b["reason"])}</li>'
        for b in tags["rejected"])

    price_txt = (f'${price["price"]}' if price.get("price")
                 else "No price clears the floor")
    price_cls = "good" if price.get("price") else "danger"

    warnings = "".join(f"<li>{html.escape(w)}</li>" for w in bp["warnings"])
    checklist = "".join(f"<li>{html.escape(c)}</li>" for c in bp["ctr_checklist"])

    return f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Blueprint — {term}</title>
<style>
:root {{
  --ground:#F1F3F1; --surface:#FFF; --surface-2:#E8ECE9; --line:#D5DCD7;
  --ink:#16211F; --ink-2:#4A5852; --ink-3:#5E6B65; --accent:#14666E;
  --good:#2F6B45; --good-bg:#E1EDE5; --warn:#8A6417; --warn-bg:#F3EAD3;
  --danger:#9E3B26; --danger-bg:#F6E3DD; --chip:#E8ECE9;
}}
@media (prefers-color-scheme:dark) {{ :root:not([data-theme="light"]) {{
  --ground:#0F1716; --surface:#17201F; --surface-2:#1F2A28; --line:#2B3835;
  --ink:#E5ECE9; --ink-2:#A9B7B2; --ink-3:#98A6A0; --accent:#5FBCC4;
  --good:#7CB795; --good-bg:#1B2A21; --warn:#D9B762; --warn-bg:#2C2617;
  --danger:#E68469; --danger-bg:#33201B; --chip:#243230;
}} }}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
  font:15px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased}}
.wrap{{max-width:760px;margin:0 auto;padding:32px 20px 64px}}
h1{{font-size:26px;letter-spacing:-.02em;margin:0 0 4px}}
.stamp{{color:var(--ink-3);font-size:12.5px;margin:0 0 20px}}
.momentum{{border-radius:8px;padding:11px 14px;font-size:13.5px;margin:0 0 20px}}
.momentum.danger{{background:var(--danger-bg);color:var(--danger)}}
.momentum.warn{{background:var(--warn-bg);color:var(--warn)}}
.momentum.good{{background:var(--good-bg);color:var(--good)}}
.block{{background:var(--surface);border:1px solid var(--line);border-radius:10px;
  padding:16px 18px;margin-bottom:14px}}
.block h2{{margin:0 0 4px;font-size:12px;letter-spacing:.07em;text-transform:uppercase;
  color:var(--ink-3)}}
.copy{{font-size:17px;font-weight:600;line-height:1.4;
  background:var(--surface-2);border:1px solid var(--line);border-radius:6px;
  padding:10px 12px;margin:6px 0;user-select:all}}
.reason{{font-size:12.5px;color:var(--ink-3);margin:4px 0 0}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0}}
.chip{{background:var(--chip);border:1px solid var(--line);border-radius:5px;
  padding:4px 9px;font-size:13px;user-select:all}}
.chip.gap{{border-color:var(--accent);color:var(--accent)}}
.rejected{{margin:10px 0 0;padding-left:18px;font-size:12.5px;color:var(--ink-3)}}
.rejected s{{color:var(--danger)}}
.price{{font-size:22px;font-weight:700}}
.price.good{{color:var(--good)}} .price.danger{{color:var(--danger)}}
.market{{font-size:13.5px;color:var(--ink-2)}}
ul.plain{{margin:6px 0 0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}}
ul.plain li{{margin-bottom:3px}}
.warnblock{{background:var(--warn-bg);border:1px solid var(--warn);border-radius:10px;
  padding:14px 16px;margin-bottom:14px}}
.warnblock h2{{color:var(--warn);margin:0 0 6px;font-size:12px;letter-spacing:.07em;
  text-transform:uppercase}}
.warnblock ul{{margin:0;padding-left:18px;font-size:13.5px;color:var(--ink-2)}}
footer{{margin-top:22px;padding-top:14px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:12px;max-width:66ch}}
</style></head><body><div class="wrap">
<h1>Blueprint: {term}</h1>
<p class="stamp">{html.escape(bp.get("product_type") or "")} · built
  {now.strftime("%Y-%m-%d %H:%M UTC")} from {bp.get("_sources", 0)} live page-one
  listings · click a box to select it</p>

{momentum}

<div class="block">
  <h2>Title ({title["length"]}/140 chars)</h2>
  <div class="copy">{html.escape(title["title"])}</div>
  <p class="reason">{html.escape(title["reason"])}</p>
</div>

<div class="block">
  <h2>Tags ({tags["filled"]}/13 — only measured support, never invented)</h2>
  <div class="chips">{tag_chips or '<span class="reason">No tag had support in 2+ listings.</span>'}</div>
  {f'<ul class="rejected">{rejected}</ul>' if rejected else ""}
</div>

<div class="block">
  <h2>Price</h2>
  <div class="price {price_cls}">{html.escape(price_txt)}</div>
  <p class="reason">{html.escape(price["reason"])}</p>
  {f'<p class="market">{market["volume"]:,} searches · {market["supply"]:,} listings</p>' if market.get("volume") else ""}
</div>

<div class="block">
  <h2>Click — tags win the impression, these win the click</h2>
  <ul class="plain">{checklist}</ul>
</div>

{f'<div class="warnblock"><h2>Warnings</h2><ul>{warnings}</ul></div>' if warnings else ""}

<footer>
  Every tag here appeared in at least two live page-one listings; none was invented.
  A thin tag set is the honest output for a term whose winners tag in phrases too
  long for Etsy's 20-character limit — a full set copied blind would silently lose
  exactly those tags. Momentum and price are the two things that most often make a
  high-ratio term a bad bet; both are stated plainly above.
</footer>
</div></body></html>'''


def write(term, out_dir=OUT_DIR, bp=None, now=None, **gather_kw):
    bp = bp if bp is not None else gather(term, **gather_kw)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"blueprint-{_slug(term)}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_html(bp, now=now))
    return path


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="blueprint_page")
    parser.add_argument("term")
    parser.add_argument("--type", default="personalized")
    parser.add_argument("--cogs", type=float, default=0.0)
    parser.add_argument("--labor-minutes", type=float, default=0.0)
    parser.add_argument("--shipping-cost", type=float, default=0.0)
    args = parser.parse_args(argv)
    path = write(args.term, product_type=args.type, cogs=args.cogs,
                 labor_minutes=args.labor_minutes, shipping_cost=args.shipping_cost)
    print(f"[+] {path}   <- open in a browser, copy the boxes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
