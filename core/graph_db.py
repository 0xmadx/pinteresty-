import sqlite3
import json
import os
from datetime import datetime, timedelta, timezone

# The metric columns that change between crawls. Every write of any of these also lands in
# the append-only node_observations table, so `nodes` can stay a latest-state/crawl-state
# table without destroying history (invariant 2, DECISION_LOG.md D-04).
OBSERVED_FIELDS = ("volume", "supply", "cvr_raw", "wow_value", "wow_trend",
                   "price_low", "price_high", "seasonality_score", "mom_change",
                   "yoy_change", "search_count")


def _utcnow():
    return datetime.now(timezone.utc).isoformat()

class GraphDB:
    def __init__(self, db_path="etsy/data/graph/graph.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS nodes (
                    term_id TEXT PRIMARY KEY,
                    term TEXT,
                    volume INTEGER,
                    supply INTEGER,
                    cvr_raw REAL,
                    wow_value REAL,
                    wow_trend TEXT,
                    price_low REAL,
                    price_high REAL,
                    depth INTEGER,
                    parent_id TEXT,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    series_json TEXT,
                    listings_json TEXT,
                    edges_json TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS frontier (
                    term TEXT PRIMARY KEY,
                    depth INTEGER,
                    parent_id TEXT
                )
            """)
            # Edges live in their own table so they can be traversed and joined. They used to
            # be a JSON blob inside nodes.edges_json, which could not be queried at all.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edges (
                    src TEXT,
                    dst TEXT,
                    edge_type TEXT,
                    source TEXT,
                    weight REAL,
                    PRIMARY KEY (src, dst, edge_type)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst)")
            # Append-only history of every metric write. `nodes` keeps only the latest
            # state (it doubles as the crawl's visited-set); this table keeps the past.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS node_observations (
                    term_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    source TEXT,
                    volume INTEGER,
                    supply INTEGER,
                    cvr_raw REAL,
                    wow_value REAL,
                    wow_trend TEXT,
                    price_low REAL,
                    price_high REAL,
                    seasonality_score REAL,
                    mom_change REAL,
                    yoy_change REAL,
                    search_count INTEGER
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_node_obs_term "
                         "ON node_observations(term_id, collected_at)")
            
            # M-3: The prediction snapshot. What was launched, and what was expected.
            #
            # SELF-SELECTION (bias B-04): the operator only launches what the model scored
            # highly, so this table is a sample of the model's own recommendations. Trained
            # on that alone, calibration measures precision — "the things we picked did
            # well" — and can never measure recall, because a niche the model rejected and
            # would have won appears nowhere. The failure is silent and flattering.
            #
            # is_control marks a deliberate mid/low-scored launch: the only rows that can
            # tell you what you are missing. Target roughly 1 in 10 (see control_ratio()).
            conn.execute("""
                CREATE TABLE IF NOT EXISTS launches (
                    listing_id TEXT PRIMARY KEY,
                    term_id TEXT NOT NULL,
                    launched_at TEXT NOT NULL,
                    predicted_score REAL,
                    predicted_profit REAL,
                    product_type TEXT,
                    is_control INTEGER NOT NULL DEFAULT 0,
                    notes TEXT
                )
            """)
            
            # M-3: The outcome tracking. Where the listings actually ranked.
            #
            # Append-only with observed_at in the key (D-04), so re-running the tracker
            # on a later day adds a row while re-running it within the same second is
            # idempotent rather than duplicating. `rank` is NULLABLE on purpose: a
            # listing that does not appear in the SERP is recorded as rank NULL —
            # "unranked, and we looked" — which is a different fact from no row at all,
            # meaning "never checked". Conflating those two is this system's whole
            # failure mode.
            # `rank` is the ORGANIC position (what SEO earned); `absolute_rank` counts
            # ads too (what the shopper's eye actually meets). MIGRATION_AND_OPERATIONS.md:111
            # requires both: a listing can slide in absolute rank while holding organic
            # rank purely because a competitor started buying placement, and storing one
            # number makes that look like a ranking loss it is not.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rank_observations (
                    listing_id TEXT NOT NULL,
                    term_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    rank INTEGER,
                    absolute_rank INTEGER,
                    page INTEGER,
                    is_ad BOOLEAN,
                    competitor_count INTEGER,
                    PRIMARY KEY (listing_id, term_id, observed_at)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rank_obs "
                         "ON rank_observations(listing_id, observed_at)")

            # The other half of the outcome. Rank is a proxy; this is the thing the
            # prediction was actually about. A listing can sit at rank 3 and sell
            # nothing, and scoring the model on rank alone would call that a success.
            #
            # Append-only with collected_at in the key (D-04). Every metric is
            # NULLABLE and no metric is derived from another: the operator reads
            # these off Etsy's own stats page, and a partial reading ("I know the
            # sales, not the views") must be recordable without inventing the rest.
            # Absent is not zero (N-02) — a launch with no outcome row has not been
            # measured, which is different from one that sold nothing.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS launch_outcomes (
                    listing_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    sales INTEGER,
                    revenue REAL,
                    views INTEGER,
                    favorites INTEGER,
                    note TEXT,
                    PRIMARY KEY (listing_id, collected_at)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_launch_outcomes "
                         "ON launch_outcomes(listing_id, collected_at)")
            
            self._migrate(conn)
            conn.commit()

    def _migrate(self, conn):
        """Additive column migration — the schema originally hardcoded Etsy's fields, so a
        Pinterest node would have written mostly NULLs. Safe to re-run."""
        existing = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
        for column, decl in [
            ("source", "TEXT"),              # 'etsy' | 'pinterest'
            ("node_type", "TEXT"),           # 'term' | 'category' | 'topic' | 'interest'
            ("seasonality_score", "REAL"),
            ("mom_change", "REAL"),
            ("yoy_change", "REAL"),
            ("search_count", "INTEGER"),
            ("demographics_json", "TEXT"),
        ]:
            if column not in existing:
                conn.execute(f"ALTER TABLE nodes ADD COLUMN {column} {decl}")
        frontier_cols = {row[1] for row in conn.execute("PRAGMA table_info(frontier)")}
        if "source" not in frontier_cols:
            conn.execute("ALTER TABLE frontier ADD COLUMN source TEXT")
        if "claimed_at" not in frontier_cols:
            # Work in progress. pop_frontier used to DELETE on pop, so a term whose
            # fetch then failed was gone from the queue and absent from `nodes` — lost
            # silently, with is_visited() reporting False and nothing ever requeuing
            # it. A crawl interrupted by a 403 or a crash finished with holes and
            # reported success.
            conn.execute("ALTER TABLE frontier ADD COLUMN claimed_at TEXT")
        edge_cols = {row[1] for row in conn.execute("PRAGMA table_info(edges)")}
        for column in ("first_seen", "last_seen"):
            if column not in edge_cols:
                conn.execute(f"ALTER TABLE edges ADD COLUMN {column} TEXT")

        # absolute_rank was added after the table; a database created in between has
        # organic rank only. Additive, same pattern as the nodes columns above.
        rank_tables = {row[0] for row in
                       conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "rank_observations" in rank_tables:
            rank_cols = {row[1] for row in
                         conn.execute("PRAGMA table_info(rank_observations)")}
            if "absolute_rank" not in rank_cols:
                conn.execute("ALTER TABLE rank_observations ADD COLUMN absolute_rank INTEGER")
                
        # Ensure launches and rank_observations tables exist if migrating an older database
        # (This is mostly redundant with _init_db but protects against partial migrations)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "launches" in tables:
            launch_cols = {row[1] for row in conn.execute("PRAGMA table_info(launches)")}
            if "is_control" not in launch_cols:
                conn.execute("ALTER TABLE launches ADD COLUMN "
                             "is_control INTEGER NOT NULL DEFAULT 0")
        if "rank_observations" not in tables:
            conn.execute("""
                CREATE TABLE rank_observations (
                    listing_id TEXT NOT NULL,
                    term_id TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    rank INTEGER,
                    page INTEGER,
                    is_ad BOOLEAN,
                    competitor_count INTEGER,
                    PRIMARY KEY (listing_id, term_id, observed_at)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rank_obs "
                         "ON rank_observations(listing_id, observed_at)")

            # The other half of the outcome. Rank is a proxy; this is the thing the
            # prediction was actually about. A listing can sit at rank 3 and sell
            # nothing, and scoring the model on rank alone would call that a success.
            #
            # Append-only with collected_at in the key (D-04). Every metric is
            # NULLABLE and no metric is derived from another: the operator reads
            # these off Etsy's own stats page, and a partial reading ("I know the
            # sales, not the views") must be recordable without inventing the rest.
            # Absent is not zero (N-02) — a launch with no outcome row has not been
            # measured, which is different from one that sold nothing.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS launch_outcomes (
                    listing_id TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    sales INTEGER,
                    revenue REAL,
                    views INTEGER,
                    favorites INTEGER,
                    note TEXT,
                    PRIMARY KEY (listing_id, collected_at)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_launch_outcomes "
                         "ON launch_outcomes(listing_id, collected_at)")

    def add_node(self, node_data):
        """Upsert the node's latest state AND append the metric snapshot to
        node_observations.

        This used to be a bare INSERT OR REPLACE, which (a) destroyed the previous
        metric values — re-crawling a term erased its history — and (b) NULLed every
        column the caller didn't supply. Now a re-write COALESCEs against the existing
        row (a missing field keeps its old value, it does not blank it), and the
        history question is answered by node_observations instead of being destroyed.
        """
        now = _utcnow()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO nodes (
                    term_id, term, volume, supply, cvr_raw, wow_value, wow_trend,
                    price_low, price_high, depth, parent_id, fetched_at,
                    series_json, listings_json, edges_json,
                    source, node_type, seasonality_score, mom_change, yoy_change, search_count,
                    demographics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(term_id) DO UPDATE SET
                    term              = COALESCE(excluded.term, nodes.term),
                    volume            = COALESCE(excluded.volume, nodes.volume),
                    supply            = COALESCE(excluded.supply, nodes.supply),
                    cvr_raw           = COALESCE(excluded.cvr_raw, nodes.cvr_raw),
                    wow_value         = COALESCE(excluded.wow_value, nodes.wow_value),
                    wow_trend         = COALESCE(excluded.wow_trend, nodes.wow_trend),
                    price_low         = COALESCE(excluded.price_low, nodes.price_low),
                    price_high        = COALESCE(excluded.price_high, nodes.price_high),
                    depth             = COALESCE(excluded.depth, nodes.depth),
                    parent_id         = COALESCE(excluded.parent_id, nodes.parent_id),
                    fetched_at        = excluded.fetched_at,
                    series_json       = COALESCE(excluded.series_json, nodes.series_json),
                    listings_json     = COALESCE(excluded.listings_json, nodes.listings_json),
                    edges_json        = COALESCE(excluded.edges_json, nodes.edges_json),
                    source            = COALESCE(excluded.source, nodes.source),
                    node_type         = COALESCE(excluded.node_type, nodes.node_type),
                    seasonality_score = COALESCE(excluded.seasonality_score, nodes.seasonality_score),
                    mom_change        = COALESCE(excluded.mom_change, nodes.mom_change),
                    yoy_change        = COALESCE(excluded.yoy_change, nodes.yoy_change),
                    search_count      = COALESCE(excluded.search_count, nodes.search_count),
                    demographics_json = COALESCE(excluded.demographics_json, nodes.demographics_json)
            """, (
                node_data.get('term_id'),
                node_data.get('term'),
                node_data.get('volume'),
                node_data.get('supply'),
                node_data.get('cvr_raw'),
                node_data.get('wow_value'),
                node_data.get('wow_trend'),
                node_data.get('price_low'),
                node_data.get('price_high'),
                node_data.get('depth'),
                node_data.get('parent_id'),
                now,
                json.dumps(node_data['series']) if node_data.get('series') else None,
                json.dumps(node_data['listings']) if node_data.get('listings') else None,
                json.dumps(node_data['edges']) if node_data.get('edges') else None,
                node_data.get('source', 'etsy'),
                node_data.get('node_type', 'term'),
                node_data.get('seasonality_score'),
                node_data.get('mom_change'),
                node_data.get('yoy_change'),
                node_data.get('search_count'),
                json.dumps(node_data['demographics']) if node_data.get('demographics') else None,
            ))
            self._observe(conn, node_data.get('term_id'), now,
                          node_data.get('source', 'etsy'),
                          {k: node_data.get(k) for k in OBSERVED_FIELDS})
            conn.commit()

    def _observe(self, conn, term_id, collected_at, source, fields):
        """Append one row to node_observations if any observed metric is present."""
        if term_id is None or not any(fields.get(k) is not None for k in OBSERVED_FIELDS):
            return
        conn.execute("""
            INSERT INTO node_observations (
                term_id, collected_at, source, volume, supply, cvr_raw, wow_value,
                wow_trend, price_low, price_high, seasonality_score, mom_change,
                yoy_change, search_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (term_id, collected_at, source,
              *[fields.get(k) for k in OBSERVED_FIELDS]))

    def get_node_history(self, term_id):
        """Every metric snapshot ever recorded for a term, oldest first."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM node_observations WHERE term_id = ? ORDER BY collected_at",
                (term_id,))]

    def update_node(self, term_id, **fields):
        """Patch specific columns without touching the rest.

        add_node uses INSERT OR REPLACE, which silently NULLs every column it doesn't supply —
        so a later partial write (e.g. batched curves) would wipe the discovery stats written
        earlier. Use this whenever you only have some of the fields.
        """
        if not fields:
            return 0
        cols = ", ".join(f"{k} = ?" for k in fields)
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(f"UPDATE nodes SET {cols} WHERE term_id = ?",
                               (*fields.values(), term_id))
            # Metric patches are history too — same append as add_node.
            observed = {k: v for k, v in fields.items() if k in OBSERVED_FIELDS}
            if cur.rowcount and observed:
                row = conn.execute("SELECT source FROM nodes WHERE term_id = ?",
                                   (term_id,)).fetchone()
                self._observe(conn, term_id, _utcnow(),
                              row[0] if row else None, observed)
            conn.commit()
            return cur.rowcount

    # -- edges -------------------------------------------------------------------------
    # Both writers used INSERT OR REPLACE, which deleted and re-inserted the row — losing
    # when the edge was first discovered. Now first_seen survives re-crawls and last_seen
    # records the most recent sighting; only weight/source are refreshed (kept non-NULL
    # via COALESCE so a weightless re-sighting doesn't erase a measured weight).
    _EDGE_UPSERT = """
        INSERT INTO edges (src, dst, edge_type, source, weight, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(src, dst, edge_type) DO UPDATE SET
            source    = COALESCE(excluded.source, edges.source),
            weight    = COALESCE(excluded.weight, edges.weight),
            last_seen = excluded.last_seen
    """

    def add_edge(self, src, dst, edge_type, source, weight=None):
        now = _utcnow()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(self._EDGE_UPSERT, (src, dst, edge_type, source, weight, now, now))
            conn.commit()

    def add_edges(self, src, dsts, edge_type, source):
        """dsts is an iterable of (dst, weight) pairs or plain strings."""
        now = _utcnow()
        rows = [(src, d[0], edge_type, source, d[1], now, now) if isinstance(d, (tuple, list))
                else (src, d, edge_type, source, None, now, now) for d in dsts]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(self._EDGE_UPSERT, rows)
            conn.commit()
        return len(rows)

    def neighbors(self, term, edge_type=None):
        sql = "SELECT dst, edge_type, source, weight FROM edges WHERE src = ?"
        args = [term]
        if edge_type:
            sql += " AND edge_type = ?"
            args.append(edge_type)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args)]

    def stats(self):
        with sqlite3.connect(self.db_path) as conn:
            out = {
                "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
                "edges": conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
                "frontier": conn.execute("SELECT COUNT(*) FROM frontier").fetchone()[0],
                "by_source": dict(conn.execute(
                    "SELECT COALESCE(source,'unknown'), COUNT(*) FROM nodes GROUP BY 1")),
                "by_edge_type": dict(conn.execute(
                    "SELECT edge_type, COUNT(*) FROM edges GROUP BY 1")),
            }
        return out

    def push_frontier(self, term, depth, parent_id, source=None):
        with sqlite3.connect(self.db_path) as conn:
            # Only push if it hasn't been visited (not in nodes)
            cursor = conn.execute("SELECT 1 FROM nodes WHERE term = ?", (term,))
            if not cursor.fetchone():
                conn.execute("""
                    INSERT OR IGNORE INTO frontier (term, depth, parent_id, source)
                    VALUES (?, ?, ?, ?)
                """, (term, depth, parent_id, source))
            conn.commit()

    def pop_frontier(self, source=None):
        """Claim the shallowest unclaimed term. Shallowest first, so the crawl is
        genuinely breadth-first — the original popped by insert order, which drifts
        depth-first once children start landing.

        **Claims, does not delete.** Call `complete_frontier(term)` once the node is
        safely written. If the process dies between the two, the claim goes stale and
        `reclaim_stale()` puts the term back — at-least-once instead of at-most-once.
        Deleting on pop meant any failed fetch silently dropped a term from the crawl.
        """
        sql = "SELECT term, depth, parent_id, source FROM frontier WHERE claimed_at IS NULL"
        args = []
        if source:
            sql += " AND source = ?"
            args.append(source)
        sql += " ORDER BY depth ASC LIMIT 1"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(sql, args).fetchone()
            if row:
                conn.execute("UPDATE frontier SET claimed_at = ? WHERE term = ?",
                             (datetime.utcnow().isoformat(), row[0]))
                conn.commit()
                return {"term": row[0], "depth": row[1], "parent_id": row[2], "source": row[3]}
            return None

    def complete_frontier(self, term):
        """The term's node is written; drop it from the queue. Idempotent."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM frontier WHERE term = ?", (term,))
            conn.commit()

    def release_frontier(self, term):
        """Hand a claimed term straight back — a fetch failed and we know it now."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE frontier SET claimed_at = NULL WHERE term = ?", (term,))
            conn.commit()

    def reclaim_stale(self, older_than_minutes=30):
        """Release claims from a run that died without releasing them.

        Call at the start of a crawl. Without it a killed run leaves its in-flight
        terms claimed forever and they never get crawled — the same silent hole the
        delete-on-pop bug created, just slower.
        """
        cutoff = (datetime.utcnow() - timedelta(minutes=older_than_minutes)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE frontier SET claimed_at = NULL "
                "WHERE claimed_at IS NOT NULL AND claimed_at < ?", (cutoff,))
            conn.commit()
            return cursor.rowcount

    def is_visited(self, term):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM nodes WHERE term = ?", (term,))
            return cursor.fetchone() is not None

    def get_node(self, term):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM nodes WHERE term = ?", (term,))
            row = cursor.fetchone()
            return dict(row) if row else None

    # -- tracking outcomes (M-3) -------------------------------------------------------

    def record_launch(self, listing_id, term_id, predicted_score=None,
                      predicted_profit=None, product_type=None, notes=None,
                      is_control=False):
        """Record what was launched and what we expected (the prediction snapshot).

        `is_control=True` marks a deliberate mid/low-scored launch. See the B-04 note
        on the launches schema: without controls the LEARN loop can only ever confirm
        its own picks.
        """
        now = _utcnow()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR IGNORE INTO launches (
                    listing_id, term_id, launched_at, predicted_score,
                    predicted_profit, product_type, is_control, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, term_id, now, predicted_score,
                  predicted_profit, product_type, int(bool(is_control)), notes))
            conn.commit()

    def record_rank(self, listing_id, term_id, rank, page=None, is_ad=False,
                    competitor_count=None, observed_at=None, absolute_rank=None):
        """Append one observation of where a listing ranked.

        `rank` is the ORGANIC position, `absolute_rank` the position among everything
        including ads. Both are recorded (MIGRATION_AND_OPERATIONS.md:111).

        `rank=None` means "we looked and it was not in the results" — a measurement.
        Callers must not skip the write in that case; an absent row means "never
        checked", which is a different claim entirely.
        """
        now = observed_at or _utcnow()
        with sqlite3.connect(self.db_path) as conn:
            # OR REPLACE only collides when listing/term/timestamp all match, i.e. the
            # same observation written twice. Distinct days always append.
            conn.execute("""
                INSERT OR REPLACE INTO rank_observations (
                    listing_id, term_id, observed_at, rank, absolute_rank,
                    page, is_ad, competitor_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, term_id, now, rank, absolute_rank, page, is_ad,
                  competitor_count))
            conn.commit()

    def record_launch_outcome(self, listing_id, sales=None, revenue=None, views=None,
                              favorites=None, note=None, collected_at=None):
        """Append one reading of how a launch actually performed.

        Every field optional on purpose. The operator reads these off Etsy's stats
        page, and refusing a partial reading would mean recording nothing at all on
        the days they only know the sales count — which is most days.

        Raises if the listing was never launched: an outcome for a listing the system
        has no prediction for cannot be scored, and silently creating one would put a
        row in the LEARN set that can never be joined.
        """
        if not any(v is not None for v in (sales, revenue, views, favorites, note)):
            raise ValueError("nothing to record — pass at least one metric or a note")
        now = collected_at or _utcnow()
        with sqlite3.connect(self.db_path) as conn:
            known = conn.execute("SELECT 1 FROM launches WHERE listing_id = ?",
                                 (listing_id,)).fetchone()
            if not known:
                raise ValueError(
                    f"listing {listing_id} has no recorded launch, so there is no "
                    f"prediction to score this against. Record the launch first: "
                    f"python -m etsy.analytics.launch --seed TERM --listing-id {listing_id}")
            conn.execute("""
                INSERT OR REPLACE INTO launch_outcomes (
                    listing_id, collected_at, sales, revenue, views, favorites, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (listing_id, now, sales, revenue, views, favorites, note))
            conn.commit()
        return {"listing_id": listing_id, "collected_at": now}

    def latest_outcome(self, listing_id):
        """The most recent outcome reading for a launch, or None if never measured."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""
                SELECT * FROM launch_outcomes WHERE listing_id = ?
                 ORDER BY collected_at DESC LIMIT 1
            """, (listing_id,)).fetchone()
            return dict(row) if row else None

    def outcome_history(self, listing_id):
        """Every reading for one launch, oldest first — the sales curve."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("""
                SELECT * FROM launch_outcomes WHERE listing_id = ?
                 ORDER BY collected_at ASC
            """, (listing_id,))]

    def get_launches(self, term_id=None):
        """Every launch, newest first. Optionally filtered to one term."""
        sql = "SELECT * FROM launches"
        args = []
        if term_id:
            sql += " WHERE term_id = ?"
            args.append(term_id)
        sql += " ORDER BY launched_at DESC"
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args)]

    def launch_count(self, controls_only=False):
        """D-12: no auto-tuning below 10 launches. This is the number that gate reads."""
        sql = "SELECT COUNT(*) FROM launches"
        if controls_only:
            sql += " WHERE is_control = 1"
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(sql).fetchone()[0]

    def control_ratio(self):
        """Share of launches that were controls, or None when nothing has launched.

        None rather than 0.0: an empty table means the ratio was never measured, which
        is not the same claim as "no controls were run". B-04's target is ~0.1; below
        that, calibration is measuring the model against its own preferences.
        """
        total = self.launch_count()
        if not total:
            return None
        return self.launch_count(controls_only=True) / total

    def get_rank_history(self, listing_id):
        """Every rank observation for a listing, oldest first — the outcome curve."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                "SELECT * FROM rank_observations WHERE listing_id = ? ORDER BY observed_at",
                (listing_id,))]

    def prediction_vs_outcome(self):
        """Join each launch to its most recent rank observation.

        The one query the LEARN loop exists to answer: did what we predicted would do
        well actually rank? `latest_rank` is None both when the listing was checked and
        not found AND when it was never checked — `observations` disambiguates, so a
        caller can tell an unranked listing from an untracked one.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("""
                SELECT l.listing_id, l.term_id, l.launched_at, l.predicted_score,
                       l.predicted_profit, l.product_type, l.is_control,
                       (SELECT COUNT(*) FROM rank_observations r
                         WHERE r.listing_id = l.listing_id) AS observations,
                       (SELECT r.rank FROM rank_observations r
                         WHERE r.listing_id = l.listing_id
                         ORDER BY r.observed_at DESC LIMIT 1) AS latest_rank,
                       (SELECT r.observed_at FROM rank_observations r
                         WHERE r.listing_id = l.listing_id
                         ORDER BY r.observed_at DESC LIMIT 1) AS latest_observed_at,
                       (SELECT COUNT(*) FROM launch_outcomes o
                         WHERE o.listing_id = l.listing_id) AS outcome_readings,
                       (SELECT o.sales FROM launch_outcomes o
                         WHERE o.listing_id = l.listing_id
                         ORDER BY o.collected_at DESC LIMIT 1) AS latest_sales,
                       (SELECT o.revenue FROM launch_outcomes o
                         WHERE o.listing_id = l.listing_id
                         ORDER BY o.collected_at DESC LIMIT 1) AS latest_revenue
                  FROM launches l
                 ORDER BY l.launched_at DESC
            """)]

