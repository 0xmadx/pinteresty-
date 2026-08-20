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

            # Competition observations — the PUBLIC-SERP counterpart to
            # keyword_observations (which is private-API demand). Kept separate on
            # purpose: it is a different source, a different cadence, and its
            # saturation numbers are a page-one SAMPLE with confidence bounds, not
            # the market-wide counts keyword_observations carries. Blending the two
            # would be the unit-mixing error card_saturation exists to prevent.
            #
            # saturation_json holds card_saturation.profile() verbatim, so the
            # Wilson interval and can_discriminate flag survive to the reader.
            # ranked_ids_count is the upgrade signal: how many listing pages a
            # deeper sample could open (39-51 typically), against the ~9 cards this
            # row measured.
            # Discovered candidates — the ranked opportunity POOL, terms the
            # operator has not typed. Populated by discover_sweep from the LLM
            # keyword endpoint, whose edges carry their own volume and supply so
            # winnability is computable without a call per term.
            #
            # Append-only, keyed by the run, so a later sweep does not overwrite an
            # earlier pool — the same term can be discovered from two seeds, or move
            # between runs, and both facts are worth keeping. `demand_per_listing`
            # is stored so the pool can be ranked without recomputing, and `verdict`
            # is the coarse winnable/contested/wall label (D-31): never a score.
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS discovered_candidates (
                    term               TEXT NOT NULL,
                    collected_at       TEXT NOT NULL,
                    seed               TEXT,
                    volume             INTEGER,
                    supply             INTEGER,
                    demand_per_listing REAL,
                    cvr                REAL,
                    verdict            TEXT,
                    moment             TEXT,
                    list_by            TEXT,
                    timing             TEXT,
                    PRIMARY KEY (term, collected_at, seed)
                )
            ''')

            cursor.execute('''
                CREATE TABLE IF NOT EXISTS keyword_competition (
                    keyword          TEXT NOT NULL,
                    collected_at     TEXT NOT NULL,
                    source           TEXT NOT NULL DEFAULT 'etsy_public',
                    total_results    INTEGER,
                    organic_sample   INTEGER,
                    ranked_ids_count INTEGER,
                    saturation_json  TEXT,
                    median_delivery  TEXT,
                    PRIMARY KEY (keyword, collected_at, source)
                )
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

            # Competitor outcome tracking (D-25) extends `listing_observations` rather
            # than creating a second table for the same concept. That table already
            # holds one listing over time, already carries `total_reviews`, and a
            # parallel table would give the system two answers to "how many reviews
            # does this listing have" — the shape of every expensive bug here.
            #
            # `first_seen_at` is named for what it is: the first time WE looked, not
            # when the listing was created. Etsy does not publish a creation date on the
            # shop page, so "listed 3 weeks ago" is only true of listings we watched
            # appear. Calling it `listed_at` would invent a fact, and a wrong age makes
            # every velocity built on it wrong.
            trend_cols = {row[1] for row in
                          cursor.execute("PRAGMA table_info(trend_observations)")}
            for column, decl in [
                # The calendar's most valuable distinction is LATE vs MISSED, and it
                # needs the peak: a deadline that passed while the peak is still two
                # months out is a live opportunity, not a lost one. Storing only the
                # takeoff threw that away.
                ("peak_date", "TEXT"),
                ("peak_length_days", "INTEGER"),
                ("phase", "TEXT"),
            ]:
                if column not in trend_cols:
                    cursor.execute(
                        f"ALTER TABLE trend_observations ADD COLUMN {column} {decl}")

            shop_cols = {row[1] for row in
                         cursor.execute("PRAGMA table_info(shop_observations)")}
            for column, decl in [
                # Etsy's lifetime sales counter is QUANTISED at scale — a shop showing
                # "25,100" moves in steps of 100, so a zero delta means "moved less
                # than the counter can display", not "sold nothing". The rate is
                # refused in that case and this bound carries what IS known.
                ("sales_per_day_upper", "REAL"),
                ("counter_resolution", "INTEGER"),
            ]:
                if column not in shop_cols:
                    cursor.execute(
                        f"ALTER TABLE shop_observations ADD COLUMN {column} {decl}")

            observed = {row[1] for row in
                        cursor.execute("PRAGMA table_info(listing_observations)")}
            for column, decl in [
                ("title", "TEXT"),
                ("rating", "REAL"),
                ("is_ad", "INTEGER"),
                ("first_seen_at", "TEXT"),
                ("matched_term", "TEXT"),
                # Not plain `basis`: the table already has sales_basis and views_basis,
                # and a bare `basis` beside them would read as "the row's basis".
                ("sighting_basis", "TEXT"),
            ]:
                if column not in observed:
                    cursor.execute(
                        f"ALTER TABLE listing_observations ADD COLUMN {column} {decl}")

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
                     growth_mom=None, velocity=None, velocity_basis=None,
                     peak_date=None, peak_length_days=None, phase=None):
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
                    growth_mom, velocity, velocity_basis,
                    peak_date, peak_length_days, phase
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (trend_name, collected_at, country, source,
                  dominant_color, color_share, color_basis,
                  demographic, demographic_basis,
                  takeoff_timestamp, list_by, takeoff_basis,
                  growth_mom, velocity, velocity_basis,
                  peak_date, peak_length_days, phase))
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
    # A bound computed over a very short window is arithmetically correct and
    # practically empty: 99 unseen sales across 9 minutes bounds the rate at
    # 16,000/day, which excludes nothing. Below this window a below_resolution
    # reading is recorded but its bound is marked uninformative rather than being
    # presented as a constraint — the same treatment survivor_bound gives a 100%
    # share.
    MIN_INFORMATIVE_WINDOW_DAYS = 1.0

    @staticmethod
    def bound_is_informative(window_days):
        """Does this window make the upper bound worth reporting?"""
        return bool(window_days and window_days >= MarketDatabase.MIN_INFORMATIVE_WINDOW_DAYS)

    @staticmethod
    def counter_resolution(total_sales):
        """The smallest change Etsy's shop counter can actually display.

        Etsy shows an exact number for a small shop and rounds at scale, so "25,100"
        is not 25,100 — it is somewhere in [25,100, 25,200). Inferred from the value
        itself rather than from a magnitude threshold: a shop reporting 8,143 is
        clearly unrounded whatever its size, and one reporting 25,100 clearly is not.
        Returns 1 when the number carries full precision.

        This matters because the resolution is the ERROR BAR on every delta. Two
        readings 4.7 days apart on a counter that steps by 100 cannot distinguish
        "sold nothing" from "sold 99", and those are opposite conclusions about a
        competitor.
        """
        if total_sales is None or total_sales < 1000:
            return 1
        for step in (1000, 100, 10):
            if total_sales % step == 0:
                return step
        return 1

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
          below_resolution  the counter did not move, but it is QUANTISED — a shop
                            displaying "25,100" steps in hundreds, so a zero delta
                            means the true change lay somewhere in [0, 100), not that
                            the shop sold nothing. Measured live: shopflowerlane held
                            25,100 across 4.7 days, which this method used to record
                            as sales_per_day 0.0 with basis `measured_delta` — a
                            confident claim that a 25,000-sale shop had stopped
                            selling. The rate is refused here and an upper BOUND is
                            stored instead, never a rate.
        """
        now = collected_at or datetime.now(timezone.utc).isoformat()
        previous = self.latest_shop_observation(shop_name)

        delta = window_days = per_day = per_day_upper = None
        basis = "baseline"
        resolution = self.counter_resolution(total_sales)
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

                if raw == 0 and resolution > 1:
                    # The counter cannot resolve this window. 0.0/day would be a
                    # confident claim that the shop sold nothing; what is actually
                    # known is only that it sold FEWER than one counter step.
                    basis = "below_resolution"
                    per_day_upper = (round((resolution - 1) / window_days, 6)
                                     if window_days > 0 else None)
                    per_day = None

        row = {
            "shop_name": shop_name, "collected_at": now,
            "total_sales": total_sales, "total_reviews": total_reviews,
            "sales_delta": delta, "window_days": window_days,
            "sales_per_day": per_day, "basis": basis,
            "sales_per_day_upper": per_day_upper,
            "counter_resolution": resolution,
        }
        with self.get_connection() as conn:
            # Same instant twice is the same observation, not two.
            conn.execute('''
                INSERT OR REPLACE INTO shop_observations (
                    shop_name, collected_at, total_sales, total_reviews,
                    sales_delta, window_days, sales_per_day, basis,
                    sales_per_day_upper, counter_resolution
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (shop_name, now, total_sales, total_reviews, delta, window_days,
                  per_day, basis, per_day_upper, resolution))
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

    def record_keyword_competition(self, keyword, total_results=None,
                                   organic_sample=None, ranked_ids_count=None,
                                   saturation=None, median_delivery=None,
                                   collected_at=None, source="etsy_public"):
        """Append one public-SERP competition reading. Never overwrites.

        `saturation` is card_saturation.profile() — stored as JSON so the interval
        and the can_discriminate flag reach the reader untouched. Nothing here is
        derived from keyword_observations; the two tables are joined only at read
        time, in the Cockpit, and never merged into one denominator.
        """
        now = collected_at or datetime.now(timezone.utc).isoformat()
        blob = json.dumps(saturation, default=str) if saturation is not None else None
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO keyword_competition (
                    keyword, collected_at, source, total_results, organic_sample,
                    ranked_ids_count, saturation_json, median_delivery
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (keyword, now, source, total_results, organic_sample,
                  ranked_ids_count, blob, median_delivery))
            conn.commit()
        return {"keyword": keyword, "collected_at": now}

    def record_discovered(self, term, seed=None, volume=None, supply=None,
                          demand_per_listing=None, cvr=None, verdict=None,
                          moment=None, list_by=None, timing=None, collected_at=None):
        """Append one discovered candidate. Never overwrites (append-only pool)."""
        now = collected_at or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO discovered_candidates (
                    term, collected_at, seed, volume, supply, demand_per_listing,
                    cvr, verdict, moment, list_by, timing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (term, now, seed, volume, supply, demand_per_listing, cvr,
                  verdict, moment, list_by, timing))
            conn.commit()
        return {"term": term, "collected_at": now}

    def latest_discovered(self, limit=200):
        """The most recent discovery run's candidates, best winnability first.

        A term can appear under multiple seeds; the highest demand_per_listing wins,
        and the losing rows are dropped so the pool reads as a ranked list, not a
        cross-join. Returns [] when nothing has been discovered yet.
        """
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            newest = conn.execute(
                "SELECT MAX(collected_at) FROM discovered_candidates").fetchone()[0]
            if not newest:
                return []
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM discovered_candidates WHERE collected_at = ? "
                "ORDER BY demand_per_listing DESC", (newest,))]
        best = {}
        for r in rows:
            prev = best.get(r["term"])
            if not prev or (r["demand_per_listing"] or -1) > (prev["demand_per_listing"] or -1):
                best[r["term"]] = r
        ranked = sorted(best.values(),
                        key=lambda r: (r["demand_per_listing"] is not None,
                                       r["demand_per_listing"] or -1), reverse=True)
        return ranked[:limit]

    def latest_keyword_competition(self, keyword):
        """The most recent competition reading for a term, or None. Parses the JSON."""
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                'SELECT * FROM keyword_competition WHERE keyword = ? '
                'ORDER BY collected_at DESC LIMIT 1', (keyword,)).fetchone()
        if not row:
            return None
        out = dict(row)
        out["saturation"] = (json.loads(out.pop("saturation_json"))
                             if out.get("saturation_json") else None)
        return out

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

    # -- competitor listings over time (D-25) ------------------------------------------

    def record_listing_observation(self, listing_id, shop_name=None, title=None,
                                   price=None, total_reviews=None, rating=None,
                                   is_ad=None, matched_term=None, collected_at=None):
        """Append one competitor-tracking reading of a listing. Never overwrites.

        Writes the same table as `record_listing` — deliberately. That one records the
        badge/sales side of a listing; this one records the outcome side. Two tables
        would give the system two answers to "how many reviews does this listing have".
        Both use `total_reviews` for exactly that reason.

        `first_seen_at` carries forward from the earliest row held, so observed age
        survives even though each row is independent. It is OUR first sighting, not the
        listing's creation date.

        `total_reviews=None` means the count did not parse, which is not zero reviews
        (N-02). Stored as 0 it would look like a brand-new listing and make the next
        velocity reading enormous.
        """
        collected_at = collected_at or datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            row = conn.execute(
                'SELECT first_seen_at, collected_at FROM listing_observations '
                'WHERE listing_id = ? ORDER BY collected_at ASC LIMIT 1',
                (str(listing_id),)).fetchone()
            if row:
                first_seen_at = row[0] or row[1]
                basis = "repeat_sighting"
            else:
                first_seen_at = collected_at
                basis = "first_sighting"

            # INSERT OR IGNORE, not REPLACE: re-reading the same listing at the same
            # timestamp must not overwrite a row another writer already placed there.
            conn.execute('''
                INSERT OR IGNORE INTO listing_observations (
                    listing_id, collected_at, shop_name, title, price, total_reviews,
                    rating, is_ad, first_seen_at, matched_term, sighting_basis
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ''', (str(listing_id), collected_at, shop_name, title, price, total_reviews,
                  rating, None if is_ad is None else int(bool(is_ad)),
                  first_seen_at, matched_term, basis))
            conn.commit()
        return {"listing_id": str(listing_id), "collected_at": collected_at,
                "first_seen_at": first_seen_at, "sighting_basis": basis}

    def get_listing_history(self, listing_id):
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                'SELECT * FROM listing_observations WHERE listing_id = ? '
                'ORDER BY collected_at ASC', (str(listing_id),)).fetchall()
            return [dict(r) for r in rows]

    def tracked_listings(self, shop_name=None):
        """Latest reading per listing. The shop's current inventory, as we last saw it."""
        sql = ('SELECT lo.* FROM listing_observations lo '
               'JOIN (SELECT listing_id, MAX(collected_at) AS mx '
               '      FROM listing_observations GROUP BY listing_id) latest '
               '  ON lo.listing_id = latest.listing_id AND lo.collected_at = latest.mx')
        args = []
        if shop_name:
            sql += ' WHERE lo.shop_name = ?'
            args.append(shop_name)
        with self.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, args).fetchall()]


def recompute_shop_rates(db_path=None, apply=False):
    """Recompute the DERIVED columns on shop_observations from the raw readings.

    Time is append-only here, so this deliberately does not touch an observation:
    `total_sales`, `total_reviews` and `collected_at` are what was seen and are left
    exactly as they were. `sales_delta`, `sales_per_day`, `basis`,
    `sales_per_day_upper` and `counter_resolution` are DERIVATIONS from those
    readings, and a derivation computed by a rule now known to be wrong should be
    recomputed, not preserved.

    The rule that changed: a quantised counter that did not move used to yield
    `sales_per_day = 0.0, basis = measured_delta`. It now yields a refusal plus an
    upper bound. Rows written before that are claims the system would no longer make.

    Dry run by default — call with apply=True to write.
    """
    db = MarketDatabase(db_path) if db_path else MarketDatabase()
    changes = []
    with db.get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM shop_observations ORDER BY shop_name, collected_at")]

        previous = {}
        for row in rows:
            shop, total = row["shop_name"], row["total_sales"]
            resolution = MarketDatabase.counter_resolution(total)
            prev = previous.get(shop)
            delta = window = per_day = upper = None
            basis = "baseline"

            if prev and prev["total_sales"] is not None and total is not None:
                raw = total - prev["total_sales"]
                if raw < 0:
                    basis = "counter_decreased"
                else:
                    gap = (datetime.fromisoformat(row["collected_at"])
                           - datetime.fromisoformat(prev["collected_at"]))
                    window = round(gap.total_seconds() / 86400.0, 6)
                    delta, basis = raw, "measured_delta"
                    per_day = round(raw / window, 6) if window > 0 else None
                    if raw == 0 and resolution > 1:
                        basis = "below_resolution"
                        upper = (round((resolution - 1) / window, 6)
                                 if window > 0 else None)
                        per_day = None

            if (row["basis"] != basis or row["sales_per_day"] != per_day
                    or row.get("counter_resolution") != resolution):
                changes.append({"shop": shop, "collected_at": row["collected_at"],
                                "was": {"basis": row["basis"],
                                        "sales_per_day": row["sales_per_day"]},
                                "now": {"basis": basis, "sales_per_day": per_day,
                                        "sales_per_day_upper": upper,
                                        "counter_resolution": resolution}})
            if apply:
                conn.execute("""
                    UPDATE shop_observations
                       SET sales_delta = ?, window_days = ?, sales_per_day = ?,
                           basis = ?, sales_per_day_upper = ?, counter_resolution = ?
                     WHERE shop_name = ? AND collected_at = ?
                """, (delta, window, per_day, basis, upper, resolution,
                      shop, row["collected_at"]))
            previous[shop] = row
        if apply:
            conn.commit()
    return {"rows": len(rows), "changed": len(changes), "applied": apply,
            "changes": changes}
