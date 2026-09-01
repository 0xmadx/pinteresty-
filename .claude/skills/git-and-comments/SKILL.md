---
name: git-and-comments
description: Use when writing, refactoring, or organising code. Enforces consistent git commit discipline (atomic commits, conventional messages, meaningful history) and code commenting standards (why not what, guard explanations, data-flow annotations). Trigger on any coding task, file creation, refactor, or when asked to "commit", "organise git", or "add comments".
---

# Git & Code Comments

Two disciplines, always active together when writing code.

---

## Git — atomic commits with meaningful history

### The commit rule
One logical change per commit. A commit should be revertable without
breaking anything else. Never bundle unrelated changes.

### Commit message format (Conventional Commits)

```
<type>(<scope>): <short summary in present tense, under 72 chars>

<optional body: WHY this change, not what — the diff already shows what>

<optional footer: BREAKING CHANGE, closes #issue>
```

**Types:**
| Type | When |
|---|---|
| `feat` | new capability added |
| `fix` | corrects a bug |
| `refactor` | restructures without changing behaviour |
| `test` | adds or fixes tests |
| `docs` | documentation only |
| `chore` | config, deps, tooling |
| `guard` | adds or fixes a data-integrity guard (sentinel, noisy, freshness) |
| `data` | schema changes, migrations |
| `perf` | performance improvement |

**Scope** is the module or layer: `scoring`, `profit`, `trends`, `guards`,
`api`, `pipeline`, `store`, `config`.

**Examples:**
```
feat(scoring): add percentile normalisation to fix unit-mixing bug

The old formula multiplied Etsy absolute counts by Pinterest 0-100 indices.
Whichever variable had the biggest raw range silently dominated the score.
Percentile ranking makes every variable comparable before weighting.

guard(trends): make ingest append-only to preserve history

ON CONFLICT DO UPDATE was overwriting time-varying rows, which would make
the LEARN backtest compare predictions against inputs that had changed.
Now inserts a new row per collected_at; _latest view serves current state.

fix(profit): clamp margin floor check to product type

Digital products were being rejected for failing the physical margin floor.
Dimension sets must be selected by type, not applied universally.
```

### Branch naming
```
feat/scoring-percentile-fix
fix/trends-temporal-bug
refactor/extract-guard-boundary
test/guard-sentinel-clamping
docs/architecture-pass
```

### What NOT to do
- `git add .` followed by `wip` or `fix stuff` — every commit must be
  intentional and describable
- Committing broken code — each commit must pass tests
- Bundling a feature with a refactor — separate commits
- Committing secrets, `.env`, `data/`, or PII — check `.gitignore` first

### Commit sequence when writing new code
1. `chore`: config, deps, folder structure first
2. `test`: write the test (it fails — that's correct)
3. `feat` or `fix`: write the code until the test passes
4. `docs`: update any affected documentation
Never skip step 2. A guard without a test is an assumed guard.

---

## Code Comments — why, not what

### The rule
**Never comment what the code does. Comment why it does it, and why the
alternatives were rejected.**

The code already says *what*. The comment must add information the code
cannot express.

### Bad (states the obvious):
```python
# multiply price by transaction rate
fee = price * TRANSACTION_RATE
```

### Good (explains the why and the trap):
```python
# Etsy charges transaction fee on the FULL price even when shipping is
# absorbed — do not subtract shipping_cost before this calculation or
# the fee is understated. Verified against Etsy's fee schedule 2026-01.
fee = price * TRANSACTION_RATE
```

### Guard comments are mandatory

Every guard must have a comment that explains:
1. What the bad value looks like
2. Why it's dangerous (what it would do to downstream calculations)
3. What the correct treatment is

```python
# SENTINEL: Pinterest caps MoM change at 100.01 to represent "10,000%+".
# If averaged into the scoring pool as a literal, it pins that term to
# rank #1 on momentum forever, regardless of its real velocity.
# Clamp to None; the scorer falls back to YoY or skips momentum entirely.
if abs(value) >= CHANGE_CAP:
    return None, True
```

### Data-flow annotations

At the top of every function that transforms data, state:
- what it receives (and from which layer)
- what it emits (and to which layer)
- which guards it applies or expects to already be applied

```python
def assemble_candidates(store: TrendsStore, etsy_by_term: dict):
    """
    Silver → Gold assembly.

    Receives: cleaned trends rows (sentinels clamped, noisy flagged,
              collected_at stamped) from TrendsStore (Silver layer).
              Etsy demand/supply data keyed by term (also Silver).

    Emits: Candidate dataclasses ready for score_pool() (Gold layer).
           Each carries noisy, cvr_source, and freshness_floor so the
           scorer can gate on confidence without re-inspecting provenance.

    Guards expected ALREADY applied by caller (Bronze→Silver boundary):
    - sentinel clamping
    - noisy flag set
    - collected_at present

    This function REFUSES (skips with reason) rather than guesses when:
    - a term has no Etsy validation yet
    - momentum is None with no fallback
    """
```

### Module headers

Every module gets a header comment:
```python
"""
profit_calculator.py

Layer: analysis/ (pure functions — no I/O, no imports from other layers)
Purpose: compute profit per unit and monthly potential for all three
         product types, with Etsy fees, capacity limits, and confidence.

Key decision: per-unit economics are trustworthy arithmetic; monthly
profit inherits the volume estimate's confidence and is flagged when
the CVR was defaulted. The two never blur. See DECISION_LOG.md D-01.

Fee schedule: see config.yaml profit.fee_schedule_verified.
Verify against Etsy's current rates before trusting dollar figures.
"""
```

### Honesty comments — required for known issues

If a piece of code has a known flaw, limitation, or open decision, say so
*in the code*, not just in a doc:

```python
# ⚠️ TEMPORAL BUG: this upsert overwrites history. See DECISION_LOG.md O-2.
# Fix: make append-only with collected_at as part of the primary key.
# Do not build on this until the fix is applied — LEARN backtest depends on it.
self.conn.execute("INSERT ... ON CONFLICT DO UPDATE ...")
```

### What NOT to do
- Commenting every line (clutters; only comment non-obvious things)
- TODO comments without a ticket or decision log entry
- Commented-out code in commits (delete it; git has history)
- Restating the function signature in prose

---

## Putting it together — the sequence for any new file

```
1. Write the module header (layer, purpose, key decisions)
2. Write the test file first (with guard tests first)
3. Commit: test(<scope>): add failing tests for <capability>
4. Write the code with guard comments and data-flow annotations
5. Commit: feat(<scope>): <what changed and why>
6. If a known issue exists, add an ⚠️ honesty comment
7. Update any affected .md in docs/
8. Commit: docs(<scope>): update architecture docs
```

This sequence is the whole discipline in eight lines.
