---
name: bias-aware-analysis
description: Use when building, reviewing, or extending any data-analysis feature that produces estimates, scores, rankings, or predictions from scraped or third-party data. Enforces naming the denominator, separating independent sources before combining them, treating capped values as bounds, and flagging survivorship and selection effects. Trigger on scoring logic, sales estimation, competitor analysis, trend prediction, ranking features, or any code that turns observed data into a recommendation.
---

# Bias-Aware Analysis

You build analysis features that **know what they cannot see**. The failure mode
here is not a crash — it is a plausible number that is quietly wrong. Every rule
below prevents one specific way that happens.

## The prime directive

> Before shipping any estimate, state what would have to be true for it to be
> wrong, and whether you can observe that.

If you cannot observe it, the estimate ships with a flag saying so. A number with
an honest caveat beats a confident number every time.

## The six checks — run these on any analysis feature

### 1. Name the denominator (survivorship)

Scraped data shows **survivors**. Search results contain listings that ranked;
the failures are invisible and always will be.

- Never report "this niche performs well" from top-N data alone — that is
  "survivors performed well."
- Where possible compute a crude survivor ratio (e.g. total supply ÷ items with
  any reviews) and report it as a known unknown.
- Prefer signals that reveal the failure side: items sorted newest with zero
  engagement after N days are an observable death rate.

### 2. Keep independent sources independent until each is confirmed

When two data sources measure different worlds (discovery interest vs purchase
intent; social momentum vs marketplace search), they must be validated
**separately** before any combined score exists.

- Emit a per-source verdict alongside the combined one.
- "Source A strong / source B weak → may not convert" is a legitimate, useful
  output. Collapsing it into one number hides the disagreement.
- Never let one strong source carry a score when the other is absent or weak.

### 3. Capped values are bounds, not measurements

Any value that is a threshold, a cap, or a sentinel — "20+", "10,000%+", a badge
that only appears above some level — is **not a measurement**.

- Clamp it, store it as a bound, never average it.
- Selection effect: a badge you only observe when a threshold was crossed
  systematically overestimates when projected forward.
- Note when the indicator is *causal* rather than merely descriptive (visibility
  badges cause the activity they appear to measure).

### 4. Check causality direction on ranked data

"X ranks well and has property P" does not mean P causes ranking. Age, review
count, and platform tenure usually explain more than the property you extracted.

- When mining attributes from top performers, weight toward **young** entries that
  outperform — their attributes are doing real work.
- State the confound in a comment where the inference is made.

### 5. Guard the feedback loop against self-selection

If a system recommends actions and then learns from the outcomes of the actions
taken, it only ever sees its own high-scored recommendations.

- Reserve a fraction of actions as **controls** (deliberately mid/low-scored),
  logged with a control flag.
- Without controls the loop measures precision but never recall — it cannot learn
  that something it rejected would have worked.
- Never auto-tune weights on a self-selected sample below a stated minimum n.

### 6. Freshness is part of the value

A derived record inherits the **oldest** timestamp among its inputs. Carry it
forward as an explicit field. A score blended from fresh and stale inputs is a
score computed across two moments in time, and nothing records that unless you
make it.

## Implementation requirements

Every analysis feature must:

- Attach **provenance** (measured vs derived vs defaulted) to each stored value.
- Attach **confidence** to any composite, degraded by its weakest input.
- Normalize incompatible units (percentile rank within the comparison pool) before
  combining — never multiply raw values from different scales.
- Store the **pool** a relative score was computed in; a percentile is meaningless
  without its comparison set.
- Refuse rather than guess: skip with a logged reason when a required input is
  missing.

## Comment requirements

Where a bias is being mitigated, say so in the code:

```python
# SURVIVORSHIP: this reflects listings that ranked. Failed listings for the same
# query are absent from any SERP and cannot be recovered. Reported alongside the
# survivor ratio (supply / reviewed) so the denominator is at least visible.
```

```python
# SELECTION EFFECT: this badge only renders above a platform threshold, so we only
# observe it on above-threshold days. Projecting it forward overestimates.
# Treated as an upper bound; calibrated against the measured daily delta.
```

## What to write in the UI, not just the code

Surface the limits to the user in plain language:

- "Estimated" must be visibly distinct from measured.
- Say which data is survivor-only.
- Say when a signal predicts *interest* rather than *purchase*.
- Say when timing is a replay of a historical pattern rather than a forecast.
- Low confidence must read as "this is a guess," not as a soft asterisk.

## Anti-patterns

- Presenting an estimate with the same visual weight as a measurement.
- Combining sources into one score before each is independently validated.
- Averaging a capped sentinel.
- Auto-tuning a model on outcomes of its own recommendations, with no controls.
- Letting a stale input silently set the freshness of a fresh-looking score.
- Reporting a percentile without its pool size.
