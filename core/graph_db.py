import sqlite3
import json
import os

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
        if "source" not in {row[1] for row in conn.execute("PRAGMA table_info(frontier)")}:
            conn.execute("ALTER TABLE frontier ADD COLUMN source TEXT")

    def add_node(self, node_data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO nodes (
                    term_id, term, volume, supply, cvr_raw, wow_value, wow_trend,
                    price_low, price_high, depth, parent_id, series_json, listings_json, edges_json,
                    source, node_type, seasonality_score, mom_change, yoy_change, search_count,
                    demographics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(node_data.get('series', [])),
                json.dumps(node_data.get('listings', [])),
                json.dumps(node_data.get('edges', [])),
                node_data.get('source', 'etsy'),
                node_data.get('node_type', 'term'),
                node_data.get('seasonality_score'),
                node_data.get('mom_change'),
                node_data.get('yoy_change'),
                node_data.get('search_count'),
                json.dumps(node_data['demographics']) if node_data.get('demographics') else None,
            ))
            conn.commit()

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
            conn.commit()
            return cur.rowcount

    # -- edges -------------------------------------------------------------------------
    def add_edge(self, src, dst, edge_type, source, weight=None):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO edges (src, dst, edge_type, source, weight)
                VALUES (?, ?, ?, ?, ?)
            """, (src, dst, edge_type, source, weight))
            conn.commit()

    def add_edges(self, src, dsts, edge_type, source):
        """dsts is an iterable of (dst, weight) pairs or plain strings."""
        rows = [(src, d[0], edge_type, source, d[1]) if isinstance(d, (tuple, list))
                else (src, d, edge_type, source, None) for d in dsts]
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany("""
                INSERT OR REPLACE INTO edges (src, dst, edge_type, source, weight)
                VALUES (?, ?, ?, ?, ?)
            """, rows)
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
        """Shallowest first, so the crawl is genuinely breadth-first. The original popped by
        insert order, which drifts depth-first once children start landing."""
        sql = "SELECT term, depth, parent_id, source FROM frontier"
        args = []
        if source:
            sql += " WHERE source = ?"
            args.append(source)
        sql += " ORDER BY depth ASC LIMIT 1"
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(sql, args).fetchone()
            if row:
                conn.execute("DELETE FROM frontier WHERE term = ?", (row[0],))
                conn.commit()
                return {"term": row[0], "depth": row[1], "parent_id": row[2], "source": row[3]}
            return None

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
