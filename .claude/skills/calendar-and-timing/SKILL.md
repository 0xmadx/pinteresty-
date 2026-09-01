---
name: calendar-and-timing
description: Use when answering "when should I list this" — building or reading the calendar, reading a Pinterest moment's takeoff and peak, or reading a seasonal curve from chart_series or daily_stats. Enforces that a moment with no takeoff date is dropped rather than defaulted to soon, that past-the-deadline is not the same as missed, that the last chart_series bucket is partial and manufactures a collapse, and that a peak Pinterest never measured cannot be guessed. Trigger on calendar, list by, takeoff, peak, seasonality, timing, or "am I too late".
---

# Calendar and timing — the half no competitor has

Every competitor is a niche checker. **None of them can say *when***, because that
needs Pinterest's takeoff dates joined to Etsy demand and a profit model willing to
say no. This is the product's front door (D-20).

---

## 1. The chain, and the one line that computes it

```
Pinterest moment → takeoff date → list_by = takeoff − lead_weeks
watched terms    → which of them belong to that moment
keyword history  → volume, supply, demand-per-listing, price band
profit gate      → does the money work at the measured price
```

`lead_weeks` defaults to **6** — the operator's build-and-rank runway, not a
Pinterest fact. `list_by` is deliberately **recomputed, never read back from the
database**, so one formula exists in one place.

Dates come from the **database**, not a live call: the calendar must render when
Pinterest is unreachable, and takeoff dates are a **weekly** reading, not a
per-request one. `trends_bridge` writes them; the engine reads the latest.

---

## 2. Five states, and two of them exist to refuse

| State | Meaning |
|---|---|
| 🔴 `list_now` | deadline here or gone, **and the moment has not peaked** |
| 🟡 `list_by` | time remains — the date is the point |
| ⚪ `watching` | beyond the 10-week horizon; nothing to do yet |
| `passed` | the **peak** is behind us — wait for next year |
| `untimed` | deadline gone **and the peak is UNMEASURED** |

**`untimed` is a state of our KNOWLEDGE, not of the world.** It must never collapse
into `passed` (pessimistic — discards a live moment) or `list_now` (optimistic —
puts a dead moment on the operator's list). It says *"re-run the Pinterest bridge
to get a peak."*

---

## 3. Past the deadline is NOT the same as missed

Measured 2026-08-15: Halloween's `list_by` was **7.6 weeks gone** while its peak
was still ~2 months out and Pinterest's own `phase` read **`rising`**.

- Calling that "missed" throws away a live opportunity.
- Calling it "on time" pretends the best window is still open.

It is reported **late, with how late and how long to the peak**, and the operator
decides. The deadline alone is never enough — `weeks_left` and `days_to_peak` are
read together or not at all.

---

## 4. Never invent a date, never invent demand

- A moment with **no takeoff timestamp is dropped**, not defaulted to "soon".
- A term with no keyword observation is **`unmeasured`**, never zero — the
  difference between "nobody wants this" and "we have not looked" is the difference
  between skipping a good niche and chasing a dead one (N-02).
- **A dated moment with no matching term is still shown**, marked as having nothing
  to sell into it. Hiding it silently answers *"is there an opportunity here?"* with
  *"no"*, when the honest answer is *"we have not pointed anything at it."*

Inside a moment, terms sort by **demand-per-listing, not volume** (D-31), and
`WALL_RATIO = 0.20` flags the ones that cannot be ranked into. **Unmeasured terms
sort last because they cannot be compared — not because they are worst.**

⚠️ The profit verdict uses the **LOW** end of the price band: clearing there clears
across it. Using the high end would flatter every candidate.

---

## 5. Two seasonal sources, plus one that is free and daily

| Source | Resolution | Use for |
|---|---|---|
| Pinterest moments | takeoff / peak dates | **when to list** — the leading edge |
| `chart_series` | 12 months, per term | **how big the season is** (D-45) |
| `daily_stats` | daily + 7-day rolling, ~3 weeks | **is it moving NOW** (D-51) |

`daily_stats` rides **free on the same `results_data` call** and was parsed by
nothing until 2026-08-27.

Etsy ships its own seasonal curve free, and every caller read `term_summaries` and
discarded it for the project's whole life. `christmas ornament` peaks in November
at **93×** its trough; **`mom necklace` peaks in DECEMBER, not May** — the obvious
guess is wrong, which is the whole argument for reading the curve.

⚠️ **The last `chart_series` bucket is the current month counted SO FAR.** Judging
on it manufactures a collapse. Drop it, or label it partial.
⚠️ `include_trendline` is **inert** — True and False return identical structures.

---

## 6. Pinterest-side timing traps

- **The moment curve arrives NEWEST-FIRST.** A statistic off the raw head describes
  the *end* of the story. `moment_metrics()` reverses at the wire boundary and
  records `series_order`.
- **`peaks[]` is forward-looking; most of the curve is history.** Read the DATE from
  `peaks` and the HEIGHT from the `is_forecast` points.
- **A null takeoff date means the region has no ramp data**, not that the moment
  does not exist — GB+IE, NL+BE+LU, SE+DK+FI+NO and IT+ES+PT+GR+MT return moment
  names with every date null. JP and IN have none; AU/NL/IE/GB **400**.
- `moments_calendar(region)` is the authoritative slug vocabulary — a wrong slug is
  a 400, not an empty result.

---

## 7. Timing rejects; it does not select

Timing is gate 4 of 5 in `finding-winners`. It can only **reject a survivor** — a
term that clears winnability, intent and margin can still be too late to build rank
into. It can never promote a term that failed an earlier gate just because the
window is open.

---

## Anti-patterns

- Defaulting a missing takeoff to "soon", or a missing peak to "passed"
- Reading the deadline without the peak
- Judging a season on the last `chart_series` bucket
- Guessing a peak month instead of reading the curve (`mom necklace` → December)
- Hiding a dated moment because nothing is pointed at it
- Sorting a moment's terms by volume
- Reading the moment curve forward off the raw wire
- Treating a region's null dates as "no moment"
