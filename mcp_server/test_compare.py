"""Offline tests for `compare` — the batch door. No network, no session.

The gap this closed: every decision tool on the surface was singular, while a
complete tested pool ranker (`scoring.score_pool` / `explain`) sat behind them with
only two CLI callers. The agent could reach `can_discriminate` — the guard that
REFUSES a ranking — without reaching the ranking it guards. So the surface could say
"these cannot be compared" and never "here is the comparison".

What these pin, in order of how expensive the mistake would be:

  1. Over the cap it REFUSES. A silent trim would leave the operator comparing a
     list they only partly measured, while the output looked complete.
  2. The headline verdict is the WORSE of the gates, never an average — averaging
     lets a huge market hide a closed door (D-31 + D-43).
  3. Sorting is by demand-per-listing, never volume, and an unmeasured term sorts
     LAST because it cannot be compared, not because it is worst (N-02).
  4. `ranked` is null when the dimensions cannot separate the pool. That is a real
     answer (N-01), not a failure, and it must not be papered over with a number.
  5. Both floors are reported even when they bite: cheap mode cannot judge intent
     at all, and under MIN_POOL_FOR_INTENT there is no reference to judge against.

Run:  python -m mcp_server.test_compare
"""
import sys

import mcp_server.tools_decide as td

PASS = FAIL = 0


def check(label, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label} {detail}")


def td_min_intent():
    from etsy.analytics.discover import MIN_POOL_FOR_INTENT
    return MIN_POOL_FOR_INTENT


def _row(rows, term):
    return next(r for r in rows if r["term"] == term)


def main():
    global PASS, FAIL

    # Stub the two fetchers and the preflight. The point of this suite is the
    # judgement layer — the fetchers are thin wrappers over parsers already covered
    # by test_parsers, and stubbing them keeps the seller account out of the loop.
    real = (td._compare_cheap, td._compare_full, td._preflight)
    td._preflight = lambda *a, **k: None

    # --- refusals come first: they are the guards, not the edge cases --------------
    print("\nrefusals")
    td._compare_cheap = lambda terms: ({}, None, 0)
    td._compare_full = lambda terms: ({}, None, 0)

    r = td.compare(terms="one term only")
    check("a single term is refused — that is a lookup, not a comparison",
          r.get("ok") is False, r)
    check("and it names the right tool", "cockpit" in str(r))
    check("an empty list is refused", td.compare(terms="").get("ok") is False)
    check("a bad mode is refused", td.compare(terms="a,b", mode="turbo").get("ok") is False)

    over = td.compare(terms=",".join(f"t{i}" for i in range(td.MAX_COMPARE_FULL + 1)),
                      mode="full")
    check("over the full-mode cap it REFUSES rather than trimming",
          over.get("ok") is False, over)
    check("the refusal explains WHY the cap exists (the seller account)",
          "SELLER" in str(over))
    check("and offers the cheaper mode as the way through",
          "mode=cheap" in str(over))
    check("cheap mode has a HIGHER cap, because it costs ceil(N/3) not N",
          td.MAX_COMPARE_CHEAP > td.MAX_COMPARE_FULL)
    check("a list at exactly the cap is allowed — the boundary is inclusive",
          td.compare(terms=",".join(f"t{i}" for i in range(td.MAX_COMPARE_FULL)),
                     mode="full").get("ok") is True)

    # --- the table: sorting, the worse-of rule, and absent-is-not-zero -------------
    print("\nthe table")
    # `wall` is D-31's real example: enormous traffic, unrankable. `winnable` is the
    # term that sits 17th by volume and first by ratio.
    FULL = {
        "home decor":        {"volume": 310467, "supply": 2160627, "cvr": 0.00005},
        "backpack name tag": {"volume": 69874,  "supply": 25031,   "cvr": 0.00279},
        "felt garland":      {"volume": 9000,   "supply": 12000,   "cvr": 0.0021},
        "birthday crown":    {"volume": 4000,   "supply": 3000,    "cvr": 0.0024},
        "mom necklace":      {"volume": 16000,  "supply": 9000,    "cvr": 0.0026},
        "linen apron":       {"volume": 3500,   "supply": 2000,    "cvr": 0.0022},
        "custom polo shirt": {"volume": 1200,   "supply": 900,     "cvr": 0.0025},
        "felt flower":       {"volume": 600,    "supply": 400,     "cvr": 0.0023},
        # measured as a term, but Etsy never sized it: absent, not zero.
        "ghost term":        {"volume": None,   "supply": None,    "cvr": None},
    }
    td._compare_full = lambda terms: ({t: dict(FULL[t]) for t in terms}, None, len(terms))
    res = td.compare(terms=",".join(FULL), mode="full")
    rows = res["rows"]

    check("every requested term appears in the table", len(rows) == len(FULL), len(rows))
    check("sorted by demand-per-listing, NOT volume — home decor has 4.4x the "
          "traffic of backpack name tag and ranks below it",
          [r["term"] for r in rows][0] == "backpack name tag", rows[0]["term"])
    check("the biggest market in the pool is called a wall",
          _row(rows, "home decor")["verdict"] == "wall",
          _row(rows, "home decor"))
    check("and the ratio is shown, so 'you cannot rank here' is checkable",
          _row(rows, "home decor")["demand_per_listing"] == 0.144)

    ghost = _row(rows, "ghost term")
    check("an unsized term is unmeasured, never 0", ghost["verdict"] == "unmeasured")
    check("its ratio is None rather than 0.0", ghost["demand_per_listing"] is None)
    check("and it sorts LAST — uncomparable, not worst",
          rows[-1]["term"] == "ghost term", rows[-1]["term"])

    # --- the worse-of rule ---------------------------------------------------------
    print("\nthe headline is the WORSE of the gates")
    # A term that clears winnability easily and converts at a fraction of its peers.
    # Averaging the two gates would call this fine; it is not.
    WEAK = dict(FULL)
    WEAK["trap term"] = {"volume": 50000, "supply": 5000, "cvr": 0.00001}
    td._compare_full = lambda terms: ({t: dict(WEAK[t]) for t in terms}, None, len(terms))
    res2 = td.compare(terms=",".join(WEAK), mode="full")
    trap = _row(res2["rows"], "trap term")
    check("a term with a 10:1 demand ratio still passes winnability",
          trap["winnability"] == "winnable", trap["winnability"])
    check("but weak intent overrides it in the headline verdict",
          trap["verdict"] == "searched_not_bought", trap)
    check("the two gates stay separately readable, not merged into one score",
          trap["demand_per_listing"] is not None and trap["cvr_vs_pool"] is not None)

    # --- the intent floor ----------------------------------------------------------
    print("\nfloors are reported, not worked around")
    check("with 9 CVRs the intent gate has a reference and uses it",
          res["floors"]["cvr_reference_median"] is not None, res["floors"])

    SMALL = {k: FULL[k] for k in list(FULL)[:4]}
    td._compare_full = lambda terms: ({t: dict(SMALL[t]) for t in terms}, None, len(terms))
    small = td.compare(terms=",".join(SMALL), mode="full")
    check("under MIN_POOL_FOR_INTENT the gate REFUSES rather than comparing to noise",
          small["floors"]["cvr_reference_median"] is None, small["floors"])
    check("and says so in words the operator will read",
          "refuses" in small["floors"]["intent_state"], small["floors"]["intent_state"])
    check("every term's intent then reads unmeasured, not weak",
          all(r["intent"] == "unmeasured" for r in small["rows"]
              if r["basis"] == "measured"))

    # --- cheap mode: honest about what it cannot do --------------------------------
    print("\ncheap mode")
    CHEAP = {t: {"volume": v["volume"], "supply": v["supply"], "cvr": None,
                 "seasonality": {"verdict": "seasonal", "basis": "measured",
                                 "peak_label": "Nov 2025"}}
             for t, v in FULL.items()}
    td._compare_cheap = lambda terms: ({t: dict(CHEAP[t]) for t in terms},
                                       {"requested": terms, "returned": terms,
                                        "omitted": [], "basis": "measured"},
                                       -(-len(terms) // 3))
    ch = td.compare(terms=",".join(CHEAP), mode="cheap")
    check("intent is 'not_checked', never 'weak' — the endpoint has no CVR",
          all(r["intent"] == "not_checked" for r in ch["rows"]))
    check("and the floor explains that, and points at mode=full",
          "mode=full" in ch["floors"]["intent_state"], ch["floors"]["intent_state"])
    check("the seasonal curve rides along free (D-45)",
          _row(ch["rows"], "mom necklace")["seasonality"]["peak_label"] == "Nov 2025")
    check("chart-series coverage is carried through, so a missing term is readable",
          ch["coverage"]["omitted"] == [], ch["coverage"])
    check("9 terms cost 3 requests, not 9", ch["spent"]["private_requests_upper_bound"] == 3,
          ch["spent"])
    check("and the spend is labelled a BOUND — the cache can make it 0",
          "bound" in ch["spent"]["basis"])

    # --- N-01: refusing to rank is a real answer -----------------------------------
    print("\nrankability")
    check("a separable pool IS ranked, with a per-dimension explanation",
          res["ranked"] and "explain" in res["ranked"][0], (res["rankable"]))
    check("the explanation names the dimensions, not just a score",
          "demand" in res["ranked"][0]["explain"])

    # Two terms measured is below MIN_POOL_SIZE: a percentile over n=2 is only ever
    # 0.0 or 1.0, which looks like a ranking and carries nothing.
    TINY = {"a": {"volume": 100, "supply": 50, "cvr": None},
            "b": {"volume": 200, "supply": 400, "cvr": None}}
    td._compare_full = lambda terms: ({t: dict(TINY[t]) for t in terms}, None, len(terms))
    tiny = td.compare(terms="a,b", mode="full")
    check("below MIN_POOL_SIZE nothing is ranked", tiny["ranked"] is None, tiny["ranked"])
    check("and the refusal explains why a percentile would carry no information",
          "no information" in tiny["rankable"]["reason"], tiny["rankable"])
    check("but the table is still returned — refusing to RANK is not refusing to SHOW",
          len(tiny["rows"]) == 2)

    # --- THE UNIT BUG: a year of demand over a right-now supply --------------------
    #
    # Caught live before it shipped, and it flipped EVERY verdict in an 8-term batch.
    # chart-series at days=365 reports search_volume as a YEAR of searches while
    # avg_total_listings is a point-in-time count. `custom guitar strap` read
    # 42,735/13,010 = 3.285 "winnable"; results-data says 2,089/13,400 = 0.156 "wall".
    #
    # winnability's thresholds (D-31) are calibrated on the ~30-day volume, so the
    # two modes MUST feed it the same unit or the labels are meaningless.
    print(chr(10) + "cheap mode feeds a MONTHLY volume, not an annual one")
    CURVE = {"points": [{"label": f"M{i}", "value": 1000 + i} for i in range(12)],
             "last_is_partial": True}
    v, basis = td._monthly_volume(CURVE)
    check("the PARTIAL final bucket is skipped — using it fakes a collapse (D-45)",
          v == 1010, v)
    check("and the basis names which month the number came from",
          "M10" in basis, basis)
    check("a curve flagged complete uses its final point",
          td._monthly_volume({**CURVE, "last_is_partial": False})[0] == 1011)
    # Falling back to the annual figure is what produced the 20x error. Unmeasured
    # is honest; inflated is not (N-02).
    check("no complete month yields None, NEVER a fallback to the annual total",
          td._monthly_volume({"points": [{"label": "M0", "value": 9}],
                              "last_is_partial": True}) == (None, ) + (
              td._monthly_volume({"points": [], "last_is_partial": True})[1], ))
    check("an absent curve is unmeasured, not zero",
          td._monthly_volume(None)[0] is None)
    check("and every row states the unit it was judged on",
          all(r.get("volume_basis") for r in ch["rows"]), ch["rows"][0])

    # --- a CVR of 0 is NOT a measured rate ------------------------------------------
    #
    # Measured live 2026-09-01: `back70 sneakers` returns query_cvr EXACTLY 0 against
    # 10,597 monthly searches (so does `back70 shoes`). A true zero on that traffic is
    # not credible — it is a reporting floor or a withheld value, and from outside we
    # cannot tell it from a real zero.
    #
    # Left alone, 0 passed confirm_intent's `is None` check, then 0/median = 0.0 fell
    # under WEAK_INTENT_RATIO and the term was branded `weak` — REJECTED by the gate
    # on a number nobody measured. N-02, at the point where it costs a niche.
    print(chr(10) + "a zero CVR is a floor, not a rate")
    ZED = dict(FULL)
    ZED["floored term"] = {"volume": 10597, "supply": 4555, "cvr": 0}
    td._compare_full = lambda terms: ({t: dict(ZED[t]) for t in terms}, None, len(terms))
    z = td.compare(terms=",".join(ZED), mode="full")
    zrow = _row(z["rows"], "floored term")
    check("a zero CVR reads unmeasured, NOT weak — it must not reject the term",
          zrow["intent"] == "unmeasured", zrow)
    check("and it keeps its winnability verdict rather than being downgraded",
          zrow["verdict"] == zrow["winnability"], zrow)
    check("no ratio is invented from it", zrow["cvr_vs_pool"] is None)
    check("the detail says floor/withheld, not 'these searchers do not buy'",
          "floor" in (zrow["intent_detail"] or ""), zrow["intent_detail"])

    # The payload used to contradict itself: terms_with_cvr counted non-None while
    # reference_median counted truthy, so it reported 8 CVRs beside a null median.
    check("zeros are counted separately from usable CVRs",
          z["floors"]["terms_with_cvr_zero"] == 1
          and z["floors"]["terms_with_usable_cvr"] == len(FULL) - 1, z["floors"])
    check("and the two halves of the gate now agree on what counts",
          (z["floors"]["cvr_reference_median"] is not None)
          == (z["floors"]["terms_with_usable_cvr"] >= td_min_intent()), z["floors"])

    td._compare_cheap, td._compare_full, td._preflight = real
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
