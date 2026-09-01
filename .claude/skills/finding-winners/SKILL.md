---
name: finding-winners
description: Use when hunting for a product to list — running discover, crawling a seed keyword, ranking a candidate pool, or deciding whether a term is worth the operator's next launch. Enforces the wall check before anything else (a term with 2M listings is a wall, not an opportunity), the intent gate on top of it (winnable is not the same as bought), the margin floor, and refusing to rank a pool the dimensions cannot separate. Trigger on find a product, opportunity, niche, ranking candidates, keyword crawl, or "what should I list".
---

# Finding winners — the order the gates fire

The operator has **one** shop, ~10 hours a week, and **0 launches recorded**, so
LEARN cannot calibrate anything yet. Every recommendation is currently a
*prediction with no track record*. Say so.

The failure mode here is not a crash. It is **a plausible wrong number ranked
first**.

---

## The gate order. It is not negotiable, and each gate can only reject.

```
1. WALL CHECK        demand ÷ supply       — can you rank here at all?
2. INTENT GATE       relative query_cvr    — do these searchers buy?
3. MARGIN FLOOR      price reality         — does a sale pay?
4. TIMING            takeoff → list-by     — is it too late?
5. DISCRIMINATION    can_discriminate()    — may this pool be ranked at all?
```

A term must survive **all five**. The headline verdict is the **worst** of them,
never an average — averaging lets a huge market hide a closed door.

---

## 1. The wall check comes FIRST (D-31)

`discover` originally sorted by **search volume**. Every number correct, every
recommendation wrong:

| Term | Volume | Supply | Demand/listing |
|---|---|---|---|
| `home decor` *(was ranked 1st)* | 310,467 | 2,160,627 | **0.14** |
| `backpack name tag` *(was 17th)* | 69,874 | 25,031 | **2.79** |

**Rank by winnability, never by market size.** Show the **ratio itself**, not a
composite score — "you cannot rank here" has to be checkable by the operator.

---

## 2. …but winnable is not the same as bought (D-43)

That ratio divides searches by listings — **both supply-side**. A term passes on
traffic alone. The expansion endpoint returns **no CVR at any price**, so DISCOVER
ranked `custom family name necklace` **first** while it converts at **0.15×** the
median of the terms measured beside it. **5 of the top 6 were the same story.**

`confirm_intent` is the second gate: one `results_data` call per top candidate.

⚠️ **It is deliberately RELATIVE.** `query_cvr` has no known units — compare it
between terms, never threshold it as orders. `volume × query_cvr` implies 39.8
orders/month market-wide for `personalized gift`, whose #1 listing holds 14,733
reviews.

---

## 3. The margin floor: price off page one, not off the band (D-46)

`results_data`'s median price band is **market-wide** — it includes every dead
listing that never ranks. On `personalized baby blanket` the band was
**$11.70–$14.30**; the 20 listings that actually rank charged a median of
**$25.19**, free in the same response.

Pricing the ceiling off the band → **$5.21** COGS ceiling (POD near-impossible).
Off page one → **$12.69** (plausible). Same term, opposite conclusion.

**The output is never "profitable."** Printify's catalog has no variant price, so
POD costing returns *a ceiling plus a handoff to the operator*. **COGS is
operator-confirmed or it does not exist.**

---

## 4. Timing can reject a survivor

A term that passes all three economics gates can still be **too late**. See
`calendar-and-timing`. `christmas ornament` peaks in November at **93×** its
trough; `mom necklace` peaks in **December**, not May. A "winner" found in
October for a November peak is a term you cannot build rank in.

---

## 5. Refuse rather than guess (N-01)

- `score_pool` raises `PoolTooSmall` rather than scoring 2 candidates
- `can_discriminate()` **refuses to rank** when the dimensions cannot separate the pool
- `survivor_bound` reports a **bound**, never a rate, and calls a 100% share `uninformative` rather than "healthy"
- a failed fetch is never cached; a failed scrape is never stored as `0`

⚠️ `can_discriminate()` returns a **NamedTuple**, which JSON-serialises to a bare
array with every field name lost. Convert to an explicit dict at the MCP boundary.

**"I cannot separate these six terms" is a valid, useful answer.** Ranking them
anyway manufactures confidence the data does not contain.

---

## Spending the crawl budget

The recursive crawl costs **~35 private seller requests and ~90 seconds per
keyword** at `iterations=10` (capped to 3 on the MCP path). The budget is **hard
and refusing** — an over-cap request gets a failure naming the cap, never a silent
clamp, because the seller account is irreplaceable (D-29).

Every crawl reports `spent` / `remaining` / `stopped_because`. Going deeper is an
**explicit second call**, never an automatic escalation.

⚠️ `private_requests_upper_bound` is a **bound**. A crawl of an already-cached
neighbourhood returns in under a second having spent **nothing** — caches are 7
days (`results_data`) and 30 days (`similar_keywords`).

**Stop early** when the neighbourhood is exhausted, when winnability collapses, or
when the budget is nearly spent. Report which.

---

## The bias that survives every gate

- **B-01 survivorship** — `trending` returns **Etsy's picks**, not the market. Only 7 of 15 taxonomy ids return anything at all.
- **B-04** — the control ratio has a ~0.1 floor; a model validated only on its own recommendations validates nothing.
- **Competitor review velocity is the one unbiased outcome dataset** available, because their launches are independent of our model.
- **N-02** — a term Pinterest does not track is *unmeasured*, not fading. Momentum is a **third axis, never a fourth gate**.

---

## And the part no gate measures

Opportunity scores are computable by anyone, which is exactly why chasing them
commoditises. The gates tell you **where you are allowed to compete**. They cannot
tell you what to make. **Brand and taste are the only parts nobody can copy** —
the system's job is to stop the operator wasting a launch, not to choose one.

---

## Anti-patterns

- Ranking by search volume, or by any composite that hides the ratio
- Passing a term on demand-per-listing alone without the intent gate
- Pricing the margin floor off the market-wide band
- Averaging the gates instead of taking the worst
- Scoring a pool the dimensions cannot separate
- Calling anything "profitable" without operator-confirmed COGS
- Presenting a bound, a floor, or a relative rate as a quantity
- Reporting a derived request count as though it were measured
