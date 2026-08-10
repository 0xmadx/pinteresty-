"""7. Trend moodboards — what a trend actually looks like.

`topics/featured` is the densest response on the whole surface: five editorially curated
macro trends, and each one ships its description, MoM growth, a full time series, its
related search terms, AND a set of pins with image URLs and a precomputed dominant colour
per pin. The UI's expanded card fires no further requests — this single call is the entire
feature, which means a visual trend report costs exactly one request per interest.

The colour field is the part worth building on. Every pin carries `color` as a hex string,
so a palette is a count, not an image-processing job. What comes out is "here is the trend,
here is what it looks like, here are its colours" — the brief a content or product team
actually works from.

Constraints the client enforces (the server just 400s/500s): US/CA/GB+IE only, the event is
hard-wired to SAVE, and `interests` takes exactly one id or the Fashion triple.

    .venv/Scripts/python.exe pinterest/products/moodboard.py --html
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import SPOTLIGHT_INTERESTS
from pinterest.endpoints.local_math import peak_week, velocity

OUT_DIR = Path(__file__).resolve().parents[1] / "data"


def _hex_to_rgb(h):
    h = (h or "").lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) if len(h) == 6 else None


def _bucket(hex_colour, step=64):
    """Quantise to a coarse grid so near-identical pin colours collapse into one swatch.

    Without this a 24-pin board yields 24 unique hexes and the 'palette' is just a list of
    the pins again. step=64 gives 4 levels per channel, which lands around 6-10 distinct
    families on a real board — about what a human would name.
    """
    rgb = _hex_to_rgb(hex_colour)
    if not rgb:
        return None
    return tuple(min(255, (c // step) * step + step // 2) for c in rgb)


def palette(topic, top=6):
    """Dominant colour families across a topic's pins, most common first."""
    counts = Counter()
    for pin in topic.get("pins") or []:
        b = _bucket(pin.get("color"))
        if b:
            counts[b] += 1
    total = sum(counts.values()) or 1
    return [{"hex": "#%02x%02x%02x" % rgb, "pins": n, "share": round(n / total, 2)}
            for rgb, n in counts.most_common(top)]


def board(api, interest="All", country="US"):
    """One interest's five topics, each as a self-contained visual brief."""
    topics = api.featured_topics(SPOTLIGHT_INTERESTS[interest], country=country) or []
    out = []
    for t in topics:
        counts = [p.get("count") for p in (t.get("time_series") or [])
                  if isinstance(p, dict) and p.get("count") is not None]
        out.append({
            "interest": interest,
            "name": t.get("name"),
            "description": t.get("description"),
            "growth_mom": t.get("pct_growth_mom"),
            "velocity": velocity(counts),
            "peak": peak_week(counts),
            "weeks": len(counts),
            "series": counts,
            "palette": palette(t),
            "terms": t.get("related_search_trends") or [],
            "images": [p.get("src") for p in (t.get("pins") or []) if p.get("src")],
        })
    return out


def editorial(api, country="US"):
    """The written layer — Pinterest's own trend stories, one request.

    Complements `board()` rather than duplicating it: featured_topics carries the numbers
    (growth, series) but only a name; editorial carries a title, real written copy, and the
    story's keywords **for US, GB+IE and CA in the same response**. No growth number, no
    series — do not try to rank on these.
    """
    stories = api.editorial_content(country) or []
    out = []
    for s in stories:
        keywords = s.get("keywords") or {}
        out.append({
            "interest": "Editorial",
            "name": s.get("title"),
            "description": s.get("body"),
            "growth_mom": None,
            "velocity": None,
            "peak": None,
            "weeks": 0,
            "series": [],
            "palette": palette(s),
            "terms": keywords.get(country) or next(iter(keywords.values()), []),
            "terms_by_region": keywords,
            "interests": s.get("interests") or [],
            "starts": s.get("start_date"),
            "images": [p.get("src") for p in (s.get("pins") or []) if p.get("src")],
        })
    return out


def all_boards(api, country="US", with_editorial=True):
    """Every dropdown option, plus the editorial stories. 16 requests, cached thereafter."""
    out = {}
    for label in SPOTLIGHT_INTERESTS:
        rows = board(api, label, country)
        if rows:
            out[label] = rows
    if with_editorial:
        stories = editorial(api, country)
        if stories:
            out["Editorial"] = stories
    return out


def to_html(boards, path=None, title="Pinterest trend moodboards"):
    """A single self-contained page. Images are hotlinked from i.pinimg.com — they are
    Pinterest's CDN URLs straight out of the response, not copies."""
    path = Path(path or OUT_DIR / "moodboards.html")
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{title}</title>",
        "<style>",
        "body{font:15px/1.5 system-ui,sans-serif;margin:0;padding:2rem;background:#111;color:#eee}",
        "h1{font-size:1.4rem;margin:0 0 1.5rem}h2{font-size:1rem;margin:2rem 0 .3rem;color:#9ab}",
        ".t{border-top:1px solid #333;padding:1.2rem 0}",
        ".t h3{margin:0 0 .2rem;font-size:1.15rem}",
        ".meta{color:#888;font-size:.85rem;margin-bottom:.6rem}",
        ".desc{color:#bbb;max-width:60ch;margin:0 0 .8rem}",
        ".sw{display:inline-block;width:46px;height:28px;border-radius:4px;margin-right:4px}",
        ".pins{display:flex;flex-wrap:wrap;gap:6px;margin:.7rem 0}",
        ".pins img{width:110px;height:110px;object-fit:cover;border-radius:6px}",
        ".terms{color:#7a9;font-size:.85rem}",
        "</style>",
        f"<h1>{title}</h1>",
    ]
    for interest, topics in boards.items():
        parts.append(f"<h2>{interest}</h2>")
        for t in topics:
            meta = (f"{t['growth_mom']:+.0%} MoM &middot; {t['weeks']} weeks of history"
                    if t["growth_mom"] is not None
                    else f"editorial &middot; from {t.get('starts') or 'undated'}")
            swatches = "".join(f"<span class='sw' style='background:{c['hex']}' "
                               f"title='{c['hex']} — {c['share']:.0%}'></span>"
                               for c in t["palette"])
            pins = "".join(f"<img src='{u}' loading='lazy'>" for u in t["images"][:12])
            parts += [
                "<div class='t'>",
                f"<h3>{t['name']}</h3>",
                f"<div class='meta'>{meta}</div>",
                f"<p class='desc'>{t['description'] or ''}</p>",
                f"<div>{swatches}</div>",
                f"<div class='pins'>{pins}</div>",
                f"<div class='terms'>{' &middot; '.join(t['terms'][:10])}</div>",
                "</div>",
            ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def report(country="US", html=False, interest=None):
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}\n")
        boards = ({interest: board(api, interest, country)} if interest
                  else all_boards(api, country))
        for name, topics in boards.items():
            print(f"=== {name} ===")
            for t in topics:
                growth = f"{t['growth_mom']:+.0%}" if t["growth_mom"] is not None else " n/a"
                swatch = " ".join(c["hex"] for c in t["palette"][:4])
                print(f"  {growth:>6}  {t['name'][:40]:42} {len(t['images'])} pins  {swatch}")
                print(f"          {', '.join(t['terms'][:5])}")
        if html:
            print(f"\nSaved {to_html(boards)}")
        return boards


if __name__ == "__main__":
    args = sys.argv[1:]
    named = next((a for a in args if not a.startswith("-")), None)
    report(html="--html" in args, interest=named)
