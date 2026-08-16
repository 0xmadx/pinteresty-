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

### JOIN 2 — winnable AND rising (Etsy private × Pinterest)
The single highest-value join, and not yet wired:

```
Etsy seed crawl        →  custom family name necklace: WINNABLE (1.74 demand/listing)
Pinterest related/momentum  →  is that term RISING or fading?
```

Winnable + rising = the jackpot. Winnable + fading = a trap the Etsy-only view cannot
see. Neither platform finds this alone.

### JOIN 3 — buyers, not dreamers (Pinterest intent × everything)
```
a niche survives winnability + profit
        │
top_categories OUTBOUND_CLICK vs SAVE  →  are these people buying or daydreaming?
```
A niche high in SAVE but low in OUTBOUND_CLICK is a Pinterest daydream that will not
convert on Etsy. The intent gate is the last filter before a blueprint.

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
5 INTENT     Pinterest OUTBOUND_CLICK vs SAVE  → buyers or dreamers?
6 JUDGE      winnability × profit gate  → does it pay?
7 GENERATE   Etsy public tags + Pinterest demographics  → the blueprint
8 TRACK      Etsy public over time  → did it work
```

**The ordering is the discipline:** cheap and wide first (discovery), scarce and precise
last (the seller account). Each stage narrows the field so the expensive call is spent
only on survivors.

---

## What is BUILT vs what these joins still need

| Join | Status |
|---|---|
| Etsy seed crawl → winnability → profit → blueprint | ✅ `hunt --seed` |
| Product type detection costing each candidate right | ✅ |
| Shared seasonal slug (moments ↔ calendar) | ✅ vocabulary confirmed, not yet wired into hunt |
| Etsy chart-series cycle → list-by date on a pocket | ❌ the next build (calendar) |
| Pinterest momentum onto Etsy pockets (JOIN 2) | ❌ |
| Intent gate (JOIN 3) | ❌ |
| Demographics → tags (JOIN 4) | ⚠️ demographics endpoint unproven; use Search filters |

The machine already does the hard half (discovery → winnability → profit → blueprint,
Etsy-side). The joins above are what turn it from a strong Etsy tool into the thing no
competitor has: **winnable, rising, bought-not-dreamed, in-season, and profitable — all
verified before a single listing goes up.**
