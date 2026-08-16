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
