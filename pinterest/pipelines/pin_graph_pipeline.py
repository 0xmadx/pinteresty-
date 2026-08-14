"""Pinterest BFS crawler — the free, wide funnel that decides where Etsy quota gets spent.

Mirrors `private/pipelines/ssr_graph_pipeline.py` and shares its GraphDB frontier contract, but
runs far deeper: Etsy costs a quota unit per node, Pinterest costs nothing.

    .venv/Scripts/python.exe pinterest/pipelines/pin_graph_pipeline.py --depth 2 --max-nodes 20

Seeds come from the discovery table (and optionally the moments calendar), expansion from
related_terms + prefix_match. Node stats are batched: one /metrics/ call per level, not per term.
"""
import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from core.graph_db import GraphDB
from pinterest.endpoints.api import PinterestTrendsAPI
from pinterest.endpoints.constants import clamp_change

SOURCE = "pinterest"


def node_from_row(row, depth, parent_id):
    """A /top_trends_filtered/ row -> a graph node.

    `clamp_change` drops the 100.01 "10,000%+" sentinel so it cannot poison an average.
    """
    return {
        "term_id": f"pin:{row['term']}",
        "term": row["term"],
        "source": SOURCE,
        "node_type": "term",
        "search_count": row.get("searchCount"),
        "seasonality_score": row.get("seasonality_score"),
        "mom_change": clamp_change((row.get("mom_change") or {}).get("value")),
        "yoy_change": clamp_change((row.get("yoy_change") or {}).get("value")),
        "wow_value": clamp_change((row.get("wow_change") or {}).get("value")),
        "depth": depth,
        "parent_id": parent_id,
    }


def seed(api, db, presets, country):
    """Sweep the discovery table and queue the rows. This is where corpus breadth comes from —
    related_terms only returns ~5 rows per call, so it refines rather than scales.

    The rows are returned rather than written straight to `nodes`: `push_frontier` skips any
    term that already exists as a node, so writing first would empty the queue instantly.
    """
    rows_by_term = {}
    for preset in presets:
        table = api.top_trends(preset, country=country)
        if not table:
            continue
        for row in table["values"]:
            rows_by_term.setdefault(row["term"], row)
            db.push_frontier(row["term"], 0, None, source=SOURCE)
        print(f"  seeded {len(table['values'])} from preset '{preset}'")
    return rows_by_term


def expand(api, db, term, term_id, depth, max_depth):
    """related_terms (co-search, topical) + prefix_match (string-prefix children)."""
    pushed = 0
    for kind, fetch in (("related", api.related_terms), ("prefix", api.prefix_match)):
        rows = fetch(term) or []
        pairs = []
        for r in rows:
            child = r.get("term")
            if not child or child == term:
                continue
            counts = r.get("counts") or []
            # Edge weight = the child's own recent level. Correlation against the parent's
            # series would be better and is computable from data we already cache.
            weight = counts[-1] if counts and isinstance(counts[-1], (int, float)) else None
            pairs.append((f"pin:{child}", weight))
            if depth < max_depth and not db.is_visited(child):
                db.push_frontier(child, depth + 1, term_id, source=SOURCE)
                pushed += 1
        if pairs:
            db.add_edges(term_id, pairs, kind, SOURCE)
    return pushed


def run(presets, country, max_depth, max_nodes, batch=50):
    db = GraphDB()
    # A previous run that was killed mid-term left its claims in place; without this
    # those terms stay claimed forever and are never crawled again.
    reclaimed = db.reclaim_stale()
    if reclaimed:
        print(f"Reclaimed {reclaimed} term(s) left claimed by an interrupted run.")
    with PinterestTrendsAPI() as api:
        print(f"Data week: {api.latest_available_date()}  |  seeding...")
        rows_by_term = seed(api, db, presets, country)
        print(f"  {len(rows_by_term)} unique terms queued")

        processed, pending = 0, []
        while processed < max_nodes:
            current = db.pop_frontier(source=SOURCE)
            if not current:
                print("\nFrontier empty.")
                break
            term, depth = current["term"], current["depth"]
            term_id = f"pin:{term}"

            try:
                row = rows_by_term.get(term)
                if row:
                    db.add_node(node_from_row(row, depth, current["parent_id"]))
                else:
                    db.add_node({"term_id": term_id, "term": term, "source": SOURCE,
                                 "node_type": "term", "depth": depth,
                                 "parent_id": current["parent_id"]})
                pending.append(term)

                pushed = expand(api, db, term, term_id, depth, max_depth)
            except Exception as exc:
                # Hand the claim back so the next run retries this term. Swallowing the
                # failure and moving on is what used to leave silent holes in the graph.
                db.release_frontier(term)
                print(f"  [!] {term!r} failed ({type(exc).__name__}: {exc}) — returned "
                      f"to the frontier, not lost")
                continue

            db.complete_frontier(term)
            processed += 1
            print(f"  [{processed}/{max_nodes}] d{depth} {term!r} -> +{pushed} frontier")

            # Curves are batched, never one call per term.
            if len(pending) >= batch:
                flush(api, db, pending)
                pending = []

        if pending:
            flush(api, db, pending)

    s = db.stats()
    print(f"\nGraph: {s['nodes']} nodes, {s['edges']} edges, {s['frontier']} queued")
    print(f"  by source: {s['by_source']}")
    print(f"  by edge:   {s['by_edge_type']}")
    return s


def flush(api, db, terms):
    """Curves for up to 50 terms, then patch the stored nodes.

    days=365 rather than 90: it is the same single request but the widest window, so it
    lands in the series store as an exact 53-point row that every shorter window slices
    out of, and it carries growth_rates (which do not reproduce from the counts). Most of
    these terms never reach the wire at all — they entered the frontier through
    related_terms/prefix_match, which already handed back their series.

    update_node, not add_node: this is a patch of two fields on an existing node, not a
    (re-)discovery. (add_node no longer blanks unsupplied columns — it COALESCEs against
    the stored row — but update_node states the intent and skips the full upsert.)
    """
    import json as _json

    series = api.metrics(terms, days=365) or []
    local = sum(1 for s in series if s.get("_source"))
    for s in series:
        counts = [p["count"] for p in s.get("counts", [])]
        db.update_node(f"pin:{s['term']}",
                       search_count=counts[-1] if counts else None,
                       series_json=_json.dumps(s.get("counts", [])))
    print(f"    ...curves for {len(series)} terms ({local} local, "
          f"{len(series) - local} fetched)")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--presets", nargs="+", default=["growing", "seasonal"])
    p.add_argument("--country", default="US")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--max-nodes", type=int, default=15)
    a = p.parse_args()
    run(a.presets, a.country, a.depth, a.max_nodes)
