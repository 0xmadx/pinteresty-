"""The read server — the same read layer, now over HTTP.

    .venv/Scripts/python.exe -m etsy.server.app          # http://127.0.0.1:8100

WHAT THIS ADDS OVER THE SNAPSHOT APP, AND WHAT IT DOES NOT
---------------------------------------------------------
The static app (`etsy/data/ui/app.html`) already gives tables, filters, charts and
the combined views, baked from the daily snapshot. This server adds exactly the two
things a file cannot:

  1. LIVE FROM THE DATABASE on every request — no waiting for the daily rebuild,
     and reachable from another device on the network (phone included).
  2. ON-DEMAND LIVE ANALYSIS — `POST /api/analyze/{term}` runs the real pipeline
     for a term the operator types and did not have watched, then returns it.

It does NOT replace the batch scheduler or the static files. Those remain the
default and need no daemon; this is an OPTIONAL local tool you start when you want
live or mobile. Run it behind `127.0.0.1` unless you deliberately want it on the
LAN — it exposes the operator's private market data with no auth.

THE ARCHITECTURE PAYOFF (D-41)
------------------------------
Every read endpoint is a one-line wrapper over `app_data`, the same functions the
snapshot app bakes in. The server did not need a second copy of any query — it is
the second thin consumer the read layer was built for. The frontend is the SAME
`app_page` renderer, fed a fresh snapshot per request, so there is no React rewrite
and no divergence between the file and the server.

THE ONE PATH THAT TOUCHES THE NETWORK
-------------------------------------
Only `/api/analyze` makes live calls, and it is honest about the cost: it gates on
the session vault (an empty pool would hang, so it refuses fast), it is a
deliberate POST rather than something a page load triggers, and it says plainly
that it spends real requests. Every other endpoint reads the database only.
"""
import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from etsy.ui import app_data, app_page

app = FastAPI(title="Etsy intelligence", docs_url="/api/docs")

DB_PATH = os.environ.get("MARKET_DB", "market_intelligence.db")


# --- the frontend: the snapshot app, but live from the DB each load -----------------

@app.get("/", response_class=HTMLResponse)
def home():
    """The interactive app, rendered fresh from the database on every request."""
    return app_page.render_html(app_data.build_snapshot(DB_PATH))


# --- read endpoints: one thin wrapper each, over the read layer ---------------------

@app.get("/api/snapshot")
def snapshot():
    """The whole dataset — what the frontend consumes, exposed for any client."""
    return app_data.build_snapshot(DB_PATH)


@app.get("/api/meta")
def meta():
    return app_data.build_meta(DB_PATH)


@app.get("/api/keywords")
def keywords():
    return app_data.build_keywords(DB_PATH)


@app.get("/api/competition")
def competition():
    return app_data.build_competition(DB_PATH)


@app.get("/api/discovered")
def discovered(verdict: str = None, timing: str = None, limit: int = 2000):
    """The candidate pool, with the same filters the app offers — server-side here."""
    pool = app_data.build_discovered(DB_PATH, limit)
    if verdict:
        pool = [d for d in pool if d.get("verdict") == verdict]
    if timing:
        pool = [d for d in pool if d.get("timing") == timing]
    return pool


@app.get("/api/pinterest")
def pinterest():
    return app_data.build_pinterest(DB_PATH)


@app.get("/api/calendar")
def calendar(lead_weeks: int = 6):
    return app_data.build_calendar(DB_PATH, lead_weeks=lead_weeks)


@app.get("/api/shops")
def shops():
    return app_data.build_shops(DB_PATH)


@app.get("/api/cockpit/{term}")
def cockpit(term: str, product_type: str = "personalized", lead_weeks: int = 6):
    """One candidate's full three-source verdict — from the database, no live calls."""
    from etsy.engines import cockpit as ck
    state = ck.build(term, db_path=DB_PATH, product_type=product_type,
                     lead_weeks=lead_weeks)
    return {"state": state, "findings": ck.read(state)}


# --- the one live path --------------------------------------------------------------

@app.post("/api/analyze/{term}")
def analyze(term: str, product_type: str = "personalized"):
    """Run the real pipeline for a term the operator just typed. LIVE — spends requests.

    This is the capability the snapshot cannot have: a keyword you did not have
    watched, measured now. It gates on the session vault so an empty pool refuses
    fast instead of hanging, stores what it measures (so it joins the daily data),
    and returns the fresh cockpit.
    """
    from core import vault_status as vs
    # A stale db-1 mirror reads as an empty vault (D-33); sync before judging, or a
    # live analyze would refuse while Chrome is beaming fine cookies into db 0.
    try:
        from core.vault_mirror import sync
        sync()
    except Exception:
        pass
    try:
        report = vs.scan(("etsy", "etsy_private"))
    except Exception as e:
        raise HTTPException(503, f"session vault unreachable: {e}")
    missing = [p for p in ("etsy", "etsy_private") if not report.get(p, {}).get("usable")]
    if missing:
        raise HTTPException(
            503, f"no usable session for {', '.join(missing)} — open Chrome with the "
                 f"extension so it refreshes cookies, then retry")

    from core.database import MarketDatabase
    from core.settings_store import load
    from etsy.analytics import card_saturation, sourcing
    from etsy.api.private.api import EtsyPrivateAPI, parse_results_data
    from etsy.api.public.api import EtsyPublicAPI

    db = MarketDatabase(DB_PATH)
    priv, pub = EtsyPrivateAPI(), EtsyPublicAPI()

    # Private demand.
    d = parse_results_data(priv.get_results_data(term)) or {}
    if not d.get("volume"):
        raise HTTPException(502, "the private API returned no volume for this term")
    db.record_keyword(term, source="etsy_private", volume=d.get("volume"),
                      competition=d.get("supply"), cvr=d.get("cvr"),
                      cvr_source="measured" if d.get("cvr") is not None else "default",
                      price_low=d.get("price_low"), price_high=d.get("price_high"))

    # Public competition + délai.
    serp = pub.get_public_search(term) or {}
    prof = card_saturation.profile(serp.get("cards"))
    organic = [c for c in (serp.get("cards") or []) if not c.get("is_ad")]
    dprofile = sourcing.fetch_profile(pub, term, countries=())
    db.record_keyword_competition(
        term, total_results=serp.get("total_results"), organic_sample=len(organic),
        ranked_ids_count=len(serp.get("organic_listing_ids") or []),
        saturation={f"{dim}|{v}": m for (dim, v), m in prof.items()},
        delivery_bands=[{"band": b, "share": sh}
                        for b, sh in sourcing.delivery_distribution(dprofile)],
        median_delivery=sourcing.median_band(dprofile))

    # The term is now measured; hand back the same cockpit the read path would.
    from etsy.engines import cockpit as ck
    state = ck.build(term, db_path=DB_PATH, product_type=product_type)
    return {"analyzed": term, "state": state, "findings": ck.read(state),
            "note": "measured live and stored; it now appears in the daily data too"}


@app.get("/api/health")
def health():
    """Is the server up, and can it reach live sessions if asked?"""
    from core import vault_status as vs
    try:
        from core.vault_mirror import sync
        sync()
    except Exception:
        pass
    try:
        report = vs.scan()
        vault = {p: len(r["usable"]) for p, r in report.items()}
    except Exception as e:
        vault = {"error": str(e)}
    return JSONResponse({"ok": True, "db": DB_PATH, "vault_usable": vault})


def main():
    import uvicorn
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8100"))
    print(f"Etsy intelligence server → http://{host}:{port}")
    print("  the interactive app is at /, the API at /api/docs")
    print("  this is an OPTIONAL local tool; the batch scheduler needs no server.")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
