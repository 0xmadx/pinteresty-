import sqlite3
import os
import json
from datetime import datetime, timezone

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
            
            # Trends Table (legacy — superseded by trend_observations below).
            # Kept so an existing database still opens; it has no writer and 0 rows.
            # Do not add one: reads go through the trends_latest view instead.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trends (
                    trend_name TEXT PRIMARY KEY,
                    dominant_color TEXT,
                    demographic TEXT,
                    takeoff_timestamp TEXT,
                    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Trend Observations — the Pinterest -> Etsy handoff.
            #
            # Append-only: collected_at is part of the key, so re-observing a trend adds a
            # row instead of destroying the previous one. This is the LEARN requirement
            # (DECISION_LOG.md D-04) and it cannot be retrofitted once rows accumulate.
            #
            # Every value carries a *_basis column recording whether it was measured at the
            # source or derived by us, because the failure mode here is a plausible wrong
            # number rather than an error (GOAL.md, "Honesty").
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trend_observations (
                    trend_name        TEXT NOT NULL,
                    collected_at      TEXT NOT NULL,
                    country           TEXT NOT NULL DEFAULT 'US',
                    source            TEXT NOT NULL,
                    dominant_color    TEXT,
                    color_share       REAL,
                    color_basis       TEXT,
                    demographic       TEXT,
                    demographic_basis TEXT,
                    takeoff_timestamp TEXT,
                    list_by           TEXT,
                    takeoff_basis     TEXT,
                    growth_mom        REAL,
                    velocity          REAL,
                    velocity_basis    TEXT,
                    PRIMARY KEY (trend_name, collected_at, country, source)
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_trend_obs_name
                ON trend_observations(trend_name, country)
            ''')

            # Current-state read path. Callers that only want "what is true now" use this
            # and never see the history, so making the table append-only did not change
            # any existing caller.
            cursor.execute('''
                CREATE VIEW IF NOT EXISTS trends_latest AS
                SELECT t.* FROM trend_observations t
                WHERE t.collected_at = (
                    SELECT MAX(collected_at) FROM trend_observations
                    WHERE trend_name = t.trend_name AND country = t.country
                )
            ''')
            
            # Keyword Observations — append-only replacement for `keywords`.
            #
            # cvr_source is the guard flag from DECISION_LOG.md D-06: a CVR that was
            # actually measured and one that fell back to the 0.02 default are different
            # numbers, and the old schema stored them in the same column indistinguishably.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keyword_observations (
                    keyword           TEXT NOT NULL,
                    collected_at      TEXT NOT NULL,
                    source            TEXT NOT NULL,
                    search_volume     INTEGER,
                    competition       INTEGER,
                    query_cvr         REAL,
                    cvr_source        TEXT,
                    median_price_low  REAL,
                    median_price_high REAL,
                    price_basis       TEXT,
                    PRIMARY KEY (keyword, collected_at, source)
                )
            ''')
            cursor.execute('''
                CREATE VIEW IF NOT EXISTS keywords_latest AS
                SELECT k.* FROM keyword_observations k
                WHERE k.collected_at = (
                    SELECT MAX(collected_at) FROM keyword_observations
                    WHERE keyword = k.keyword)
            ''')

            # Listing Observations — append-only replacement for `listings`.
            #
            # estimated_sales used to hold two different quantities depending on which
            # branch produced it (grid_analytics.py:152 vs :158): a lifetime ratio estimate
            # and a 30-day extrapolation. They differ by an unknown factor and were not
            # comparable across rows. They are separate columns here, each with its basis.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS listing_observations (
                    listing_id         TEXT NOT NULL,
                    collected_at       TEXT NOT NULL,
                    shop_name          TEXT,
                    price              REAL,
                    sales_lifetime_est INTEGER,
                    sales_30d_est      INTEGER,
                    sales_basis        TEXT,
                    estimated_views    INTEGER,
                    views_basis        TEXT,
                    velocity_score     TEXT,
                    daily_sales        INTEGER,
                    daily_views        INTEGER,
                    scarcity_stock     INTEGER,
                    badge_present      INTEGER,
                    demand_signals     TEXT,
                    total_reviews      INTEGER,
                    PRIMARY KEY (listing_id, collected_at)
                )
            ''')
            cursor.execute('''
                CREATE VIEW IF NOT EXISTS listings_latest AS
                SELECT l.* FROM listing_observations l
                WHERE l.collected_at = (
                    SELECT MAX(collected_at) FROM listing_observations
                    WHERE listing_id = l.listing_id)
            ''')

            # Listing flaws are LLM output, not a scraped fact, so they live apart from the
            # measured columns rather than sharing a row with them.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS listing_flaws (
                    listing_id   TEXT NOT NULL,
                    collected_at TEXT NOT NULL,
                    flaws_text   TEXT,
                    model        TEXT,
                    PRIMARY KEY (listing_id, collected_at)
                )
            ''')

            # Shop Observations — the daily sales delta, the system's ONE measured
            # sales number. Everything else (estimate_sales, the ratio estimator, badge
            # math) is inferred; this is a difference between two counters Etsy itself
            # publishes.
            #
            # ⚠️ window_days is not decoration. A "daily" delta measured across an
            # unknown gap is the classic units bug: run the tracker Monday and next
            # Friday and the difference is a 4-day figure. Compared as daily it inflates
            # every downstream rate 4x, and nothing in the number itself reveals that.
            # sales_per_day is the only field safe to compare across shops or dates.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS shop_observations (
                    shop_name     TEXT NOT NULL,
                    collected_at  TEXT NOT NULL,
                    total_sales   INTEGER,
                    total_reviews INTEGER,
                    sales_delta   INTEGER,
                    window_days   REAL,
                    sales_per_day REAL,
                    basis         TEXT NOT NULL,
                    PRIMARY KEY (shop_name, collected_at)
                )
            ''')

            # --- SCHEMA MIGRATIONS (additive columns) ---
            #
            # These were four `try: ALTER ... except: pass` pairs. A bare except cannot
            # tell "this column already exists" (the expected case, every run after the
            # first) from "the database is locked" or "the SQL is wrong" — so a genuinely
            # broken migration left the table silently short a column, and every later
            # write of that field failed for a reason nobody could see.
            #
            # Ask instead of guessing, the same way graph_db._migrate does.
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(listings)")}
            for column, decl in [
                ("daily_sales", "INTEGER DEFAULT 0"),
                ("daily_views", "INTEGER DEFAULT 0"),
                ("scarcity_stock", "INTEGER DEFAULT 0"),
                ("demand_signals", "TEXT"),
            ]:
                if column not in existing:
                    # No try/except: if this fails now, it is a real failure and should
                    # be loud. The only expected error was the one we just ruled out.
                    cursor.execute(f"ALTER TABLE listings ADD COLUMN {column} {decl}")

            conn.commit()

    # --- KEYWORDS API ---
    def record_keyword(self, keyword, source="etsy_private", collected_at=None,
                       volume=None, competition=None, cvr=None, cvr_source="unspecified",
                       price_low=None, price_high=None, price_basis="measured"):
        """Append one observation of a keyword. Never overwrites.

        cvr_source must say where the CVR came from: 'measured' when the source returned
        one, 'default' when it fell back to the 0.02 assumption. Storing those two as the
        same number is how a guess becomes indistinguishable from a measurement.
        """
        collected_at = collected_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO keyword_observations (
                    keyword, collected_at, source, search_volume, competition,
                    query_cvr, cvr_source, median_price_low, median_price_high, price_basis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (keyword, collected_at, source, volume, competition,
                  cvr, cvr_source, price_low, price_high, price_basis))
            conn.commit()
        return collected_at

    def upsert_keyword(self, keyword, volume, competition, cvr, price_low, price_high):
        """Backward-compatible entry point for existing callers (private_blueprint.py:93).

        The name is kept so call sites need no edit, but this now APPENDS rather than
        overwriting. Legacy callers cannot say whether the CVR was measured or defaulted,
        so provenance is recorded as 'unspecified' — which is honest, and is the signal to
        migrate the caller to record_keyword().
        """
        return self.record_keyword(
            keyword=keyword, source="legacy_upsert", volume=volume, competition=competition,
            cvr=cvr, cvr_source="unspecified", price_low=price_low, price_high=price_high,
            price_basis="unspecified")

    def get_keyword(self, keyword):
        """Current state. Shape matches the pre-append-only version, so
        grid_analytics.py:34 and master_arbitrage.py:241 need no change."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM keywords_latest WHERE keyword = ?', (keyword,)).fetchone()
            return dict(row) if row else None

    def get_keyword_history(self, keyword):
        """Every observation, oldest first."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                'SELECT * FROM keyword_observations WHERE keyword = ? '
                'ORDER BY collected_at ASC', (keyword,))]

    # --- LISTINGS API ---
    def record_listing(self, listing_id, collected_at=None, shop_name=None, price=None,
                       sales_lifetime_est=None, sales_30d_est=None, sales_basis="unspecified",
                       estimated_views=None, views_basis="unspecified", velocity_score=None,
                       daily_sales=None, daily_views=None, scarcity_stock=None,
                       badge_present=None, demand_signals=None, total_reviews=None):
        """Append one observation of a listing. Never overwrites.

        Two things the old schema could not express, both of which produced numbers that
        looked measured and were not:

        `sales_lifetime_est` and `sales_30d_est` are separate because they are different
        quantities — a review-ratio estimate over the listing's life, and a 30-day run rate
        extrapolated from a daily-sales badge. The old column held whichever branch ran.

        `badge_present` disambiguates zero: daily_sales=0 means "no urgency badge on the
        page" far more often than it means "sold nothing today", and downstream code
        branched on `> 0` as though those were the same.
        """
        collected_at = collected_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        if isinstance(demand_signals, (list, dict)):
            demand_signals = json.dumps(demand_signals)
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO listing_observations (
                    listing_id, collected_at, shop_name, price,
                    sales_lifetime_est, sales_30d_est, sales_basis,
                    estimated_views, views_basis, velocity_score,
                    daily_sales, daily_views, scarcity_stock, badge_present,
                    demand_signals, total_reviews
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (listing_id, collected_at, shop_name, price,
                  sales_lifetime_est, sales_30d_est, sales_basis,
                  estimated_views, views_basis, velocity_score,
                  daily_sales, daily_views, scarcity_stock,
                  None if badge_present is None else int(bool(badge_present)),
                  demand_signals, total_reviews))
            conn.commit()
        return collected_at

    def upsert_listing_metrics(self, listing_id, shop_name, price, est_sales, est_views, velocity,
                               daily_sales=0, daily_views=0, scarcity_stock=0, demand_signals=""):
        """Backward-compatible entry point (grid_analytics.py:214, single_listing_analytics.py:151).

        Now APPENDS. The caller passes a single `est_sales` without saying which quantity it
        is, so it lands in sales_lifetime_est with basis 'unspecified'. Migrating the caller
        to record_listing() is what turns that into a real answer.
        """
        return self.record_listing(
            listing_id=listing_id, shop_name=shop_name, price=price,
            sales_lifetime_est=est_sales, sales_basis="unspecified",
            estimated_views=est_views, views_basis="unspecified",
            velocity_score=velocity, daily_sales=daily_sales, daily_views=daily_views,
            scarcity_stock=scarcity_stock, demand_signals=demand_signals)

    def upsert_listing_flaws(self, listing_id, flaws_text, model="deepseek-chat"):
        """Append LLM flaw analysis. Stored apart from the measured columns.

        The old version inserted into `listings`, so calling it for an unseen listing
        created a row where every metric was NULL — a listing that looked observed and
        never was.
        """
        collected_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO listing_flaws (listing_id, collected_at, flaws_text, model)
                VALUES (?, ?, ?, ?)
            ''', (listing_id, collected_at, flaws_text, model))
            conn.commit()
        return collected_at

    def get_listing(self, listing_id):
        """Current state, with the latest flaw analysis joined on.

        Keeps `estimated_sales` and `top_flaws` in the returned dict so
        master_listing_analyzer.py:71 needs no change.
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM listings_latest WHERE listing_id = ?', (listing_id,)).fetchone()
            if not row:
                return None
            out = dict(row)
            flaw = conn.execute(
                'SELECT flaws_text FROM listing_flaws WHERE listing_id = ? '
                'ORDER BY collected_at DESC LIMIT 1', (listing_id,)).fetchone()
            out["top_flaws"] = flaw["flaws_text"] if flaw else None
            # Legacy alias. Prefer the explicit columns — this one cannot say which
            # quantity it holds, which is the ambiguity the split was made to remove.
            out["estimated_sales"] = out.get("sales_30d_est") or out.get("sales_lifetime_est")
            return out

    def get_listing_history(self, listing_id):
        """Every observation, oldest first."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                'SELECT * FROM listing_observations WHERE listing_id = ? '
                'ORDER BY collected_at ASC', (listing_id,))]
            
    # --- TRENDS API ---
    def record_trend(self, trend_name, source, country="US", collected_at=None,
                     dominant_color=None, color_share=None, color_basis=None,
                     demographic=None, demographic_basis=None,
                     takeoff_timestamp=None, list_by=None, takeoff_basis=None,
                     growth_mom=None, velocity=None, velocity_basis=None):
        """Append one Pinterest observation of a trend. Never overwrites.

        This is the write side of the handoff described in
        docs/_old/_old_etsy_master_architecture.md:119 — the half that was specified but
        never built, which is why the trends table sat empty while Pinterest held 954 rows.

        `demographic` is stored as JSON. Re-running on the same UTC second is the only case
        that collides, and that is a genuine duplicate, so INSERT OR REPLACE is correct
        there and nowhere else.
        """
        collected_at = collected_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
        if isinstance(demographic, (dict, list)):
            demographic = json.dumps(demographic)

        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO trend_observations (
                    trend_name, collected_at, country, source,
                    dominant_color, color_share, color_basis,
                    demographic, demographic_basis,
                    takeoff_timestamp, list_by, takeoff_basis,
                    growth_mom, velocity, velocity_basis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (trend_name, collected_at, country, source,
                  dominant_color, color_share, color_basis,
                  demographic, demographic_basis,
                  takeoff_timestamp, list_by, takeoff_basis,
                  growth_mom, velocity, velocity_basis))
            conn.commit()
        return collected_at

    def get_trend(self, trend_name, country="US"):
        """Current state for one trend. Reads the latest observation, not the history.

        Shape is backward-compatible with the pre-append-only version, so
        master_arbitrage.py:242 needs no change.
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM trends_latest WHERE trend_name = ? AND country = ?',
                (trend_name, country)).fetchone()
            if not row:
                return None
            out = dict(row)
            if out.get("demographic"):
                try:
                    out["demographic"] = json.loads(out["demographic"])
                except (ValueError, TypeError):
                    pass
            return out

    def find_trend(self, keyword, country="US"):
        """Pinterest trend data for an ETSY keyword, joining across the wording gap.

        `get_trend` is an exact match, so the bridge writing "Mom Necklaces" and the
        engine asking for "mom necklace" miss each other and the candidate scores with
        no momentum — a free dimension lost silently. This normalises both sides
        (overviews.md §5) and matches on the content-word set.

        Returns None rather than a near-match: importing "cat collar"'s momentum for
        "dog collar" would be a wrong number wearing the right label.
        """
        exact = self.get_trend(keyword, country)
        if exact:
            return exact

        from etsy.analytics.term_join import best_match
        with self.get_connection() as conn:
            names = [r[0] for r in conn.execute(
                'SELECT DISTINCT trend_name FROM trends_latest WHERE country = ?',
                (country,))]
        matched = best_match(keyword, names)
        return self.get_trend(matched, country) if matched else None

    def get_trend_history(self, trend_name, country="US"):
        """Every observation for a trend, oldest first — the reason for append-only."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                'SELECT * FROM trend_observations WHERE trend_name = ? AND country = ? '
                'ORDER BY collected_at ASC', (trend_name, country))]

    # --- SHOP OBSERVATIONS API (the daily delta) ---
    def record_shop_observation(self, shop_name, total_sales, total_reviews=None,
                                collected_at=None):
        """Append one shop reading and derive the delta against the previous one.

        Receives: lifetime counters scraped from a shop page (`ShopScraper`).
        Emits: an append-only row carrying the absolute totals AND the derived rate.

        The delta is computed here rather than by the caller so the window can never be
        assumed. Three outcomes, each with its own basis:

          baseline          first sighting — no previous reading to difference against
          measured_delta    a real difference over a known window
          counter_decreased the lifetime counter went DOWN, which it cannot legitimately
                            do (Etsy does not un-sell). Something changed underneath —
                            a shop rename, a scrape parsing a different element, a
                            platform edit. Storing a negative "delta" would silently
                            drag every downstream rate below zero, so the delta is
                            refused while the observation is still kept, making the
                            anomaly visible instead of invisible.
        """
        now = collected_at or datetime.now(timezone.utc).isoformat()
        previous = self.latest_shop_observation(shop_name)

        delta = window_days = per_day = None
        basis = "baseline"
        if previous and previous.get("total_sales") is not None:
            raw = total_sales - previous["total_sales"]
            if raw < 0:
                basis = "counter_decreased"
            else:
                gap = (datetime.fromisoformat(now)
                       - datetime.fromisoformat(previous["collected_at"]))
                window_days = round(gap.total_seconds() / 86400.0, 6)
                delta = raw
                basis = "measured_delta"
                # A zero-length window cannot produce a rate; dividing would be a
                # division by zero dressed up as an infinite sales rate.
                per_day = round(raw / window_days, 6) if window_days > 0 else None

        row = {
            "shop_name": shop_name, "collected_at": now,
            "total_sales": total_sales, "total_reviews": total_reviews,
            "sales_delta": delta, "window_days": window_days,
            "sales_per_day": per_day, "basis": basis,
        }
        with self.get_connection() as conn:
            # Same instant twice is the same observation, not two.
            conn.execute('''
                INSERT OR REPLACE INTO shop_observations (
                    shop_name, collected_at, total_sales, total_reviews,
                    sales_delta, window_days, sales_per_day, basis
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shop_name, now, total_sales, total_reviews, delta, window_days,
                  per_day, basis))
            conn.commit()
        return row

    def latest_shop_observation(self, shop_name):
        """The most recent reading for a shop, or None if never seen."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM shop_observations WHERE shop_name = ? '
                'ORDER BY collected_at DESC LIMIT 1', (shop_name,)).fetchone()
            return dict(row) if row else None

    def get_shop_history(self, shop_name):
        """Every reading for a shop, oldest first."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(
                'SELECT * FROM shop_observations WHERE shop_name = ? '
                'ORDER BY collected_at ASC', (shop_name,))]

    def latest_shop_rate(self, shop_name):
        """Most recent measured sales-per-day, or None when none has been measured.

        This is the calibration target bias B-03 asks for: badge-derived sales figures
        ("17 bought today") are observed only on above-threshold days and must be bounded
        against something actually measured. None means unmeasured — callers must not
        substitute 0.0, which would read as "this shop sells nothing".
        """
        with self.get_connection() as conn:
            row = conn.execute(
                'SELECT sales_per_day FROM shop_observations '
                'WHERE shop_name = ? AND sales_per_day IS NOT NULL '
                'ORDER BY collected_at DESC LIMIT 1', (shop_name,)).fetchone()
            return row[0] if row else None
