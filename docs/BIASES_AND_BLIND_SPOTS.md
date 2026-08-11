# BIASES & BLIND SPOTS

*⚠️ These biases are inferred from the DOCS, not verified against the CODE. The
docs have already been wrong three times (the trends table, `private_blueprint`'s
two descriptions, the endpoint's three names), so treat everything below as
**hypotheses to test against the real code**, not confirmed findings.*

*This is a hunting guide, not a verdict. Claude Code runs this audit against the
actual implementation and reports which biases are real, which are worse than
described, and which don't exist. Until then, nothing here is confirmed.*

**How to use this document:**
- Each bias below is a hypothesis with a "where to look in the code" pointer.
- Claude Code confirms, corrects, or refutes each one against the real functions.
- The output is a *verified* bias report replacing this inferred one.
- A bias we guessed wrong is fine. A bias we missed because we only read docs is
  the danger — so the last section lists how to find biases NOT anticipated here.

The system's failure mode is **a plausible wrong number, not an error**. These are
the specific ways that happens — *if the code works the way the docs claim.*

---

## Tier 1 — Structural biases (these distort every score)

### B-01 · Survivorship bias ⚠️ THE WORST ONE

**The problem:** Every listing you analyze is a listing that *survived*. You scrape
SERPs, so you see listings that rank. The failed listings for the same keyword —
the ones that never got a sale, never ranked, got buried — appear in no SERP you
will ever scrape.

**Why it's dangerous:** "This niche has high sales" actually means "the survivors
have high sales." You have **no denominator**. A niche with 3 winners and 500
corpses looks identical to a niche with 3 winners and 5 corpses. The first is a
lottery; the second is a real opportunity.

**Where it enters:** `grid_analytics.py` (top listings only), `single_listing_analytics.py`,
the entire supply-side read.

**Partial mitigations:**
- Total supply count (`organic_listings_count`) vs. listings with *any* reviews →
  the ratio is a crude survivor rate. A niche where 900 listings exist but only 40
  have reviews has a ~95% failure rate.
- Sort by Newest and count how many recent listings have zero reviews after 90
  days — that's an observable death rate.
- **Never claim to have solved it.** Report the survivor ratio as a known unknown.

### B-02 · Rank causality reversed

**The problem:** The system infers "this listing ranks because of its tags." It may
rank because it's 4 years old, has 4,000 reviews, ships free, and Etsy's algorithm
favors established sellers.

**Why it's dangerous:** The Triple-Pass Listing Generator (W10) copies tags from
top-ranked listings. You may be copying a *symptom* of ranking, not a *cause*.

**Mitigation:** Weight tag-mining toward **young listings that rank well** — if a
4-month-old listing outranks established sellers, its SEO is doing real work.
This is the same signal as new-entrant detection (C.2), reused.

### B-03 · Badge selection bias

**The problem:** "17 bought today" appears *because* the number crossed a
threshold. You only observe it on above-threshold days.

**Worse — the badge is causal:** shops with badges get visibility → get sales →
keep the badge. The badge partly *causes* the sales it appears to measure.

**Where it enters:** the "Live Demand Override" in `single_listing_analytics.py` and
`grid_analytics.py`, which explicitly *replaces* the ratio estimate with badge math.

**Mitigation:** Treat badge-derived numbers as an **upper bound**, never a point
estimate. Calibrate against the Daily Sales Delta (the one measured number).

### B-04 · LEARN trains on its own recommendations ⚠️

**The problem:** You only launch products the machine scored high. So `launches`
contains almost no low-score launches. The model learns from a biased sample of
its own outputs and **can never discover that a low-scored niche would have won.**

**Why it's dangerous:** The calibration will look good — high-scored things did
well — while the model is systematically blind to what it rejects.

**Mitigation:** Deliberately launch 1 in 10 as a **control** — a mid or low scorer.
Log it with `is_control=true`. Without controls, the LEARN loop measures precision
but never recall.

### B-05 · Source-world separation (Pinterest ≠ Etsy)

**The problem:** Pinterest momentum and Etsy demand are different worlds. "Coquette
aesthetic bedroom" can explode on Pinterest with zero Etsy search volume, because
nobody types that into Etsy — they type "pink bow picture frame."

**Rule (already in the architecture, restated here as a bias):**
> Pinterest and Etsy are never merged into one score until both are independently
> confirmed. The score shows the combination. The cards show the separation.

**UI requirement:** three source verdicts visible *before* the combined score.
"Pinterest strong / Etsy weak → demand may not convert" is an honest output.

---

## Tier 2 — Measurement biases

### B-06 · The ratio estimator assumes uniform review propensity

`ratio_estimator.py` computes Shop Sales ÷ Shop Reviews, then multiplies by a
listing's review count. This assumes every product in a shop is reviewed at the
same rate. A $12 sticker and a $200 custom piece are not. Error compounds when
`single_listing_analytics.py` then divides by CVR to get Estimated Views.

**Mitigation:** flag `sales_source='ratio'` as low confidence; prefer
`daily_delta` whenever available.

### B-07 · Temporal bias in timing

Pinterest's `takeoff_timestamp_millis` is measured to be **last year + 365 days
exactly**. If last year was anomalous — a viral moment, a supply shock, a
one-off — you're timing this year to a fluke.

**Mitigation:** cross-check against `historical_peaks` and the multi-year history
archive. A single year is an anecdote.

### B-08 · Category bias against digital products

Pinterest's 383-category shopping taxonomy is **physical-goods shaped** (rugs,
tables, jewelry). Printables and digital templates barely appear as categories.

**Consequence:** digital niches systematically get weaker Pinterest signals — not
because demand is weaker, but because the taxonomy doesn't index them.

**Mitigation:** route digital candidates through the Pinterest **search** side
(`top_trends`, `related_terms`), never the shopping/category side. Already in
`MASTER_DOCUMENT.md` §2 as a routing rule; it exists because of this bias.

### B-09 · Normalized indices have no magnitude

Every Pinterest count is 0–100 relative to its own peak. `searchCount: 3` can top
a table. Magnitude comes only from Etsy. Mixing them without percentile
normalization was the original scoring bug.

### B-10 · Freshness blending

A score built from a fresh Pinterest reading and a month-old Etsy supply count is
computed across two moments in time. `freshness_floor` exists to make this visible,
but the bias remains: **the score is only as current as its stalest input.**

---

## Tier 3 — Missing models (things the system doesn't attempt)

| # | Missing | Why it matters |
|---|---|---|
| **M-01** | **Competitor response** | You find a gap, fill it, others follow, the gap closes. Nothing models how fast. A gap with low barriers closes in weeks. |
| **M-02** | **Seasonal cost variation** | Shipping, ad costs, and competition all spike in Q4. A margin computed in July is wrong in November. |
| **M-03** | **Returns & refunds** | Personalized goods have low returns but high dissatisfaction risk; physical goods have real return rates. Neither is in the profit model. |
| **M-04** | **Listing execution quality** | Two identical products with different photos convert differently. The system treats a product as a keyword, not an execution. Photos, video count, and variation count are scrapeable and unused. |
| **M-05** | **Own-catalog cannibalization** | Two of your listings competing for one keyword split your ranking signal. Flagged in the addendum, never designed. |
| **M-06** | **Etsy algorithm changes** | The entire supply/rank model assumes Etsy's ranking is stable. It isn't. Nothing detects a platform-wide shift. |
| **M-07** | **Ad spend by competitors** | A competitor outranking you may simply be paying. `promoted_above` captures ad load but not competitor spend intensity. |
| **M-08** | **Buyer review-rate variance by price band** | Feeds B-06; cheap items get reviewed at different rates than expensive ones. |

---

## Tier 4 — Honest limitations to state in the UI

These should be *visible to the user*, not buried:

1. **"Estimated" means estimated.** Sales, views, and revenue for competitors are
   inferred, not measured. Only your own numbers are real.
2. **Survivor data only.** We show you the listings that ranked. We cannot show you
   the ones that failed.
3. **Pinterest predicts interest, not purchases.** High momentum ≠ high conversion.
4. **Timing is last year's pattern.** Not a forecast — a computed replay.
5. **Low confidence is not a soft warning.** A defaulted CVR or a noisy series
   means the number is a guess wearing a suit.

---

## The bias-check ritual (run before trusting any verdict)

Six questions, in order:

1. **What's the denominator?** How many listings failed in this niche? (B-01)
2. **Are the sources agreeing or is one carrying the score?** (B-05)
3. **Is the ranking signal from young listings or old ones?** (B-02)
4. **Is any number badge-derived?** Treat as upper bound. (B-03)
5. **How stale is the oldest input?** (B-10)
6. **Would I have launched this if the score were 40?** If not, LEARN can't
   learn from it. (B-04)

---

## How to find biases we DIDN'T anticipate (the real job)

The biases above are guesses from docs. The dangerous ones are the biases in your
code that this document doesn't mention. To find them, Claude Code traces the code
and asks, at every point a number is produced:

**The five questions to ask of every computed number in the codebase:**

1. **What population did this sample from, and what's missing from it?**
   (Every scrape samples survivors — but where else? Reviews only from people who
   reviewed. Prices only from active listings. Trends only from indexed categories.)

2. **Is this value observed, or is it standing in for something observed?**
   (A default, a fallback, an "if missing then X" — every one is a hidden
   assumption. Grep for default values, `or 0`, `except: return`, hardcoded
   constants like `0.02` and `1.256`.)

3. **Does this number's existence depend on its own value?**
   (Selection effects: badges that only show above a threshold, listings that only
   appear if they ranked, reviews that only exist if the item sold. The observation
   is conditioned on the outcome.)

4. **When two things are combined, are they the same kind of thing?**
   (Units, scales, time periods, sources. A fresh number and a stale number. A
   normalized index and an absolute count. A measured value and an estimate.)

5. **If this feeds a loop, does the loop only ever see its own outputs?**
   (Anything that learns from the results of its own recommendations.)

**The method:**
- List every function that returns a number used in a decision.
- Run the five questions on each.
- A "yes, and it's not handled" is a bias to log with file + line.
- Produce `docs/architecture/bias_audit.md` — the *verified* version of this doc,
  with each hypothesis marked CONFIRMED / WORSE / REFUTED / NOT-APPLICABLE, plus
  any new biases found by the five questions.

**The honest stance:** we don't know what the code does yet. This document is the
starting hypothesis set. The real bias picture only exists after the code is read.
A verified "we found 4 of these and 3 new ones" beats a confident guess every time.

---

## What this document is for

Not to paralyze the system — to keep it honest. Every tool in this space has these
biases; most don't name them. Naming them lets you:

- put confidence flags where they belong
- avoid the specific traps (control launches, young-listing tag mining, upper-bound
  badge math)
- tell the user what the number *means* rather than just showing a number

**A tool that says "87, but here's what I can't see" is more trustworthy than one
that says "A+" — but only once we've verified against the code what it actually
can and can't see.**
