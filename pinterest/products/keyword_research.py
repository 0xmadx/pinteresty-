"""1. Keyword research — a general trend/content research tool for any niche.

Three distinct capabilities, deliberately kept apart because they answer different
questions and cost different amounts:

    long_tail()   /prefix_match/  — terms that START with the query. This is free
                                    autocomplete: one request, ~10 children, each with 52
                                    weeks of history attached.
    neighbours()  /related_terms/ — terms CO-SEARCHED with the query. The interesting ones
                                    share no word with the seed ("washington" -> "pnw
                                    aesthetic"), which is what makes this a topic clusterer
                                    rather than a string expander.
    sweep()       /top_trends_filtered/ per interest — 24 interests x 4 presets = up to 96
                                    ranked tables of 50 rows. This is where breadth comes
                                    from; expansion only refines.

Every row is scored on `velocity()` (our own momentum measure) rather than the API's
growth_rates, because prefix/related rows do not carry growth_rates at all — see
`local_math` for why those cannot be recomputed from the counts.

    .venv/Scripts/python.exe pinterest/products/keyword_research.py "halloween nails"
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import (INTERESTS, PRESETS, TOP_TRENDS_LIMIT_MAX,
                                           clamp_change)
from pinterest.endpoints.local_math import peak_week, velocity

STOPWORDS = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with", "ideas", "diy"}


def _words(term):
    return {w for w in term.lower().split() if w not in STOPWORDS}


def _row(term, counts, source):
    """One scored keyword. `counts` is the raw 0-100 weekly series the endpoint attached.

    `noisy` is the honesty flag. Each series is normalized to 100 at its own peak, so a
    term sitting at 1-3 all year produces velocities like +900% off a one-unit move. Same
    threshold the series store refuses to slice below, for the same reason: the source
    rounding, not the term, is what moved.
    """
    recent = counts[-8:] if counts else []
    return {
        "term": term,
        "source": source,
        "level": counts[-1] if counts else None,        # current interest, 0-100 in-window
        "velocity": velocity(counts),                    # 4wk mean vs prior 4wk
        "noisy": bool(recent) and max(recent) < 25,
        "peak": peak_week(counts),
        "weeks": len(counts),
    }


def long_tail(api, query, country="US", min_level=0):
    """Prefix children, ranked by momentum. One request.

    `min_level` filters out terms whose most recent week is near zero — a prefix match can
    return a term that was big last winter and is dead now, and for content planning that
    is noise rather than a long tail.
    """
    rows = api.prefix_match(query, country=country) or []
    out = [_row(r["term"], r.get("counts") or [], "prefix")
           for r in rows if r.get("term") != query]
    out = [r for r in out if (r["level"] or 0) >= min_level]
    return sorted(out, key=lambda r: (r["velocity"] is None, -(r["velocity"] or 0)))


def neighbours(api, seed, country="US", only_novel=False):
    """Co-searched terms. `only_novel` keeps just the ones sharing no significant word with
    the seed — those are the ones autocomplete could never have produced, and they are the
    whole reason to call this endpoint rather than prefix_match."""
    rows = api.related_terms(seed, country=country) or []
    seed_words = _words(seed)
    out = []
    for r in rows:
        term = r.get("term")
        if not term or term == seed:
            continue
        row = _row(term, r.get("counts") or [], "related")
        row["novel"] = not (_words(term) & seed_words)
        out.append(row)
    if only_novel:
        out = [r for r in out if r["novel"]]
    return sorted(out, key=lambda r: -(r["level"] or 0))


def expand(api, seed, country="US", depth=1, only_novel=False):
    """Seed -> prefix children + co-searched neighbours, recursively.

    Depth costs 2 requests per node and nothing else: the series ride along inside the
    responses, so a 40-term corpus built this way needs no /metrics/ call at all.
    """
    seen, frontier, out = {seed}, [(seed, 0)], {}
    while frontier:
        term, d = frontier.pop(0)
        rows = long_tail(api, term, country) + neighbours(api, term, country, only_novel)
        for r in rows:
            if r["term"] in out:
                continue
            r["found_via"] = term
            r["depth"] = d + 1
            out[r["term"]] = r
            if d + 1 < depth and r["term"] not in seen:
                seen.add(r["term"])
                frontier.append((r["term"], d + 1))
    return sorted(out.values(), key=lambda r: (r["velocity"] is None, -(r["velocity"] or 0)))


def sweep(api, preset="growing", interests=None, country="US", limit=TOP_TRENDS_LIMIT_MAX):
    """The discovery table per interest — the breadth engine.

    Unfiltered, `top_trends_filtered` returns one national table. Passing `l1interests`
    re-runs the same ranking inside that interest, so 24 calls yield up to 2400 ranked
    terms instead of 50. Rows are tagged with the interest they came from, which is the
    label a keyword tool needs and the national table cannot give you.

    `limit` defaults to the server maximum of 100 rather than the UI's 50: it is the same
    single request either way, and the first 50 rows are identical, so the extra 50 are
    free breadth. This is a keyword tool — breadth is the product.

    Only 'growing' and 'seasonal' are velocity-sorted; on the two 'top_*' presets the row
    order is volume, so `rank` means something different there (see constants.PRESETS).

    `interests=None` means all 24; `interests=[]` means none. The distinction matters —
    conflating them turns a caller's empty filter into 24 live requests.
    """
    names = list(INTERESTS if interests is None else interests)
    out = []
    for name in names:
        table = api.top_trends(preset, country=country, interests=[INTERESTS[name]],
                               limit=limit)
        for i, row in enumerate(table["values"] if table else []):
            out.append({
                "term": row["term"],
                "interest": name,
                "interest_id": INTERESTS[name],
                "rank": i,
                "preset": preset,
                "sorted_by": PRESETS[preset]["sorted_by"],
                "search_count": row.get("searchCount"),
                "seasonality": row.get("seasonality_score"),
                "mom": clamp_change((row.get("mom_change") or {}).get("value")),
                "yoy": clamp_change((row.get("yoy_change") or {}).get("value")),
                "wow": clamp_change((row.get("wow_change") or {}).get("value")),
            })
    return out


def cross_interest(rows):
    """Terms that rank inside more than one interest.

    A term appearing under both Home Decor and Wedding is a broader piece of demand than
    its rank in either table suggests, and it is invisible if you only ever read one table.
    """
    by_term = {}
    for r in rows:
        by_term.setdefault(r["term"], []).append(r["interest"])
    return {t: ints for t, ints in by_term.items() if len(ints) > 1}


def report(seed, country="US", depth=1):
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}\n")

        print(f"=== long tail of {seed!r} (~ = too small to trust the velocity) ===")
        for r in long_tail(api, seed, country)[:10]:
            v = f"{r['velocity']:+.0%}" if r["velocity"] is not None else "  n/a"
            print(f"  {'~' if r['noisy'] else ' '}{v}  level {str(r['level']):>3}  {r['term']}")

        print(f"\n=== co-searched with {seed!r} (* = shares no word) ===")
        for r in neighbours(api, seed, country):
            mark = "*" if r["novel"] else " "
            print(f"  {mark} level {str(r['level']):>3}  {r['term']}")

        if depth > 1:
            corpus = expand(api, seed, country, depth=depth)
            print(f"\n=== depth-{depth} corpus: {len(corpus)} terms, 0 /metrics/ calls ===")
            for r in corpus[:15]:
                v = f"{r['velocity']:+.0%}" if r["velocity"] is not None else "  n/a"
                print(f"  {v}  d{r['depth']} {r['term']:38} via {r['found_via']}")


if __name__ == "__main__":
    seed = sys.argv[1] if len(sys.argv) > 1 else "halloween nails"
    report(seed, depth=int(sys.argv[2]) if len(sys.argv) > 2 else 1)
