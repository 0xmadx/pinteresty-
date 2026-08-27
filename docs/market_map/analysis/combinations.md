# Analysis — Combinations (the edge no single source has)

This is the point of the whole system. Any competitor can read one platform. The edge is
in the **joins** — where a fact from one source changes the meaning of a fact from
another. No scraper that reads Pinterest OR Etsy alone can produce these.

Reference: the three `reference/` files. Discipline: `etsy-market-intelligence` skill.

---

## The three truths, and why each needs the others

```
        PINTEREST                ETSY PRIVATE              ETSY PUBLIC
        audience truth           demand truth              competition truth
        ─────────────            ────────────              ─────────────────
        is it RISING?            is there DEMAND?          can I RANK?
        who WANTS it?            when does it PEAK?        what do winners DO?
        buyers or dreamers?      real volume + CVR         how crowded?
```

Each answers a question the other two are blind to. A launch decision needs all three,
and getting any one wrong sinks it:

- winnable + rising + profitable, but **nobody actually buys** (SAVE not CLICK) → a dud
- winnable + demanded + buyers, but **fading** (Pinterest momentum down) → a trap
- rising + demanded + buyers, but **a wall** (2M listings) → you never surface
- winnable + rising + buyers, but **the margin loses money** → the profit gate kills it

Only the join catches all four.

---

## The joins, concretely

### JOIN 1 — the shared seasonal vocabulary (Pinterest ↔ Etsy, verified)
Pinterest's `moments` filter and both calendars speak the SAME slug: `mothers day`,
`halloween`, `valentines day`. So:

```
moments_calendar (Pinterest)  →  "halloween" peaks late Oct, list-by date
        │ same slug
top_trends(moments="halloween")  →  the rising Halloween keyword seeds
        │ each seed
get_chart_series (Etsy private)  →  Etsy's OWN 12-month cycle for that seed
```

Two independent seasonal sources (Pinterest moments + Etsy chart-series) that **confirm
or contradict each other**. When both say a term peaks in November, that is a strong
signal; when they disagree, that is a flag to investigate, not a number to trust.

### JOIN 2 — winnable AND rising (Etsy private × Pinterest) — ✅ built, D-44
```
Etsy seed crawl        →  custom family name necklace: WINNABLE (1.74 demand/listing)
Pinterest related/momentum  →  is that term RISING or fading?
```

Winnable + rising = the jackpot. Winnable + fading = a trap the Etsy-only view cannot
see. Neither platform finds this alone. **Built as a third AXIS, not a fourth gate**
(`etsy/analytics/momentum.py`) — Pinterest tracks under half the pool (3 of 7 probed
terms), so gating on it would reject terms for absence rather than for fading.

### JOIN 3 — buyers, not dreamers — this project's intent gate is Etsy-side, not Pinterest ✅ built, D-43
```
a niche survives winnability
        │
confirm_intent()  →  relative comparison of query_cvr against the pooled reference median
```
`volume × query_cvr` for `personalized gift` implied 39.8 orders/month market-wide,
while its #1 listing holds 14,733 reviews — proof `query_cvr` has no absolute units.
The gate that shipped compares CVR **between** terms in the same pool, never as a
threshold. The Pinterest `OUTBOUND_CLICK` vs `SAVE` split described below remains a
real, distinct signal — **unproven** (§9.6 of the endpoint reference: `top_categories`
verified real and separating, but never joined into this gate) — and is the more
literal reading of "buyers, not dreamers." Kept in this doc as the next candidate for
JOIN 3b, not double-counted as already done.

### JOIN 4 — audience-matched tags (Pinterest demographics × Etsy blueprint)
```
Pinterest Age/Gender filter  →  who searches this (female 25-34, say)
        │
Etsy blueprint tags          →  written in THAT audience's language
```
Not "necklace" but the words that demographic actually uses. Audience truth shaping the
listing copy.

---

## The full funnel — all three sources, in order

```
1 DISCOVER   Pinterest (search/spotlight/shopping seeds)  +  Etsy seed crawl
                → wide, cheap, no seller-account risk
2 QUALIFY    Etsy PUBLIC SERP  → real competition, tags, type, category
                → free, narrows the field
3 MEASURE    Etsy PRIVATE  → true volume, CVR, seasonal cycle
                → scarce, spent only on what survived 1–2
4 TIME       Pinterest moments  ∩  Etsy chart-series  → two seasonal sources agree?
                → this is what the CALENDAR runs on, built 2026-08-19
5 INTENT     confirm_intent()  → query_cvr vs the pooled reference median (D-43, built)
                → Pinterest OUTBOUND_CLICK vs SAVE is the literal "buyers or
                  dreamers" version of this step and remains UNBUILT — see the
                  JOIN 3 note above. Do not read step 5 as that join; it isn't.
6 JUDGE      winnability × profit gate  → does it pay?
                → for physical/POD, priced against page-one actual prices, not
                  the market-wide band (`pod_check.py`, D-46, built)
7 GENERATE   Etsy public tags + Pinterest demographics  → the blueprint
8 TRACK      Etsy public over time  → did it work
```

**The ordering is the discipline:** cheap and wide first (discovery), scarce and precise
last (the seller account). Each stage narrows the field so the expensive call is spent
only on survivors.

---

## What is BUILT vs what these joins still need — re-audited 2026-08-27

**This table was badly stale as of its previous version (dated 2026-08-16): three of
the four items it marked ❌ "not yet built" were built within days of that date. Kept
visible rather than quietly corrected, because it is itself the case study for why
this whole file needs a re-audit before being trusted — a doc that goes 11 days
without a check drifts from mostly-true to mostly-false.**

| Join | Status |
|---|---|
| Etsy seed crawl → winnability → profit → blueprint | ✅ `hunt --seed` |
| Product type detection costing each candidate right | ✅ |
| Shared seasonal slug (moments ↔ calendar) | ✅ **wired into the calendar**, 2026-08-19 — was "not yet wired into hunt" |
| Etsy chart-series cycle → list-by date on a pocket | ✅ **built** — `etsy.engines.calendar_engine`, 2026-08-19 |
| Pinterest momentum onto Etsy pockets (JOIN 2) | ✅ **built** — `etsy.analytics.momentum`, D-44 |
| Intent gate (JOIN 3, the CVR version) | ✅ **built** — `confirm_intent()`, D-43 |
| Pinterest OUTBOUND_CLICK vs SAVE (JOIN 3, the literal version) | ❌ still open — `top_categories` verified real and separating, never joined to the gate |
| Demographics → tags (JOIN 4) | ⚠️ demographics endpoint still unproven; use Search filters |
| Etsy `daily_stats` → sharper takeoff-date detection | ❓ found 2026-08-27, not yet built — see `reference/etsy_private.md` |
| Etsy public pagination (page 2+) | ❌ still open, confirmed unfixed 2026-08-27 — caps the survivor bound, competitor analysis and rank tracking at page 1 |
| Printify cost → profit gate ceiling | ✅ **built** — `pod_check.py`, D-46 (not a join this doc originally listed; added because it now exists) |

The machine already does the hard half (discovery → winnability → profit → blueprint,
Etsy-side, PLUS timing and momentum). What's still genuinely open: the literal
Pinterest buyer-vs-dreamer split, demographics-into-tags, the free daily time series,
and Etsy's own pagination gap.
