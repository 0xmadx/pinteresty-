# Analysis — Pinterest (what it's worth)

The audience layer. Pinterest is where demand is FORMED before it reaches Etsy's search
box — people plan on Pinterest weeks before they buy on Etsy. That lead time is the
whole value: it is a **leading indicator** where Etsy is a **coincident** one.

Reference for exact fields: `../reference/pinterest.md`.

---

## What each page is worth to a seller

### Search trends — the wide seed net
Hundreds of rising keywords, each pre-sized with momentum at three timescales. Value is
in the **preset** and the **filters**:

- `seasonal` preset = *what is spiking THIS week* → the timing edge
- `Age`/`Gender` filters = *who is searching it* → `male` and `female` return dramatically
  different worlds (wallpaper/anime vs nails/outfits). This is audience truth Etsy has at
  no price.
- `Moments` filter = *tie a keyword set to a holiday* → and it shares a vocabulary with
  the calendar (see combinations).

**Use it for:** bulk discovery seeds, filtered to a timely, specific audience.

### Trends in the Spotlight — the curated few
5 hand-picked trends, each with keyword seeds + a momentum curve. Small but high-signal —
Pinterest's humans chose these as the story of the week. SAVE-ranked = what is *catching
the eye* (aspiration), not yet what is *bought*.

**Use it for:** a handful of pre-vetted, editorially-blessed seeds. Feed the
`related_search_trends` into the crawl.

### Shopping trends — the intent filter
Category-level momentum PLUS the click-vs-save split. This is Pinterest's one
irreplaceable claim:

- **OUTBOUND_CLICK** = people who clicked THROUGH to buy → purchase intent
- **SAVE** = people who bookmarked a dream → aspiration

The gap between them separates *buyers* from *dreamers*. Nothing on Etsy can tell you
this. A trend high in SAVE but low in OUTBOUND_CLICK is a daydream; one high in
OUTBOUND_CLICK is money moving.

**Use it for:** the buyer-intent gate on a discovered niche.

### Reading the Shopping trends page as a marketer, not a scraper
The wire is fully mapped (`reference/pinterest.md`, `pinterest/endpoints/`) — this is what
it's worth once you're looking at it.

- **The sort toggle IS the D-31 trap, built into the page.** `order_by` is either
  `RELATIVE_VOLUME` (biggest category right now) or `PCT_CHANGE_MOM` (fastest-growing).
  Defaulting to volume reproduces the exact mistake `discover` made ranking `home decor`
  #1 — a category can be huge and saturated. **Default this page to growth, never volume**,
  same discipline as everywhere else in the system.
- **`related_search_trends` (25 terms per category, free in the same call) is a discovery
  engine, not a footnote.** A seller does not care that "Sweatshirts" is +23% MoM in the
  abstract — they care that the 25 seeds attached to it are `zip hoodie`, `patchwork
  hoodie ideas`, `graphic hoodie`, etc. The category ranking is the filter; the seed list
  is the payload. Feed these straight into the Etsy seed crawl (JOIN 2) rather than typing
  keywords by hand.
- **The three summaries in one row (`saves`/`outbound_clicks`/`engagement`) are the intent
  gate for free.** `local_math.intent_ratio()` already derives clicks-growth ÷ saves-growth
  from a single `event=OUTBOUND_CLICK` call — no need to also fetch `event=SAVE`. A
  category high in outbound-click growth but flat on saves is people buying without
  browsing first; the reverse is a mood board. This is JOIN 3, and it costs nothing extra.
- **Age/Gender here slice REAL demand, not a display filter.** Unlike some Pinterest
  demographic surfaces, `category_metrics()` genuinely recomputes the curve per age/gender
  bucket — so "Coats & jackets, female, 25-34" is a real different number, not the same
  chart with a label. Worth combining with the Search-trends `/demographics/` per-keyword
  breakdown (JOIN 4) once a category has been narrowed to specific seed terms.
- **What a seller does NOT get here**: price, margin, or how many Etsy competitors already
  own this category. This page answers "is this category worth looking at," never "can I
  win it" — that's still public-tier Etsy work, after this page narrows the field.

---

## The three signals Etsy cannot give at any price

1. **Lead time.** Pinterest momentum precedes Etsy search — see it rising here before it
   is crowded there.
2. **Demographics.** Age/gender per keyword (via Search filters — the `demographics`
   endpoint itself returned empty, so use the filters). Who wants it.
3. **Purchase intent.** Click-vs-save. Are they buyers or dreamers.

---

## What Pinterest is NOT good for
- **Competition.** It has no idea how many Etsy listings compete for a term. That is
  public-tier truth. A term can be red-hot on Pinterest and a wall on Etsy.
- **Profit.** No prices, no fees. Pinterest tells you desire, never margin.
- **Reliability of some endpoints.** `demographics` and `metrics` returned empty/None on
  probe. Use the Search-trends filters for demographics; do not build on the standalone
  endpoints until they prove out.

---

## The honest caveat (bias-aware)
Pinterest's curated surfaces (Spotlight, and to a degree the trending presets) are what
Pinterest chose to promote, by criteria it does not publish. Treat curated lists as
*"what Pinterest is pushing"*, tag them, and never as objective market truth (B-01 at the
point of discovery).
