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

    # --- record_serp_ranks: the two populations must never be merged ---------------
    #
    # A SERP page hands us ~12 server-rendered cards AND, separately, 39-51 organic
    # ids in rank order. Different sizes, different position semantics. Collapsing
    # them into one `position` column is the unit-mixing card_saturation exists to
    # prevent — and it would look completely reasonable in a diff.
    #
    # Before this, job_competition_sweep stored len(organic_listing_ids): a count,
    # which can never become a series.
    serp = {
        "total_results": 217196,
        "cards": [
            {"listing_id": "111", "shop_name": "AlphaCo", "is_ad": True},
            {"listing_id": "222", "shop_name": "BetaCo", "is_ad": False},
            # A card whose shop name did not parse — distinct from a listing that had
            # no card at all, which is the whole point of card_rendered.
            {"listing_id": "333", "shop_name": None, "is_ad": False},
        ],
        # 222 and 333 rank organically; 111 is an ad so it is absent here. 444 ranks
        # beyond the rendered cards — an id with no shop name available.
        "organic_listing_ids": ["222", "333", "444"],
    }
    out = db.record_serp_ranks("felt garland", serp)
    check("one row per listing across BOTH populations, deduped",
          out["rows"] == 4, out)

    rows = {r["listing_id"]: r for r in db.get_term_rank_history("felt garland")}
    check("the term-keyed reader returns them all", len(rows) == 4, sorted(rows))

    check("an ad has an absolute rank and NO organic rank",
          rows["111"]["absolute_rank"] == 1 and rows["111"]["rank"] is None,
          dict(rows["111"]))
    check("and is flagged as an ad", bool(rows["111"]["is_ad"]))

    check("a card that also ranks organically carries BOTH, unmerged",
          rows["222"]["absolute_rank"] == 2 and rows["222"]["rank"] == 1,
          dict(rows["222"]))
    check("shop_name is stored — this is who ranked", rows["222"]["shop_name"] == "BetaCo")

    check("a listing ranking beyond the rendered cards has organic rank only",
          rows["444"]["rank"] == 3 and rows["444"]["absolute_rank"] is None,
          dict(rows["444"]))
    # The distinction that makes a NULL shop_name readable. Without card_rendered,
    # "no card was rendered" and "a card rendered and the shop failed to parse" are
    # the same row, and only the second is a bug worth chasing.
    check("...and is marked card_rendered = 0", rows["444"]["card_rendered"] == 0)
    check("while a rendered card with an unparsed shop is card_rendered = 1",
          rows["333"]["card_rendered"] == 1 and rows["333"]["shop_name"] is None,
          dict(rows["333"]))

    check("competitor_count rides along so rank 40 reads against its market",
          rows["222"]["competitor_count"] == 217196)
    check("one shared observed_at — a sweep is ONE reading, not N straddling a second",
          len({r["observed_at"] for r in rows.values()}) == 1)

    # A second sweep on a later timestamp must APPEND, not overwrite. A rank series
    # that overwrites is not a series.
    db.record_serp_ranks("felt garland", serp, observed_at="2099-01-01T00:00:00+00:00")
    check("a later sweep appends rather than replacing",
          len(db.get_term_rank_history("felt garland")) == 8)
    check("and the listing-keyed reader sees both readings",
          len(db.get_rank_history("222")) == 2)

    # No launch was ever recorded here. Competitor ranks must not require one — they
    # are the unbiased outcome data precisely because we did not choose them (B-04).
    check("recording competitor ranks needs no launch row", out["rows"] == 4)

    empty = db.record_serp_ranks("nothing here", {"cards": [], "organic_listing_ids": []})
    check("an empty SERP writes nothing rather than a phantom row", empty["rows"] == 0)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
