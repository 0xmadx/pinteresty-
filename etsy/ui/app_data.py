"""The read layer — every view's data as plain JSON, from the database only.

This is the single seam the whole app strategy turns on. Both consumers read
THROUGH here and nothing else:

    snapshot app   bakes build_snapshot() into one interactive HTML file (today)
    FastAPI server wraps each build_* function as an HTTP endpoint (later)

Because the presentation never reaches past these functions into the database, a
server can be added without touching the app, and the app without touching the
server. The MCP tools already proved the shape — clean JSON per question — this
consolidates it into one place the UI can lean on.

RULES IT KEEPS (the same ones the screens keep)
-----------------------------------------------
* No live calls. Everything is the daily snapshot; a value's age is carried, never
  hidden, so a month-old reading cannot masquerade as fresh.
* Every number keeps its basis. `measured` / `derived` / `bound` / `unmeasured` /
  `provisional` travel in the JSON so the client can style them differently — an
  estimate must never render like a fact.
* Demand and competition stay in separate objects. keyword_observations is
  market-wide private demand; keyword_competition is a page-one public sample. The
  client may show them side by side but the data never merges their denominators.
* Absent is not zero. A term never measured is `null` with a reason, not 0.
"""
import sqlite3
from datetime import datetime, timezone

DB_PATH = "market_intelligence.db"
WALL_RATIO = 0.20


def _conn(db_path):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    return c


def build_meta(db_path=DB_PATH, now=None):
    """Top-of-app state: freshness, the settings basis, and what is blocked."""
    from core.settings_store import load
    now = now or datetime.now(timezone.utc)
    settings = load()
    basis = settings.basis()
    blockers = []
    if basis["basis"] != "operator":
        blockers.append({"kind": "settings",
                         "text": f"Fee/cost inputs are defaults: {', '.join(basis['unconfirmed'])}"})
    shops = settings.shop_names()
    if shops and len(shops) < 3:
        blockers.append({"kind": "shops",
                         "text": f"Only {len(shops)} shop(s) tracked — all winners (B-01)"})
    try:
        from core.graph_db import GraphDB
        launches = GraphDB().launch_count()
    except Exception:
        launches = None
    if launches == 0:
        blockers.append({"kind": "launches",
                         "text": "0 launches — LEARN cannot start until 10 exist"})

    return {
        "generated_at": now.isoformat(),
        "settings_basis": basis["basis"],
        "verdicts_provisional": basis["basis"] != "operator",
        "watched_terms": settings.terms(),
        "tracked_shops": shops,
        "launches": launches,
        "blockers": blockers,
    }


def build_keywords(db_path=DB_PATH):
    """Etsy demand intelligence: every watched term's latest reading + history.

    History is the sparkline series for the tracking view; latest carries the
    demand-per-listing ratio and the wall flag. Nothing derived from competition —
    that is a separate object.
    """
    with _conn(db_path) as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM keyword_observations ORDER BY keyword, collected_at ASC")]
    by_term = {}
    for r in rows:
        by_term.setdefault(r["keyword"], []).append(r)

    out = []
    for term, history in by_term.items():
        latest = history[-1]
        vol, sup = latest.get("search_volume"), latest.get("competition")
        ratio = (vol / sup) if (vol and sup) else None
        out.append({
            "term": term,
            "volume": vol, "supply": sup,
            "cvr": latest.get("query_cvr"),
            "cvr_basis": latest.get("cvr_source"),
            "price_low": latest.get("median_price_low"),
            "price_high": latest.get("median_price_high"),
            "demand_per_listing": round(ratio, 4) if ratio else None,
            "is_wall": (ratio is not None and ratio < WALL_RATIO),
            "readings": len(history),
            "measured_at": latest["collected_at"],
            "series": [{"at": h["collected_at"], "volume": h.get("search_volume"),
                        "supply": h.get("competition")} for h in history],
            "basis": "measured",
        })
    out.sort(key=lambda k: (k["demand_per_listing"] is not None,
                            k["demand_per_listing"] or -1), reverse=True)
    return out


def build_competition(db_path=DB_PATH):
    """Etsy competition intelligence: page-one saturation + delivery, per term.

    A SAMPLE with intervals, kept apart from market-wide demand. Only decisive
    saturation dimensions are surfaced; the délai is the median delivery band.
    """
    from core.database import MarketDatabase
    from core.settings_store import load
    db = MarketDatabase(db_path)
    out = []
    for term in load().terms():
        row = db.latest_keyword_competition(term)
        if not row:
            continue
        sat = row.get("saturation") or {}
        decisive = []
        for label, m in sat.items():
            dim, _, val = label.partition("|")
            if m.get("can_discriminate"):
                decisive.append({"dimension": dim, "value": val, "share": m.get("share"),
                                 "low": m.get("low"), "high": m.get("high")})
        out.append({
            "term": term, "measured_at": row.get("collected_at"),
            "organic_sample": row.get("organic_sample"),
            "ranked_ids": row.get("ranked_ids_count"),
            "decisive": decisive,
            "median_delivery": row.get("median_delivery"),
            "delivery_bands": row.get("delivery_bands") or [],
            "basis": "measured (page-one sample)",
        })
    return out


def build_discovered(db_path=DB_PATH, limit=2000):
    """The candidate pool: terms the operator never typed, ranked by winnability."""
    from core.database import MarketDatabase
    pool = MarketDatabase(db_path).latest_discovered(limit)
    return [{
        "term": r["term"], "seed": r.get("seed"),
        "volume": r.get("volume"), "supply": r.get("supply"),
        "demand_per_listing": r.get("demand_per_listing"),
        "verdict": r.get("verdict"),
        # The measured CVR behind a weak_intent verdict, so the reader can check it
        # rather than take the label on trust (D-43).
        "cvr": r.get("cvr"),
        # Pinterest's axis. NULL for any term Pinterest does not track, which is most
        # of them — the client must render that as unknown, never as flat (N-02).
        "momentum": r.get("momentum"),
        "momentum_mom": r.get("momentum_mom"),
        "moment": r.get("moment"), "list_by": r.get("list_by"),
        "timing": r.get("timing"),
    } for r in pool]


def build_pinterest(db_path=DB_PATH):
    """Pinterest intelligence: dated moments and trending topics.

    The underused half. Moments carry takeoff/peak/phase (the timing engine);
    topics carry colour and velocity (what is rising, and how it looks).
    """
    with _conn(db_path) as c:
        latest = c.execute(
            "SELECT MAX(collected_at) FROM trend_observations").fetchone()[0]
        if not latest:
            return {"moments": [], "topics": [], "as_of": None}
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM trend_observations WHERE collected_at = ?", (latest,))]
    moments, topics = [], []
    for r in rows:
        if r["source"] == "pinterest_moments":
            moments.append({"name": r["trend_name"], "takeoff": r["takeoff_timestamp"],
                            "peak": r.get("peak_date"), "phase": r.get("phase"),
                            "list_by": r.get("list_by")})
        else:
            topics.append({"name": r["trend_name"], "color": r.get("dominant_color"),
                           "color_share": r.get("color_share"),
                           "velocity": r.get("velocity"),
                           "growth_mom": r.get("growth_mom")})
    topics.sort(key=lambda t: (t["velocity"] is not None, t["velocity"] or -1),
                reverse=True)
    moments.sort(key=lambda m: m.get("list_by") or "9999")
    return {"as_of": latest, "moments": moments, "topics": topics}


def build_calendar(db_path=DB_PATH, lead_weeks=6, now=None):
    """The combination: Pinterest timing joined to Etsy demand."""
    from etsy.engines import calendar_engine
    rows = calendar_engine.build(db_path=db_path, lead_weeks=lead_weeks, now=now)
    return [{
        "moment": r["moment"], "state": r["state"], "list_by": r["list_by"],
        "peak": r.get("peak"), "is_late": r.get("is_late"), "reason": r["reason"],
        "actionable": r["actionable"],
        "terms": [{"term": e["term"], "basis": e.get("basis"),
                   "demand_per_listing": e.get("demand_per_listing"),
                   "is_wall": e.get("is_wall")} for e in r.get("evidence", [])],
    } for r in rows]


def build_shops(db_path=DB_PATH):
    """Competitor tracking: shops and their listings matching a watched term."""
    from etsy.ui import market_page
    data = market_page.gather(db_path)
    out = []
    for d in data:
        out.append({
            "shop": d["shop"],
            "lifetime_sales": (d["latest"] or {}).get("total_sales"),
            "reviews": (d["latest"] or {}).get("total_reviews"),
            "sales_per_day_bound": d["rate_bound"],
            "listings": [{
                "title": m.get("title"), "matched_term": m.get("matched_term"),
                "reviews": (m.get("velocity") or {}).get("total_reviews")
                           or m.get("total_reviews"),
                "review_velocity": (m.get("velocity") or {}).get("velocity"),
                "velocity_basis": (m.get("velocity") or {}).get("basis"),
            } for m in d["matched"]],
        })
    return out


def build_snapshot(db_path=DB_PATH, now=None):
    """The whole app's data in one object. What the snapshot app bakes in."""
    return {
        "meta": build_meta(db_path, now),
        "keywords": build_keywords(db_path),
        "competition": build_competition(db_path),
        "discovered": build_discovered(db_path),
        "pinterest": build_pinterest(db_path),
        "calendar": build_calendar(db_path, now=now),
        "shops": build_shops(db_path),
    }
