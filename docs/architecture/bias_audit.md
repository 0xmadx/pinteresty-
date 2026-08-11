# Bias Audit — verified against the code

`BIASES_AND_BLIND_SPOTS.md` states its own status plainly: *"inferred from the DOCS,
not verified against the CODE… treat everything below as hypotheses to test."* It asks
for this file as the verified replacement.

This is that file. Each hypothesis is marked **CONFIRMED / WORSE / PARTLY REFUTED /
FIXED / UNVERIFIABLE**, with the file and line that settles it.

**Headline: 8 of 10 hold. One is already fixed, one is half wrong.** The doc was a
better guess than the docs it was inferred from — but two of its claims would have sent
work in the wrong direction, and three of the biases it names are *cheaper to fix than
it assumed*, because the data needed is already being fetched and thrown away.

---

## Verdicts

| # | Bias | Verdict | Settled by |
|---|---|---|---|
| **B-01** | Survivorship | 🔴 **CONFIRMED, unmitigated** — but the fix is nearly free | no `survivor`/`death_rate` anywhere; data already in `api.py:114,162` |
| **B-02** | Rank causality reversed | 🔴 **CONFIRMED, unmitigated** — fix is nearly free | no age weighting in `listing_generator.py`; `shop_years_on_etsy` parsed at `api.py:160`, unused |
| **B-03** | Badge selection | 🔴 **WORSE than described** | `derivations.py:56` — the badge *wins*, it is not a bound |
| **B-04** | LEARN self-selection | 🔴 **CONFIRMED** — introduced 2026-08-11 | `graph_db.launches` has no `is_control` column |
| **B-05** | Source-world separation | 🟠 **CONFIRMED at the scoring layer** | `scoring.py:55,64` — `momentum` merged at 0.15 with no per-source verdict |
| **B-06** | Ratio assumes uniform review propensity | 🟡 **CONFIRMED, mitigation already present** | `derivations.py:29-37`; basis flagged, badge preferred |
| **B-07** | Temporal / last-year timing | 🟢 **PARTLY REFUTED** | `local_math.py:119-124` already guards the 365-day echo |
| **B-08** | Category bias against digital | ⚪ **UNVERIFIABLE from code** | no routing rule exists; the taxonomy claim needs live data |
| **B-09** | Normalized indices have no magnitude | ✅ **FIXED** | `scoring.py` — percentile normalization, 14 references |
| **B-10** | Freshness blending | 🔴 **CONFIRMED, unmitigated** | no `freshness_floor` anywhere; `collected_at` is per-row only |

---

## The three that matter most

### B-03 is worse than the doc says

The doc asks for badge numbers to be treated as **an upper bound**. The code does the
opposite — `derivations.py:53-56`:

```python
thirty_day = int(daily_sales) * 30 if daily_sales and daily_sales > 0 else None
if thirty_day is not None:
    return lifetime, thirty_day, thirty_day, "daily_badge_x30"
```

The badge figure is returned as `chosen` — the *preferred* estimate, ranked above the
ratio because it is "a measurement rather than an inference". That reasoning is right
about provenance and wrong about selection: the badge only renders above a platform
threshold, so it is a measurement **conditioned on its own value**. Multiplying an
above-threshold day by 30 projects the best day of the month across the whole month.

Provenance is honest here (`basis="daily_badge_x30"` is stored), which is why this is a
bias rather than a bug — the number is labelled, just not bounded.

### B-01 and B-02 are cheap, not expensive

The doc treats survivorship as near-unfixable. It is unfixable in general, but the
*crude* mitigation it proposes is nearly free, because `parse_search_html` already
fetches both halves and discards one:

- `api.py:114` — `total_results` (supply for the query)
- `api.py:162` — `review_count` per card

The ratio of cards with any reviews to total supply is a survivor rate, computable with
no extra request. Same for B-02: `api.py:160` already parses `shop_years_on_etsy`, and
`listing_generator` mines tags from the top 10 with no age weighting at all. Both fixes
are arithmetic over data already in memory.

### B-04 is a gap this project just created

`launches` was built on 2026-08-11 with `predicted_score`, `predicted_profit`,
`product_type`, `notes` — and no control flag. The table is still **empty**, so adding
`is_control` costs nothing today and becomes unfixable-in-retrospect the moment real
launches accumulate. D-12's 10-launch gate counts launches; it does not yet distinguish
"10 things we recommended" from "10 things that tested the model".

---

## Where the doc is wrong

**B-07 — the mechanical bug is already guarded.** The doc says takeoff timing is
"last year + 365 days exactly" and treats that as live. `local_math.py:119-124`:

```python
def _drift(takeoff, last_year):
    if not last_year:
        return None
    gap = (takeoff - last_year).days
    return gap - 365 if 300 <= gap <= 430 else None
```

Someone already found that Pinterest echoes the same timestamp into both blocks and
returns `None` rather than a fake `-365d` drift. **The underlying concern survives**:
`list_by` is still derived from a single prior year, so an anomalous year still produces
anomalous timing. But the specific bug named is fixed, and re-fixing it would be waste.

**B-09 — already fixed.** The doc calls unnormalized mixing "the original scoring bug".
`etsy/analytics/scoring.py` percentile-normalizes every dimension within its pool and
stores `pool_id`/`pool_size` on each result. This is done.

---

## Biases the doc did not anticipate

Found by running its own five questions against the code.

### N-01 · The degeneracy trap — a score that cannot discriminate 🔴

With two dimensions at equal weight, one inverted, a pool whose demand and supply are
rank-correlated scores **every candidate at exactly 0.500** — at any pool size. That is
the normal shape of this data (popular keywords carry more listings). Found by running
`master_niche_finder`, not by reading it. `scoring.py` now detects the flat spread,
halves confidence and says "not discriminating" on every row — but the underlying point
stands: **demand/supply alone cannot rank anything.** A ranking that looks meaningful and
is not is precisely this system's stated failure mode.

### N-02 · "Not found" and "not checked" collapse into the same value 🟡

The general form of a bias the doc only names for badges. Fixed in two places this
session (`rank_observations` writes `rank=NULL` for measured-absent and *no row* for
unchecked; review ratings are `None` rather than a fabricated 5), but the pattern recurs
wherever `0` is a default — `listing_api.py:96-98` still returns `0` for `daily_sales`,
`daily_views` and `scarcity_stock` when the badge is simply absent, and
`grid_analytics.py` branches on `daily_sales > 0`. Absent and zero take the same path
while meaning opposite things.

### N-03 · Cache staleness is a bias, not just a performance concern 🟠

`related_terms` and `prefix_match` are cached under **dateless keys**
(`endpoints/api.py:269,285`) while `metrics` is keyed by date (`:237`). All three return
weekly time series. A series harvested weeks ago is served as current and fed to the
graph pipeline. This is B-10's freshness bias with no `collected_at` to even inspect —
the value is stale *and unlabelled*. Filed separately as **T-3**.

---

## What the UI must carry (Tier 4, verified)

The doc's five UI statements are all still true of the code as it stands:

| Statement | Status in code |
|---|---|
| "Estimated means estimated" | ✅ every derived value carries a `basis` |
| "Survivor data only" | 🔴 no survivor ratio computed — the UI cannot show what nothing measures |
| "Pinterest predicts interest, not purchases" | 🟠 no per-source verdict exists to display |
| "Timing is last year's pattern" | 🟢 drift guarded; single-year reliance remains |
| "Low confidence is not a soft warning" | ✅ `confidence` on every score, degraded by weakest input |

Two of these cannot be honoured by the UI until the backend produces the number.
Per `ui-builder`'s prime directive, those get an **empty state that says why**, not a
fabricated figure.
