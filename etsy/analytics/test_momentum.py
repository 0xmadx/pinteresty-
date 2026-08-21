"""JOIN 2 — momentum reports, never overrides, and absence is never decline.

The two failures this suite exists to prevent are both real events in this repo. A
term Pinterest does not track must not read as fading — that is N-02, and the version
of this join that matched stored featured topics returned nothing at all for exactly
that reason. And Pinterest's "10,000%+" display cap is a sentinel, not a measurement;
reading 100.01 as a real value would make every capped term the best in the pool.

    .venv/Scripts/python.exe -m etsy.analytics.test_momentum
"""
from etsy.analytics.momentum import (RISING_MOM, attach, classify, conflicts,
                                     render, series_index)

passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"  FAIL: {label} {detail}")


# --- the real values, measured live 2026-08-20 -------------------------------------
# Asked Pinterest for 7 candidates; it returned 3. These are those three, verbatim.
LIVE = {
    "ceramic vase": {"yoy_change": None, "mom_change": 0.03, "wow_change": 0.06},
    "christmas eve box": {"yoy_change": None, "mom_change": 0.7, "wow_change": 0.3},
    "macrame plant hanger": {"yoy_change": None, "mom_change": -0.07, "wow_change": -0.01},
}

rising = classify(LIVE["christmas eve box"])
check("a term ramping into its season reads as rising",
      rising["verdict"] == "rising", rising)
check("and the reason quotes the real figure, as a percentage",
      "70%" in rising["reason"], rising["reason"])
# +70% MoM for "christmas eve box" measured in AUGUST is the Christmas ramp starting.

flat = classify(LIVE["ceramic vase"])
check("a 3% drift is flat, not a trend", flat["verdict"] == "flat", flat)

# -7% MoM sits INSIDE the flat band, and that is the intended answer. A single
# month can drift 7% on noise alone, and calling that a decline would hand the
# operator a warning the data does not support. The threshold is not tuned to make
# any particular term come out a particular way.
drifting = classify(LIVE["macrame plant hanger"])
check("a 7% monthly dip is still flat — under the threshold, it is noise",
      drifting["verdict"] == "flat", drifting)
check("and the figure is shown signed, so the reader sees the direction anyway",
      "-7%" in drifting["reason"], drifting["reason"])

fading = classify({"mom_change": -0.34, "wow_change": -0.1})
check("a real decline reads as fading", fading["verdict"] == "fading", fading)
check("and the reason says DOWN, unambiguously", "DOWN" in fading["reason"], fading)
check("with the magnitude, unsigned, after the word DOWN",
      "34%" in fading["reason"], fading["reason"])
check("a value exactly at the fading threshold counts as fading",
      classify({"mom_change": -0.10})["verdict"] == "fading")

# --- absence is NOT decline (N-02) -------------------------------------------------
absent = classify(None)
check("a term Pinterest does not track is unmeasured",
      absent["verdict"] == "unmeasured", absent)
check("and its basis names why", absent["basis"] == "absent_from_pinterest", absent)
check("and it explicitly denies being evidence of decline",
      "not evidence of decline" in absent["reason"], absent)
check("carrying no momentum figure at all", absent["mom"] is None, absent)
# Pinterest returned 3 of 7 real candidates. Treating the other 4 as fading would
# reject them for being absent from an instrument, not for anything true about them.

check("an empty growth dict is also unmeasured, not flat",
      classify({})["verdict"] == "unmeasured")

# --- the 10,000%+ sentinel is not a number -----------------------------------------
capped = classify({"mom_change": 100.01, "wow_change": 100.01})
check("the display cap sentinel is NOT read as a 10,001% rise",
      capped["verdict"] != "rising", capped)
check("it is unmeasured, because the real value is unknown above the cap",
      capped["verdict"] == "unmeasured", capped)
check("and no momentum figure survives it", capped["mom"] is None, capped)
# Raw >= 100.01 renders as "10,000%+" in Pinterest's own UI — the true value is
# censored, not measured. clamp_change already knew this; this join reuses it.

above = classify({"mom_change": 250.0, "wow_change": None})
check("anything above the sentinel is censored too",
      above["verdict"] == "unmeasured", above)

# --- a week alone cannot establish a direction -------------------------------------
week_only = classify({"mom_change": None, "wow_change": 0.4})
check("wow without mom refuses to call a direction",
      week_only["verdict"] == "unmeasured", week_only)
check("and says why", week_only["basis"] == "no_month_over_month", week_only)
check("while still carrying the weekly figure it does have",
      week_only["wow"] == 0.4, week_only)
# A seasonal term can swing 30%+ in the week it enters its ramp; that is not a trend.

check("the rising threshold is stated, not implicit", RISING_MOM == 0.10)
check("a value exactly at the threshold counts as rising",
      classify({"mom_change": RISING_MOM})["verdict"] == "rising")

# --- the index is a DIRECT lookup, not a fuzzy match -------------------------------
idx = series_index([{"term": t, "growth_rates": g} for t, g in LIVE.items()])
check("Pinterest echoes the term back, so the key is exact",
      set(idx) == set(LIVE), idx)
check("a series with no term is skipped rather than keyed on None",
      series_index([{"growth_rates": {}}]) == {})
check("an empty response is not fatal", series_index(None) == {})
# The stored-topic join needed content-word matching and scored 0 matches on 1,333
# terms. This asks Pinterest about OUR terms, so no matching exists to get wrong.

# --- attach reports; it never reorders or overrides --------------------------------
pool = [
    # A real decline, to exercise the conflict path. The live macrame reading is
    # -7% and therefore flat; this is what a term actually dying looks like.
    {"term": "dying craft", "verdict": "contested",
     "winnability": {"demand_per_listing": 0.27},
     "intent": {"verdict": "strong", "cvr_vs_pool": 2.73}},
    {"term": "christmas eve box", "verdict": "contested",
     "winnability": {"demand_per_listing": 0.28},
     "intent": {"verdict": "typical", "cvr_vs_pool": 1.66}},
    {"term": "custom family name necklace", "verdict": "weak_intent",
     "winnability": {"demand_per_listing": 1.744},
     "intent": {"verdict": "weak", "cvr_vs_pool": 0.16}},
]
idx_with_decline = dict(idx, **{"dying craft": {"mom_change": -0.34,
                                               "wow_change": -0.1}})
tagged = attach(pool, idx_with_decline)
check("every candidate keeps its position", [c["term"] for c in tagged]
      == [c["term"] for c in pool], tagged)
check("and its verdict is untouched by momentum",
      [c["verdict"] for c in tagged] == [c["verdict"] for c in pool], tagged)
# Momentum is a third AXIS, not a fourth gate: Pinterest covers under half the pool,
# so gating on it would reject terms for absence rather than for evidence.
check("the candidate Pinterest does not track still gets a momentum block",
      tagged[2]["momentum"]["verdict"] == "unmeasured", tagged[2])

# --- the conflict this join exists to surface --------------------------------------
mph = tagged[0]   # "dying craft": strong intent, -34% MoM
c = conflicts(mph)
check("a term that converts well AND is dying raises a conflict", len(c) >= 1, c)
check("and the conflict states both readings, rather than averaging them",
      any("rank here" in x and "dying" in x for x in c), c)
check("including the shrinking-pool reading",
      any("shrinking" in x for x in c), c)
# macrame plant hanger: 2.73x the pool median on intent, -7% MoM on Pinterest. Both
# Etsy gates approve it and Pinterest says it is dying. No Etsy-only view can see it.

check("agreeing axes produce no conflict", conflicts(tagged[1]) == [], tagged[1])
check("and an unmeasured momentum cannot contradict anything",
      conflicts(tagged[2]) == [], tagged[2])

# The other direction: attention without purchase intent, the classic Pinterest trap.
trap = attach([{"term": "ceramic vase", "verdict": "contested",
                "intent": {"verdict": "weak", "cvr_vs_pool": 0.4}}],
              {"ceramic vase": {"mom_change": 0.5}})[0]
check("rising on Pinterest while converting badly is called out",
      any("without purchase intent" in x for x in conflicts(trap)), conflicts(trap))

# --- render -------------------------------------------------------------------------
out = render(tagged)
check("the render shows all three axes on one line",
      "rank=" in out and "intent=" in out, out[:200])
check("and surfaces the conflict beneath the term", "⚠️" in out, out[:400])
check("an unmeasured term renders without crashing on a None ratio",
      "custom family name necklace" in out)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
