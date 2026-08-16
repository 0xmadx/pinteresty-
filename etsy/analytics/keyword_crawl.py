"""The recursive keyword crawl — one seed → the whole neighbourhood, sized for winnability.

This is the DISCOVER machine the project was aiming at: you name ONE term you can make,
and the crawl maps the keyword universe around it. Each term Etsy's LLM endpoint returns
(RK-2) carries its own search_volume and avg_total_listings, so every node is sized for
winnability with no extra call — the recursion is affordable.

Four lenses shape how it crawls and what it reports:

**Data scientist — spend the budget where opportunity is, and prune the rest.** Blind BFS
is exponential and, in a saturated category, almost all walls. The frontier is a priority
queue by winnability: the most promising unexpanded term is expanded next. Every term seen
is still recorded (walls included) so the picture stays honest — pruning decides where to
*look further*, never what to *report*.

**SEO expert — the long tail is the product.** The 28 curated front-door terms are head
terms. A seed expands into hundreds of long-tail terms Etsy does not promote, which is
where a shop without ranking authority can actually surface.

**Analyst — find the pockets, not the average.** The useful output is not "this niche is
crowded" (usually true) but the specific deep term whose demand-per-listing is an outlier
against its saturated neighbourhood. `pockets()` surfaces exactly those.

**Hunter — no typing.** One seed in, a ranked list of winnable-and-adjacent terms out.

The graph is persisted (`GraphDB`), so a second crawl over the same neighbourhood reuses
nodes already sized — the self-learning flywheel, over a store that already exists.
"""
import heapq

from etsy.analytics.discover import winnability


def _node(term, volume, supply, depth, parent):
    win = winnability({"volume": volume, "supply": supply})
    return {
        "term": term, "volume": volume, "supply": supply,
        "depth": depth, "parent": parent,
        "demand_per_listing": win.get("demand_per_listing"),
        "verdict": win.get("verdict"),
        "winnability": win,
    }


def crawl(api, seed, max_nodes=150, max_depth=3, expand_top_k=6, on_node=None):
    """Best-first recursive expansion from one seed. Returns every term discovered.

    `api.get_similar_keywords(term)` supplies the children, each with volume and supply
    inline. Cycles (the graph loops back — `felt banner` lists `felt garland`) are handled
    by a seen-set, so a term is expanded at most once.

    `expand_top_k` bounds fan-out per node: the LLM returns ~100-165 children, and taking
    every one exponentially would blow the budget on the first level. The top-K by
    winnability are queued; the rest are still RECORDED, just not expanded further.
    """
    from etsy.api.private.api import edge_term

    seen = {}                       # term -> node (dedupe + the result set)
    # Max-heap by winnability via negated ratio. Tie-break on a counter for stable,
    # comparison-safe ordering (dicts are never compared).
    counter = 0
    frontier = []

    seed_node = _node(seed, None, None, 0, None)
    seed_node["is_seed"] = True
    seen[seed] = seed_node
    heapq.heappush(frontier, (0.0, counter, seed))    # seed expanded first regardless
    counter += 1

    while frontier and len(seen) < max_nodes:
        _, _, term = heapq.heappop(frontier)
        node = seen[term]
        if node["depth"] >= max_depth:
            continue

        edges = api.get_similar_keywords(term)
        if not edges:
            continue

        children = []
        for edge in edges:
            child = edge_term(edge)
            if not child or child in seen:
                continue
            cn = _node(child, edge.get("search_volume"), edge.get("avg_total_listings"),
                       node["depth"] + 1, term)
            seen[child] = cn
            children.append(cn)
            if on_node:
                on_node(cn)
            if len(seen) >= max_nodes:
                break

        # Queue only the most promising children for further expansion; the rest are
        # recorded but not drilled. This is the pruning — it shapes the search, not the
        # report.
        children.sort(key=lambda n: n["demand_per_listing"] or -1, reverse=True)
        for cn in children[:expand_top_k]:
            heapq.heappush(frontier, (-(cn["demand_per_listing"] or 0), counter, cn["term"]))
            counter += 1

    return list(seen.values())


def pockets(nodes, min_ratio=0.25, exclude_seed=True):
    """The winnable terms in an otherwise-saturated crawl — the analyst's output.

    Not "is this niche crowded" (it usually is) but the specific terms whose
    demand-per-listing clears the bar despite the neighbourhood. Sorted best-first, CVR
    unavailable here so the ratio alone orders them.
    """
    out = [n for n in nodes
           if not (exclude_seed and n.get("is_seed"))
           and n["demand_per_listing"] is not None
           and n["demand_per_listing"] >= min_ratio]
    return sorted(out, key=lambda n: n["demand_per_listing"], reverse=True)


def summary(nodes):
    """The shape of what the crawl found — for a one-line honest headline."""
    sized = [n for n in nodes if n["demand_per_listing"] is not None]
    verdicts = {}
    for n in sized:
        verdicts[n["verdict"]] = verdicts.get(n["verdict"], 0) + 1
    return {
        "discovered": len(nodes),
        "sized": len(sized),
        "winnable": verdicts.get("winnable", 0),
        "contested": verdicts.get("contested", 0),
        "wall": verdicts.get("wall", 0),
        "max_depth": max((n["depth"] for n in nodes), default=0),
    }


def persist(db, nodes, source="etsy_private"):
    """Write the crawl to the graph store, so the next crawl reuses sized nodes.

    add_node COALESCEs against the stored row, so re-crawling never blanks a field it
    did not supply. The graph is the flywheel's memory.
    """
    for n in nodes:
        db.add_node({
            "term_id": f"kw:{n['term']}", "term": n["term"], "source": source,
            "node_type": "term", "volume": n["volume"], "supply": n["supply"],
            "cvr_raw": None, "depth": n["depth"],
            "parent_id": f"kw:{n['parent']}" if n.get("parent") else None,
        })
    return len(nodes)


def render(nodes, top=25):
    icon = {"winnable": "🟢", "contested": "🟡", "wall": "🔴"}
    s = summary(nodes)
    lines = [
        f"Crawled {s['discovered']} terms (depth {s['max_depth']}): "
        f"{s['winnable']} winnable · {s['contested']} contested · {s['wall']} walls",
        "",
    ]
    pocket = pockets(nodes)
    if not pocket:
        lines.append("No winnable pockets — this neighbourhood is a wall all the way down.")
        lines.append("That is an answer: the seed's whole market is saturated.")
        return "\n".join(lines)

    lines.append(f"WINNABLE POCKETS ({len(pocket)}):")
    for n in pocket[:top]:
        v = n["verdict"]
        lines.append(f"  {icon.get(v,'⚪')} {n['demand_per_listing']:>6.2f}/listing  "
                     f"vol={str(n['volume']):>6} supply={str(n['supply']):>7}  "
                     f"{'  '*n['depth']}{n['term']}  (d{n['depth']})")
    return "\n".join(lines)


def main(argv=None):
    import argparse

    from dotenv import load_dotenv

    load_dotenv(override=True)
    parser = argparse.ArgumentParser(prog="keyword_crawl")
    parser.add_argument("seed", help="the one keyword to expand from")
    parser.add_argument("--max-nodes", type=int, default=150)
    parser.add_argument("--max-depth", type=int, default=3)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args(argv)

    from core.preflight import PreflightFailed, require
    try:
        require("etsy_private")
    except PreflightFailed as exc:
        print(exc)
        return 1

    from etsy.api.private.api import EtsyPrivateAPI, SessionDown
    try:
        nodes = crawl(EtsyPrivateAPI(), args.seed,
                      max_nodes=args.max_nodes, max_depth=args.max_depth)
    except SessionDown as exc:
        print(f"⛔ {exc}")
        return 1

    print(render(nodes))
    if not args.no_persist:
        from core.graph_db import GraphDB
        persist(GraphDB(), nodes)
        print(f"\n(persisted {len(nodes)} nodes to the graph)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
