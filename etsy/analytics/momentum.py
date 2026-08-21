"""JOIN 2 — is a winnable, converting term also RISING? (the third axis)

Etsy answers *can I rank here* (supply) and *do they buy* (D-43's intent gate). Neither
can see whether interest in a term is growing or dying, because Etsy's own `wow_data`
covers one week and nothing longer. Pinterest measures exactly that, for free, with no
seller account at risk — and it is the join `docs/market_map/analysis/combinations.md`
calls the highest-value one in the system.

    winnable + converting + RISING  -> the thing worth building
    winnable + converting + FADING  -> a trap no Etsy-only view can see

**One Pinterest call for the whole pool.** `/metrics/` accepts ~50 terms at once, and
the candidate pool that survives both Etsy gates is far smaller than that, so this
costs a single request regardless of pool size.

WHAT WAS PROBED, AND THE TRAP IT AVOIDS (2026-08-20)
----------------------------------------------------
The obvious implementation joins the momentum already stored in `trend_observations`.
**It returns nothing, ever.** 84 stored Pinterest featured topics against 1,333
discovered Etsy terms gives 0 exact and 0 containment matches — Pinterest writes
editorial phrases ("Apple-Themed Preschool Activities"), Etsy candidates are product
keywords. That is the identical vocabulary mismatch that silently emptied the calendar
for the project's whole life, so it is a known shape rather than a surprise.

So the join asks Pinterest about *our* terms directly instead of matching against the
terms Pinterest chose to feature.

⚠️ **Pinterest DROPS terms it has no data for — it does not return zeros.** Asked for
7 real candidates, it returned 3. A term missing from the response is *unmeasured*,
never "no momentum" (N-02). Coverage is genuinely partial and that is a fact about the
instrument, not a bug to code around.

⚠️ **`100.01` is a sentinel, not a number.** Raw growth values are fractions (×100 for
percent), and Pinterest caps its display at "10,000%+" — every value at or above
`100.01` is that cap, not a measured 10,001% rise. `clamp_change` turns it into None
so it cannot poison an average, and this module reuses it rather than reimplementing.
"""
from pinterest.endpoints.constants import clamp_change

# Month-over-month thresholds, as fractions (0.10 == +10%). Deliberately coarse and
# named, like every other threshold here: they separate a direction from noise, and
# are not a forecast. MoM leads because week-over-week on a single term is mostly
# noise — a seasonal term can swing 30% on the week it enters its ramp.
RISING_MOM = 0.10
FADING_MOM = -0.10


def classify(growth):
    """Pinterest `growth_rates` -> rising / flat / fading / unmeasured, with a reason.

    `growth` is the dict Pinterest returns per series, or None when the term was not
    in the response at all — which is the common case, not an error path.
    """
    if not growth:
        return {"verdict": "unmeasured", "mom": None, "wow": None,
                "basis": "absent_from_pinterest",
                "reason": "Pinterest returned no series for this term — it does not "
                          "track it. That is not evidence of decline (N-02)."}

    # Sentinels out first, or a capped "10,000%+" reads as an explosive real rise.
    mom = clamp_change(growth.get("mom_change"))
    wow = clamp_change(growth.get("wow_change"))

    if mom is None:
        # wow alone is too noisy to call a direction on, and saying so beats
        # inventing one from a single week.
        return {"verdict": "unmeasured", "mom": None, "wow": wow,
                "basis": "no_month_over_month",
                "reason": "no month-over-month figure — a single week cannot "
                          "establish a direction"}

    if mom >= RISING_MOM:
        verdict = "rising"
        reason = f"interest up {mom * 100:.0f}% month-over-month on Pinterest"
    elif mom <= FADING_MOM:
        verdict = "fading"
        reason = f"interest DOWN {abs(mom) * 100:.0f}% month-over-month on Pinterest"
    else:
        verdict = "flat"
        reason = f"interest flat on Pinterest ({mom * 100:+.0f}% MoM)"

    return {"verdict": verdict, "mom": mom, "wow": wow,
            "basis": "measured", "reason": reason}


def series_index(series):
    """`[{term, growth_rates, ...}] -> {term: growth_rates}`, keyed as asked.

    Pinterest echoes the term back, so no fuzzy matching is needed or wanted — this
    is a direct lookup, which is exactly why it works where the stored-topic join
    could not.
    """
    out = {}
    for s in series or []:
        term = s.get("term")
        if term:
            out[term] = s.get("growth_rates")
    return out


def attach(candidates, index):
    """Tag each candidate with its momentum. Never reorders, never changes a verdict.

    **Momentum is a third axis, not a fourth gate.** It does not demote anything, for
    two measured reasons:

      * Pinterest covers under half the pool (3 of 7 probed), so gating on it would
        reject terms for being absent from an instrument rather than for anything
        true about them;
      * a fading term still has today's demand, and whether that is disqualifying is
        the operator's call — the system's job is to make sure they are not surprised.

    So it reports, and the disagreement between axes is the output (B-05, D-38). The
    loudest case this surfaces is real: `macrame plant hanger` converts at 2.73x the
    pool median AND is down 7% month-over-month — a term both Etsy gates approve and
    Pinterest says is dying.
    """
    out = []
    for candidate in candidates:
        momentum = classify(index.get(candidate["term"]))
        out.append({**candidate, "momentum": momentum})
    return out


def conflicts(candidate):
    """The readings that point opposite ways, stated rather than averaged.

    Returns [] when the axes agree or when momentum is unmeasured — an absent
    reading cannot contradict anything.
    """
    m = candidate.get("momentum") or {}
    intent = (candidate.get("intent") or {}).get("verdict")
    verdict = candidate.get("verdict")
    out = []

    if m.get("verdict") == "fading" and verdict in ("winnable", "contested"):
        out.append(
            f"Etsy says you can rank here and Pinterest says interest is dying "
            f"({m['mom'] * 100:.0f}% MoM). Today's demand is real; next quarter's "
            f"may not be.")
    if m.get("verdict") == "fading" and intent == "strong":
        out.append(
            "its searchers convert well today, but the pool of them is shrinking")
    if m.get("verdict") == "rising" and intent == "weak":
        out.append(
            "rising on Pinterest while converting far below its peers on Etsy — "
            "attention without purchase intent is the classic Pinterest trap")
    return out


def render(candidates):
    """Terminal view: the three axes side by side, never collapsed into one score."""
    icon = {"rising": "📈", "fading": "📉", "flat": "➡️", "unmeasured": "· "}
    lines = []
    for c in candidates:
        m = c.get("momentum") or {}
        intent = (c.get("intent") or {}).get("cvr_vs_pool")
        ratio = (c.get("winnability") or {}).get("demand_per_listing")
        lines.append(
            f"  {icon.get(m.get('verdict'), '  ')} {c['term'][:32]:<34} "
            f"rank={ratio if ratio is not None else '?':<6} "
            f"intent={f'{intent:.2f}x' if intent is not None else '?':<7} "
            f"{m.get('reason', '')}")
        for conflict in conflicts(c):
            lines.append(f"{'':>6} ⚠️  {conflict}")
    return "\n".join(lines)
