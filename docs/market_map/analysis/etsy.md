# Analysis — Etsy (what its two tiers are worth)

Etsy is where demand is REALISED — the search box, the sale, the review. Where Pinterest
leads, Etsy confirms. It answers the two questions that decide a launch: *is there real
money here, and can I get a piece of it.*

Reference: `../reference/etsy_private.md`, `../reference/etsy_public.md`.

---

## Private tier — demand truth (the scarce asset)

The seller tool is the only source of **real numbers**: true search volume, true
conversion rate, the true seasonal cycle. Everything else in the system estimates; this
measures.

**What it's worth:**
- **Volume × CVR** = real weekly demand for the MARKET (never confuse with your share —
  see combinations). The denominator every winnability call needs.
- **The seasonal cycle** (`chart-series`) = *when* a term peaks, from Etsy alone. "mom
  necklace" peaks Nov–Dec and April. This is the calendar's engine and it needs no
  Pinterest — and it now actually runs the calendar (`etsy.engines.calendar_engine`,
  built 2026-08-19); this was theoretical as of the last version of this doc.
- **`daily_stats`**, riding free on every `results-data` call — a day-by-day search
  volume series with a rolling average, sharper timing than the monthly cycle above.
  Found 2026-08-27, not yet wired into anything. See `reference/etsy_private.md`.
- **The keyword tree** (`get_similar_keywords`) = one seed → 165 long-tail terms, each
  sized. This is the discovery engine — Etsy's own algorithm mapping the neighbourhood.
- **20 competitor cards free** in every demand call — a head start on the SERP.

**The discipline:** this authenticates as the operator's OWN shop. Spend it LAST, only on
what already looks worth it after free discovery and public qualification (D-29). A hunt
that runs results-data on 100 raw ideas wastes the one irreplaceable account.

---

## Public tier — competition truth (unlimited, safe)

The buyer-session view of the marketplace: who ranks, what they tag, how they position.

**What it's worth:**
- **Winnability's denominator** — how many listings actually compete, from the SERP.
- **The blueprint's raw material** — 13 tags per page-one listing, the exact words that
  rank. Plus the category path (where to file it) and the product type (how to cost it).
- **Competitor outcomes over time** — review velocity per listing = validated winners,
  caught early. The ONE unbiased outcome dataset (a competitor's launches are independent
  of our model — the fix for LEARN self-selection, B-04).

**The discipline:** everything about competitors lives here. Never spend the seller
account to learn something a buyer session can see.

---

## The two Etsy questions, and which tier answers each

| Question | Tier |
|---|---|
| Is there real demand? How much, converting how well? | private (`results-data`) |
| When does it peak? | private (`chart-series`) |
| What related terms exist, and how big? | private (`similar_keywords`) |
| Who am I competing with? How many? | public (SERP) |
| What do the winners tag / title / charge? | public (`listing_data`) |
| Which category, which product type? | public (`listing_data`) |
| Did a competitor's launch actually work? | public (shop + review velocity over time) |

---

## What Etsy is NOT good for
- **Lead time.** Etsy is coincident — by the time a term is hot in its search box, the
  SERP is crowded. Pinterest sees it forming earlier.
- **Audience.** Etsy does not tell you the age/gender/intent behind a search. Pinterest
  does.

That is precisely why the two combine — next file.
