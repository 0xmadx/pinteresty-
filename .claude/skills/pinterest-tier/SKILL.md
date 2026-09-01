---
name: pinterest-tier
description: Use when calling or reasoning about Pinterest Trends — top_trends, metrics, moments, moment_curve, categories, demographics, expand, sweep — or when joining Pinterest momentum to Etsy demand. Enforces that every count is 0-100 RELATIVE and never absolute volume, that the moment curve arrives newest-first, that click-vs-save is the buyer-vs-dreamer signal, and that a term Pinterest does not track is absent rather than flat. Trigger on Pinterest, momentum, trends, moments, takeoff, seasonal timing, or audience demographics.
---

# Pinterest — the audience and timing tier

Pinterest is where demand **forms** weeks before it reaches Etsy's search box.
That lead time is the entire value: Pinterest is a **leading** indicator where
Etsy is a **coincident** one.

It is also the tier where the most numbers are relative, capped, or backwards.

---

## 1. EVERY count is relative. There is no absolute volume here.

`count`, `normalizedCount`, `searchCount`, `normal_counts`,
`percent_relative_volume` are all **peak-normalised within their own response**,
typically to 100.

- You may compare a series **to itself over time**.
- You may **not** read any of them as searches, saves, or people.
- You may **not** compare numbers **across two responses** — different
  normalisation scope means not comparable.

To compare across scopes use **percentages** (`percent_growth`, `wow/mom/yoy_change`)
— those are absolute. On the shopping side, `total` is **always 0**; Pinterest
withholds absolutes deliberately.

⚠️ **`100.01` is Pinterest's "10,000%+" display cap, not a real value.** Use
`constants.clamp_change()` — averaging it in poisons everything downstream.

---

## 2. The moment curve arrives NEWEST-FIRST

`moment_metrics` is **the only endpoint in this API that resolves below weekly** —
daily, where everything else is weekly-only. It is also the one whose series runs
**backwards**: measured `[0]` = 2026-11-23, `[-1]` = 2025-08-25.

`moment_metrics()` reverses to ascending at the wire boundary and records it in
`series_order`. **A summary statistic taken from the raw head describes the end of
the story** — sampling `[0]` gives `normal_counts: 2` and reads as a collapsed
forecast when it is really the far tail three weeks *after* Halloween. The real
forecast peak was 79.

**`peaks[]` is forward-looking; most of the curve is history.** Read the DATE from
`peaks` and the HEIGHT from the `is_forecast` points, then sanity-check against
last year's observed peak. There is **no `has_prediction` flag** on this endpoint
— a non-null upper bound is the only marker.

---

## 3. Click-vs-save IS the buyer-vs-dreamer signal

`event` genuinely **re-computes** the data; it is not a label swap. Measured on
one category, same call, only `event` varied:

| age band | `OUTBOUND_CLICK` | `SAVE` |
|---|---|---|
| 25-34 | 0.16 | **0.24** |
| 65+ | **0.24** | 0.16 |

The people who *save* skew young; the people who *click through to buy* skew 65+.
**Same category, opposite audience.**

- `OUTBOUND_CLICK` = purchase intent · `SAVE` = aspiration · `ENGAGEMENT` = attention
- Category counts differ per event: 44 / 18 / 35
- `top_products` returns rows on **OUTBOUND_CLICK only**
- **A demographic quoted without naming its event is meaningless.**

`local_math.intent_ratio()` derives clicks-growth ÷ saves-growth from a **single**
response — the intent signal costs nothing extra.

---

## 4. Absent is not fading

Pinterest **drops** terms it does not track. Asked for 7, got 3. A missing term is
**unmeasured**, not flat and not declining (N-02). Always report
`requested vs returned`.

Momentum is a **third axis, never a fourth gate** (D-44) — Pinterest tracks well
under half of a typical pool, so gating on it rejects terms for *absence*.

⚠️ **Join on the TERM, never on stored featured topics.** Matching a candidate
pool against `trend_observations`' 84 topics scored **0 exact and 0 containment
matches** against 1,333 Etsy terms — editorial phrases ("Apple-Themed Preschool
Activities") versus product keywords. Ask `/metrics/` about the pool's own terms
directly, in one batched call. `find_trend` normalises both sides and **refuses a
near match**: importing `cat collar`'s momentum for `dog collar` is a wrong number
wearing a right label.

---

## 5. Regions differ per feature, and the gaps are silent

| Feature | Coverage |
|---|---|
| most endpoints | 32 region codes |
| `top_products`, `editorial`, `featured` | **US / CA / GB+IE only** — others return 200 + empty |
| moments with real DATES | single-country codes only (US CA BR MX IT ES FR DE CO AR) |
| moments, names but **every date null** | GB+IE, NL+BE+LU, SE+DK+FI+NO, IT+ES+PT+GR+MT |
| moments | **JP and IN have none**; AU/NL/IE/GB **400** |

A null takeoff date is *"this region has no ramp data"*, not *"no moment"*.
`moments_calendar(region)` is the **authoritative vocabulary** for which `moments=`
values other endpoints will accept there — a wrong slug is a 400, not an empty
result.

---

## 6. Wire traps that cost a request each

- **age/gender want NUMERIC indices** on flat REST (`ageBuckets=2,3`), **string
  enums** on shopping (`AGE_25_34`). Same UI concept, two schemes. The string form
  on the wrong endpoint returns **500**, which reads as "unsupported" when it is
  supported.
- keywords must be **lowercase** — uppercase returns 200 with an empty list
- moment slugs: lowercase, apostrophes **stripped**, spaces kept
- `lookbackWindow` is **cosmetic** — byte-identical rows across values
- `shouldMock=true` returns fake 2019 data with a 200
- `limit` defaults to **8** on shopping (max 522) and **50** on search (max 100) —
  the first 50 of a 100-row response are byte-identical, so asking for 100 is free
  breadth

**`expand` at depth 1 costs 2 requests and ZERO `/metrics/` calls** — the series
ride inside the prefix/related responses. Best value on the whole surface. Depth 2
costs ~32.

---

## Anti-patterns

- Reading any count as a real volume
- Comparing normalised numbers across two responses
- Averaging `100.01` instead of clamping it
- Reading the moment curve forward off the raw wire
- Quoting a demographic without its `event`
- Treating a term Pinterest omits as fading
- Gating a candidate pool on Pinterest momentum
- Matching Etsy keywords against stored Pinterest topic names
