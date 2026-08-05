import sqlite3
import json
import os

class GraphDB:
    def __init__(self, db_path="data/etsy_graph.db"):
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
            conn.commit()

    def add_node(self, node_data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO nodes (
                    term_id, term, volume, supply, cvr_raw, wow_value, wow_trend, 
                    price_low, price_high, depth, parent_id, series_json, listings_json, edges_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                json.dumps(node_data.get('edges', []))
            ))
            conn.commit()

    def push_frontier(self, term, depth, parent_id):
        with sqlite3.connect(self.db_path) as conn:
            # Only push if it hasn't been visited (not in nodes)
            cursor = conn.execute("SELECT 1 FROM nodes WHERE term = ?", (term,))
            if not cursor.fetchone():
                conn.execute("""
                    INSERT OR IGNORE INTO frontier (term, depth, parent_id)
                    VALUES (?, ?, ?)
                """, (term, depth, parent_id))
            conn.commit()

    def pop_frontier(self):
        with sqlite3.connect(self.db_path) as conn:
            # Pop the highest priority / oldest item
            cursor = conn.execute("SELECT term, depth, parent_id FROM frontier LIMIT 1")
            row = cursor.fetchone()
            if row:
                conn.execute("DELETE FROM frontier WHERE term = ?", (row[0],))
                conn.commit()
                return {"term": row[0], "depth": row[1], "parent_id": row[2]}
            return None

    def is_visited(self, term):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT 1 FROM nodes WHERE term = ?", (term,))
            return cursor.fetchone() is not None

    def get_node(self, term):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM nodes WHERE term = ?", (term,))
            return dict(cursor.fetchone()) if cursor.fetchone() else None
