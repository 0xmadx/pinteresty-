"""The recursive keyword crawl: best-first search, cycle-safe, honest pruning.

The pruning is the delicate part — it shapes WHERE the crawl looks without changing WHAT
it reports. A term not expanded is still recorded; only the report's completeness depends
on that being true.

Offline: a fake keyword graph, no network.

    .venv/Scripts/python.exe -m etsy.analytics.test_keyword_crawl
"""
from etsy.analytics.keyword_crawl import crawl, pockets, summary

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


class FakeGraph:
    """A fixed keyword graph. `edges[term]` = list of (child, volume, supply)."""

    def __init__(self, edges):
        self.edges = edges
        self.calls = []

    def get_similar_keywords(self, term):
        self.calls.append(term)
        rows = self.edges.get(term, [])
        return [{"search_term": t, "search_volume": v, "avg_total_listings": s}
                for t, s, v in [(t, s, v) for (t, v, s) in rows]]


# A small graph: seed → three children of different winnability, one child deeper.
graph = FakeGraph({
    "seed": [("winnable_kid", 800, 1000),      # 0.80
             ("wall_kid", 100, 50000),         # 0.002
             ("mid_kid", 300, 1500)],          # 0.20
    "winnable_kid": [("deep_gem", 400, 500),   # 0.80, depth 2
                     ("seed", 1, 1)],          # a CYCLE back to seed
})

nodes = crawl(FakeGraph({**graph.edges}), "seed", max_nodes=50, max_depth=3)
terms = {n["term"]: n for n in nodes}

check("the seed and all children are discovered",
      {"seed", "winnable_kid", "wall_kid", "mid_kid"} <= set(terms), sorted(terms))
check("a child keeps its inline volume", terms["winnable_kid"]["volume"] == 800)
check("winnability is computed on every node",
      terms["wall_kid"]["demand_per_listing"] == 0.002, terms["wall_kid"])

# --- cycle safety -----------------------------------------------------------------
g = FakeGraph({**graph.edges})
nodes = crawl(g, "seed", max_nodes=50, max_depth=3)
check("a term is expanded at most once despite a cycle",
      g.calls.count("seed") == 1, g.calls)
check("the deep gem beyond the winnable child is reached",
      "deep_gem" in {n["term"] for n in nodes}, [n["term"] for n in nodes])
check("its depth is recorded correctly",
      next(n for n in nodes if n["term"] == "deep_gem")["depth"] == 2)

# --- pruning shapes search, not the report ----------------------------------------
# expand_top_k=1 must still RECORD every child of an expanded node, only limit which
# get drilled further.
g = FakeGraph({
    "seed": [("a", 900, 1000), ("b", 50, 1000), ("c", 10, 1000)],
    "a": [("a_child", 500, 1000)],
    "b": [("b_child", 500, 1000)],
})
nodes = crawl(g, "seed", max_nodes=50, max_depth=3, expand_top_k=1)
found = {n["term"] for n in nodes}
check("all three children are recorded even with top_k=1",
      {"a", "b", "c"} <= found, found)
check("only the most winnable child was expanded",
      "a_child" in found and "b_child" not in found, found)
# a (0.9) beats b (0.05), so a is drilled and b is not — the pruning heuristic.
check("the un-expanded child was NOT drilled",
      "b" not in g.calls and "b_child" not in found, g.calls)
# top_k=1 means only 'a' is queued for expansion, so 'b' is never fetched at all.

# --- budget and depth limits ------------------------------------------------------
wide = FakeGraph({"seed": [(f"k{i}", 100, 1000) for i in range(200)]})
nodes = crawl(wide, "seed", max_nodes=20, max_depth=3)
check("the node budget is respected", len(nodes) <= 20, len(nodes))

deep = FakeGraph({"seed": [("d1", 100, 100)], "d1": [("d2", 100, 100)],
                  "d2": [("d3", 100, 100)], "d3": [("d4", 100, 100)]})
nodes = crawl(deep, "seed", max_nodes=50, max_depth=2)
check("depth limit stops expansion", "d3" not in {n["term"] for n in nodes},
      [n["term"] for n in nodes])
# d1 (depth1) and d2 (depth2) reached; d2 is at max_depth so d3 is never fetched.

# --- pockets: the analyst's output ------------------------------------------------
nodes = crawl(FakeGraph({**graph.edges}), "seed", max_nodes=50, max_depth=3)
p = pockets(nodes, min_ratio=0.25)
names = [n["term"] for n in p]
check("winnable terms surface as pockets",
      "winnable_kid" in names and "deep_gem" in names, names)
check("walls are excluded from pockets", "wall_kid" not in names, names)
check("the seed itself is excluded", "seed" not in names, names)
check("pockets are sorted best-first",
      all(p[i]["demand_per_listing"] >= p[i+1]["demand_per_listing"]
          for i in range(len(p)-1)), [n["demand_per_listing"] for n in p])

# A neighbourhood that is a wall all the way down yields no pockets — a real answer.
allwall = FakeGraph({"seed": [("w1", 10, 100000), ("w2", 5, 90000)]})
check("an all-wall crawl reports zero pockets",
      pockets(crawl(allwall, "seed")) == [])

s = summary(crawl(FakeGraph({**graph.edges}), "seed"))
# winnable_kid and deep_gem are 0.80 = contested (winnable needs >= 1.0); wall_kid 0.002.
check("summary counts the verdict mix", s["contested"] >= 2 and s["wall"] >= 1, s)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
