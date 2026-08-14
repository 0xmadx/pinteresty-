"""Offline tests for GraphDB's append-only migration. Uses a temp file, no network.

The regressions these guard against:
  1. re-crawling a term erased its previous metrics (INSERT OR REPLACE),
  2. a partial re-write NULLed every column it didn't supply,
  3. edges lost their discovery date on every re-sighting.

Run:  python -m core.test_graph_db
"""
import os
import sys
import tempfile

from core.graph_db import GraphDB

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def main():
    tmp = tempfile.mkdtemp()
    db = GraphDB(db_path=os.path.join(tmp, "graph.db"))

    # --- history survives a re-crawl ---------------------------------------------------
    db.add_node({"term_id": "t1", "term": "mom necklace", "volume": 100, "supply": 50,
                 "depth": 1, "source": "etsy"})
    db.add_node({"term_id": "t1", "term": "mom necklace", "volume": 140, "supply": 60,
                 "depth": 1, "source": "etsy"})
    hist = db.get_node_history("t1")
    check("re-crawl appends an observation instead of overwriting",
          len(hist) == 2, f"got {len(hist)}")
    check("both metric values are kept, oldest first",
          [h["volume"] for h in hist] == [100, 140],
          f"got {[h['volume'] for h in hist]}")
    check("every observation carries collected_at",
          all(h["collected_at"] for h in hist))
    node = db.get_node("mom necklace")
    check("nodes keeps the latest state", node["volume"] == 140, f"got {node['volume']}")

    # --- partial re-write no longer blanks columns --------------------------------------
    print()
    db.add_node({"term_id": "t1", "term": "mom necklace", "cvr_raw": 0.03})
    node = db.get_node("mom necklace")
    check("a partial add_node keeps fields it did not supply",
          node["volume"] == 140 and node["supply"] == 60 and node["depth"] == 1,
          f"got volume={node['volume']} supply={node['supply']} depth={node['depth']}")
    check("and still applies the fields it did supply",
          node["cvr_raw"] == 0.03, f"got {node['cvr_raw']}")
    check("the partial write is itself an observation",
          len(db.get_node_history("t1")) == 3)

    # --- update_node records metric patches ---------------------------------------------
    print()
    db.update_node("t1", search_count=900, series_json="[]")
    hist = db.get_node_history("t1")
    check("update_node with a metric field appends an observation",
          len(hist) == 4 and hist[-1]["search_count"] == 900,
          f"got {len(hist)}")
    n_before = len(hist)
    db.update_node("t1", series_json="[1]")
    check("update_node with only non-metric fields appends nothing",
          len(db.get_node_history("t1")) == n_before)
    check("update_node on a missing term writes no orphan observation",
          db.update_node("ghost", volume=5) == 0 and db.get_node_history("ghost") == [])

    # --- edges keep first_seen across re-sightings --------------------------------------
    print()
    db.add_edge("a", "b", "related", "etsy", weight=0.9)
    first = db.neighbors("a")[0]
    db.add_edge("a", "b", "related", "etsy")  # re-sighted, no weight this time
    again = db.neighbors("a")[0]
    check("a re-sighted edge keeps its measured weight",
          again["weight"] == 0.9, f"got {again['weight']}")

    import sqlite3
    with sqlite3.connect(db.db_path) as conn:
        row = conn.execute("SELECT first_seen, last_seen FROM edges "
                           "WHERE src='a' AND dst='b'").fetchone()
    check("edge first_seen survives the re-sighting", row[0] == first.get("first_seen", row[0]))
    check("edge first_seen and last_seen are both set", row[0] and row[1])

    n = db.add_edges("a", [("c", 0.5), "d"], "related", "etsy")
    check("add_edges handles pairs and bare strings", n == 2)
    check("batch edges land with timestamps",
          all(e["dst"] in {"b", "c", "d"} for e in db.neighbors("a")))

    # --- crawl-state behaviour is unchanged ---------------------------------------------
    print()
    db.push_frontier("new term", 2, "t1", source="etsy")
    check("frontier still works", db.pop_frontier()["term"] == "new term")
    db.complete_frontier("new term")   # a pop is now a claim; callers must close it
    check("is_visited still works", db.is_visited("mom necklace"))

    # --- a claimed term survives a failed fetch (was: silently lost) --------------------
    # pop_frontier used to DELETE on pop, so a term whose fetch then failed vanished
    # from the queue while never reaching `nodes`. Nothing retried it and is_visited()
    # said False, so the crawl finished with a hole and reported success.
    db.push_frontier("flaky term", 1, None, source="etsy")
    claimed = db.pop_frontier(source="etsy")
    check("claim returns the term", claimed and claimed["term"] == "flaky term", claimed)
    check("a claimed term is not handed out twice",
          db.pop_frontier(source="etsy") is None)
    db.release_frontier("flaky term")
    again = db.pop_frontier(source="etsy")
    check("released term is retried", again and again["term"] == "flaky term", again)
    db.complete_frontier("flaky term")
    check("completed term leaves the queue", db.pop_frontier(source="etsy") is None)

    # A run killed mid-term leaves a claim behind. Without reclaim it stays claimed
    # forever — the same silent hole, arriving more slowly.
    db.push_frontier("orphaned term", 1, None, source="etsy")
    db.pop_frontier(source="etsy")
    check("stale claim blocks until reclaimed", db.pop_frontier(source="etsy") is None)
    check("nothing reclaimed while the claim is fresh", db.reclaim_stale(30) == 0)
    check("reclaim_stale releases an old claim", db.reclaim_stale(0) == 1)
    check("and the term is crawlable again",
          (db.pop_frontier(source="etsy") or {}).get("term") == "orphaned term")
    db.complete_frontier("orphaned term")

    s = db.stats()
    check("stats still counts", s["nodes"] == 1 and s["edges"] == 3, f"got {s}")

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
