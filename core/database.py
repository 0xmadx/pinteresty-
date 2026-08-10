import sqlite3
import os

class MarketDatabase:
    """
    Central Market Intelligence Database for the Etsy Arbitrage Engine.
    Unifies data from Private API, Public API, DeepSeek, and Pinterest.
    """
    def __init__(self, db_path="market_intelligence.db"):
        # Put the database in the root repository folder
        self.db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), db_path)
        self._init_db()
        
    def get_connection(self):
        return sqlite3.connect(self.db_path)
        
    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Keywords Table (Populated by private_blueprint.py)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keywords (
                    keyword TEXT PRIMARY KEY,
                    search_volume INTEGER,
                    competition INTEGER,
                    query_cvr REAL,
                    median_price_low REAL,
                    median_price_high REAL,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Listings Table (Populated by grid_analytics & sentiment_analytics)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS listings (
                    listing_id TEXT PRIMARY KEY,
                    shop_name TEXT,
                    price REAL,
                    estimated_sales INTEGER,
                    estimated_views INTEGER,
                    velocity_score TEXT,
                    top_flaws TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Trends Table (For Pinterest Claude Code)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trends (
                    trend_name TEXT PRIMARY KEY,
                    dominant_color TEXT,
                    demographic TEXT,
                    takeoff_timestamp TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # --- SCHEMA MIGRATIONS (Safe updates for new columns) ---
            try: cursor.execute("ALTER TABLE listings ADD COLUMN daily_sales INTEGER DEFAULT 0")
            except: pass
            try: cursor.execute("ALTER TABLE listings ADD COLUMN daily_views INTEGER DEFAULT 0")
            except: pass
            try: cursor.execute("ALTER TABLE listings ADD COLUMN scarcity_stock INTEGER DEFAULT 0")
            except: pass
            try: cursor.execute("ALTER TABLE listings ADD COLUMN demand_signals TEXT")
            except: pass
            
            conn.commit()

    # --- KEYWORDS API ---
    def upsert_keyword(self, keyword, volume, competition, cvr, price_low, price_high):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO keywords (keyword, search_volume, competition, query_cvr, median_price_low, median_price_high)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(keyword) DO UPDATE SET
                    search_volume=excluded.search_volume,
                    competition=excluded.competition,
                    query_cvr=excluded.query_cvr,
                    median_price_low=excluded.median_price_low,
                    median_price_high=excluded.median_price_high,
                    last_updated=CURRENT_TIMESTAMP
            ''', (keyword, volume, competition, cvr, price_low, price_high))
            conn.commit()
            
    def get_keyword(self, keyword):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM keywords WHERE keyword = ?', (keyword,))
            row = cursor.fetchone()
            if row:
                return {
                    "keyword": row[0],
                    "search_volume": row[1],
                    "competition": row[2],
                    "query_cvr": row[3],
                    "median_price_low": row[4],
                    "median_price_high": row[5]
                }
            return None

    # --- LISTINGS API ---
    def upsert_listing_metrics(self, listing_id, shop_name, price, est_sales, est_views, velocity, 
                               daily_sales=0, daily_views=0, scarcity_stock=0, demand_signals=""):
        """Used by analytics to save financial metrics & live demand signals"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO listings (listing_id, shop_name, price, estimated_sales, estimated_views, velocity_score, daily_sales, daily_views, scarcity_stock, demand_signals)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    shop_name=excluded.shop_name,
                    price=excluded.price,
                    estimated_sales=excluded.estimated_sales,
                    estimated_views=excluded.estimated_views,
                    velocity_score=excluded.velocity_score,
                    daily_sales=excluded.daily_sales,
                    daily_views=excluded.daily_views,
                    scarcity_stock=excluded.scarcity_stock,
                    demand_signals=excluded.demand_signals,
                    last_updated=CURRENT_TIMESTAMP
            ''', (listing_id, shop_name, price, est_sales, est_views, velocity, daily_sales, daily_views, scarcity_stock, demand_signals))
            conn.commit()
            
    def upsert_listing_flaws(self, listing_id, flaws_text):
        """Used by sentiment_analytics to save DeepSeek output"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO listings (listing_id, top_flaws)
                VALUES (?, ?)
                ON CONFLICT(listing_id) DO UPDATE SET
                    top_flaws=excluded.top_flaws,
                    last_updated=CURRENT_TIMESTAMP
            ''', (listing_id, flaws_text))
            conn.commit()
            
    def get_listing(self, listing_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM listings WHERE listing_id = ?', (listing_id,))
            row = cursor.fetchone()
            if row:
                return {
                    "listing_id": row[0],
                    "shop_name": row[1],
                    "price": row[2],
                    "estimated_sales": row[3],
                    "estimated_views": row[4],
                    "velocity_score": row[5],
                    "top_flaws": row[6]
                }
            return None
            
    # --- TRENDS API ---
    def get_trend(self, trend_name):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM trends WHERE trend_name = ?', (trend_name,))
            row = cursor.fetchone()
            if row:
                return {
                    "trend_name": row[0],
                    "dominant_color": row[1],
                    "demographic": row[2],
                    "takeoff_timestamp": row[3]
                }
            return None
