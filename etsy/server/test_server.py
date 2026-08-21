"""The read server: every read endpoint is DB-only, and the live path refuses safely.

The server's whole justification is that it adds live + network access WITHOUT a
second copy of any query — so the tests check that the read endpoints wrap the read
layer faithfully (a temp DB, no network), that filters apply, and that the one live
path gates on the vault rather than hanging when it is empty. The live analysis
itself is not exercised here (it spends real requests); its guard is.

    .venv/Scripts/python.exe -m etsy.server.test_server
"""
import os
import tempfile

from fastapi.testclient import TestClient

from core.database import MarketDatabase

PASS = FAIL = 0


def check(label, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}  {detail}")


def seed(path):
    db = MarketDatabase(db_path=path)
    db.record_keyword("mom necklace", volume=12000, competition=350000, cvr=0.0003,
                      cvr_source="measured", price_low=17, price_high=21,
                      collected_at="2026-08-19T00:00:00+00:00")
    db.record_discovered("winner", seed="mom necklace", volume=9000, supply=4000,
                         demand_per_listing=2.25, verdict="winnable",
                         timing="evergreen", collected_at="2026-08-20T00:00:00+00:00")
    db.record_discovered("a wall", seed="mom necklace", demand_per_listing=0.02,
                         verdict="wall", timing="seasonal",
                         collected_at="2026-08-20T00:00:00+00:00")
    db.record_trend(trend_name="christmas", source="pinterest_moments", country="US",
                    takeoff_timestamp="2026-10-28", list_by="2026-09-16",
                    peak_date="2026-12-09", phase="approaching", takeoff_basis="measured")
    return db


def client(path):
    # DB_PATH is read at import, so set the env before importing the app module.
    os.environ["MARKET_DB"] = path
    import importlib
    from etsy.server import app as appmod
    importlib.reload(appmod)
    return TestClient(appmod.app)


def main():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "s.db")
    seed(path)
    c = client(path)

    # --- the frontend serves live ------------------------------------------------------
    print()
    r = c.get("/")
    check("GET / returns the interactive app", r.status_code == 200)
    check("and it is the app, rendered from THIS database",
          "v-discover" in r.text and "winner" in r.text)

    # --- read endpoints wrap the read layer, DB only -----------------------------------
    print()
    for ep, shape in [("/api/meta", dict), ("/api/keywords", list),
                      ("/api/competition", list), ("/api/discovered", list),
                      ("/api/pinterest", dict), ("/api/calendar", list),
                      ("/api/shops", list)]:
        r = c.get(ep)
        check(f"{ep} is 200 and the right shape",
              r.status_code == 200 and isinstance(r.json(), shape), r.status_code)

    check("keywords carries the demand reading from the DB",
          c.get("/api/keywords").json()[0]["term"] == "mom necklace")
    check("pinterest exposes moments and topics separately",
          set(c.get("/api/pinterest").json()) >= {"moments", "topics"})

    # --- the discovered filters apply server-side --------------------------------------
    print()
    allp = c.get("/api/discovered").json()
    check("unfiltered returns the whole pool", len(allp) == 2, len(allp))
    win = c.get("/api/discovered?verdict=winnable").json()
    check("?verdict=winnable filters to the winnable term",
          [d["term"] for d in win] == ["winner"], win)
    seasonal = c.get("/api/discovered?timing=seasonal").json()
    check("?timing=seasonal filters by season",
          [d["term"] for d in seasonal] == ["a wall"], seasonal)

    # --- cockpit is a DB-only read -----------------------------------------------------
    print()
    r = c.get("/api/cockpit/mom necklace")
    check("cockpit returns a three-source state", r.status_code == 200
          and "state" in r.json() and "combined" in r.json()["state"])

    # --- the live path REFUSES cleanly on an empty vault, never hangs ------------------
    print()
    import core.vault_status as vs
    real_scan = vs.scan
    vs.scan = lambda *a, **k: {"etsy": {"usable": []}, "etsy_private": {"usable": []}}
    try:
        r = c.post("/api/analyze/some new term")
        check("an empty vault yields 503, not a hang or a 500",
              r.status_code == 503, r.status_code)
        check("with a message pointing at the fix",
              "open Chrome" in r.json().get("detail", ""), r.json())
    finally:
        vs.scan = real_scan

    # --- an unknown route is a clean 404 -----------------------------------------------
    print()
    check("an unknown API route is 404, not a crash",
          c.get("/api/nonsense").status_code == 404)

    # --- health --------------------------------------------------------------------------
    print()
    r = c.get("/api/health")
    check("health is 200 and reports the db + vault",
          r.status_code == 200 and r.json()["ok"] and "vault_usable" in r.json())

    print(f"\n{PASS} passed, {FAIL} failed")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
