# TESTING STRATEGY

*The most important missing document. This system's failure mode is **a plausible
wrong number, not an error** — which means tests are not a quality nicety, they are
the primary defense. Every guard in the architecture is only real if a test proves
it fires.*

**The model already exists in this project.** The Pinterest half is trustworthy
because of 206 live checks that assert nothing from memory, record negative results
with equal weight, and double as drift canaries. That discipline extends to
everything.

---

## The governing principle

> A test that only checks "it didn't crash" is nearly worthless here. Every module
> in this system can run perfectly and return a number that is quietly wrong. Tests
> must assert **correctness of value and of provenance**, not absence of exception.

Concretely, a degenerate-input pass on the Pinterest products found **three silent
defects** — nothing crashed, three things were wrong. That is the expected yield.

---

## Six test categories, in priority order

### 1. Guard tests — highest priority

The guards are the system's whole safety story. Each needs a test that proves it
fires *and* a test that proves it doesn't fire spuriously.

| Guard | Must prove |
|---|---|
| Sentinel clamping | `100.01` → `None` + `capped=True`; `0.35` passes through untouched |
| Badge sentinels | "20+ in cart" stored as lower bound, never a point estimate |
| `noisy` propagation | Set at Bronze→Silver, survives the join, neutralizes momentum in scoring |
| `cvr_source` | `default` → views refused, confidence low; `private` → computed |
| `collected_at` | Stamped on every row, never null |
| `freshness_floor` | Equals the **oldest** input's timestamp, not the newest |
| Temporal append | A second ingest of the same term **adds a row**, doesn't overwrite |

⚠️ **The temporal guard test is the one that would have caught the `trends_store.py`
bug.** Write it first: ingest a term, ingest it again with a new value, assert two
rows exist and the original is intact.

### 2. Golden tests — known input, known output

Freeze a small fixture pool and assert exact outputs for scoring and profit. These
catch unintended changes when weights, fees, or formulas move.

- Profit: a physical product at known price/COGS/shipping → exact per-unit profit,
  exact margin, exact verdict.
- Scoring: a fixed 5-candidate pool → exact ranking, exact percentiles.
- When a golden test changes, that's a **decision**, not a fix — update it
  deliberately and note it in `DECISION_LOG.md`.

### 3. Property tests — invariants that must always hold

Use Hypothesis. These catch classes of bugs golden tests miss.

| Property | Why |
|---|---|
| profit per unit ≤ price, always | catches sign/fee errors |
| margin ∈ [-∞, 1.0], never > 1 | you can't keep more than the price |
| percentiles ∈ [0, 1] for any input distribution | ranking correctness |
| a candidate that improves on one variable, all else equal, never scores lower | monotonicity — catches weight-sign bugs |
| adding a candidate never changes another's *relative* order on a single variable | percentile sanity |
| clamped output is never > CHANGE_CAP | sentinel containment |
| digital profit is independent of shipping input | type routing works |

### 4. Contract tests — against the real sources

Modeled directly on the Pinterest suite. These are the drift canaries.

- Assert **response shape**, not values (values change; shapes shouldn't).
- Assert that documented fields exist and are the documented type.
- Assert the **negative results** too — e.g. "`seasonality_score` is not derivable
  from the series" — because a broken derivation returns a plausible number.
- Exit non-zero naming the broken claim, so the suite tells you *what* drifted.
- Run before trusting any doc claim after a gap in work.

### 5. Degenerate input tests — where the silent bugs live

For **every** public function: empty list, `None`, single item, unknown key, empty
string, zero, negative, all-identical values. The Pinterest pass found three real
defects this way, all silent.

Known landmines in the current code:
- `score_pool([])` → must return `[]`, not crash
- `score_pool([one])` → must flag "no pool", not report a confident percentile
- a pool where every candidate is `noisy` → momentum distribution is empty
- `percentile(x, [])` → 0.5 neutral, not a division error
- profit with `price=0` → no division by zero in margin

### 6. Pipeline / integration tests

End-to-end on fixtures: Pinterest records → trends (guards) → candidates → scored.
Assert the *whole chain* preserves provenance — that a `noisy` term entering Bronze
is still flagged in the final score. `trends_store.py`'s demo is already this
shape; formalize it as a test.

---

## What must NOT be tested against live sources

Contract tests hit real endpoints; everything else uses fixtures. Reasons: live
tests are slow, flaky, quota-consuming, and — most importantly — **non-deterministic
tests train you to ignore failures.** Keep the live suite small, named, and
separately invoked.

---

## Fixtures

- Capture **real** responses once, strip PII, commit as fixtures. Never hand-write
  a fixture that pretends to be a real response shape.
- Keep a `fixtures/` tree mirroring the Bronze layout.
- Bronze *is* your fixture source: any archived raw response can become a test case.

---

## Coverage targets (opinionated)

| Layer | Target | Why |
|---|---|---|
| Guards (Bronze→Silver) | **100%** | the safety story; no exceptions |
| Scoring + profit math | **~95%** | pure functions, cheap to cover |
| Pipelines | happy path + one failure path each | integration, not exhaustive |
| Adapters | contract tests only | shape, not logic |
| Access layer | **not tested here** | out of scope for this project |

Coverage percentage is a weak signal generally — but for the guard layer it's a
real requirement, because an untested guard is an assumed guard.

---

## Running

```
pytest tests/unit          # fast, fixtures only — run constantly
pytest tests/property      # hypothesis — run pre-commit
pytest tests/integration   # end-to-end on fixtures — run pre-merge
pytest tests/contract      # LIVE sources — run deliberately, before trusting docs
```

Only the contract suite touches the network. Everything else runs offline in
seconds.

---

## Regression discipline

**Every bug found gets a test before it gets a fix.** The two known defects right
now are the first two entries:

1. `trends_store.py` overwrites history → write the two-row assertion, watch it
   fail, then fix the schema.
2. Duplicate `scoring.py` / `scoring_engine.py` → resolve, then a test that imports
   the surviving one by name so the ambiguity can't return.

---

## What good looks like

The Pinterest suite is the benchmark: **206 live checks, negative results recorded
alongside positive ones, and a failure names the broken claim.** When this system's
suite can do that — tell you *which* assumption stopped being true — the tests have
stopped being a chore and become the thing that lets you trust a number you didn't
compute by hand.
