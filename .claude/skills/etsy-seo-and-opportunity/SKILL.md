---
name: etsy-seo-and-opportunity
description: Use when ranking, scoring, recommending, or surfacing keywords, niches, listings or candidates to the operator — any code or UI that decides WHICH opportunity to show first, or that touches Etsy search ranking, tags, titles, CTR, conversion or competitiveness. Enforces winnability over market size, naming the funnel stage a metric belongs to, and refusing to recommend what this shop cannot rank for.
---

# Etsy SEO & Opportunity

The other half of being right. `etsy-pipeline-work` makes sure a number is **true**;
this makes sure it is the **right number to show first**.

Both failures cost the operator a wasted launch. Only one of them looks like a bug.

---

## The mistake this exists to prevent

`discover.py` shipped sorting candidates by **search volume**. Every number in it was
correct, provenance-tagged and honest. It was still wrong:

| Term | Volume | Supply | Demand/supply | CVR |
|---|---|---|---|---|
| `home decor` — ranked **1st** | 310,467 | 2,160,627 | 0.14 | 0.00005 |
| `backpack name tag` — ranked **17th** | 69,874 | **25,031** | **2.79** | **0.00279** |

`backpack name tag` has **19× the demand per listing** and **56× the conversion rate**.
It was buried under three terms this shop can never rank for.

**Market size is not opportunity.** A term with two million listings is not a chance,
it is a wall. Sorting by volume optimises for the wrong operator — one who already
ranks.

---

## Rule 1 — Rank by winnability, never by volume

A candidate is worth showing when the operator could plausibly **reach page one**, not
when the market is large. At minimum combine:

```
demand per listing   volume / supply      ← the single most useful ratio here
conversion           query_cvr            ← intent, not just traffic
competition quality  survivor bound, review counts, star-seller density
recency of supply    can a new listing still enter the top rows?
```

Report the ratio, not just the rank. `2.79 demand per listing` is inspectable;
`opportunity score 87` is not.

**Never present a head term as an opportunity to a small shop.** If the only honest
answer is "you cannot rank here", that is the answer — the same refusal discipline as
the profit gate, applied to visibility instead of margin.

---

## Rule 2 — Say which funnel stage a number describes

Etsy's funnel is `impressions → clicks → favourites → orders`. Most metrics here live
at exactly one stage, and mixing them silently is how a listing gets "optimised" at the
wrong step:

| Signal | Stage | What it can and cannot explain |
|---|---|---|
| search volume | impressions | how many could see it — never how many will buy |
| tags / title | impressions | they win the *impression*, not the click |
| photo, price, review count | **clicks** | the biggest lever, and the one this repo measures least |
| `query_cvr` | orders | intent of the term, not the quality of the listing |
| review velocity | orders | outcome, lagging, the most trustworthy |

**Tags do not sell.** Tags earn an impression; the photo and price earn the click.
Recommending tag changes for a listing with a click problem is confident, cheap, and
useless.

---

## Rule 3 — Long tail is the strategy, not a consolation

For a shop without ranking authority, a 2,000-volume term with 3,000 listings beats a
300,000-volume term with 2,000,000. Prefer specific over broad, and say why:

* specific terms carry **higher intent** and convert better
* they are **winnable now**, not after a year of authority
* several long-tail wins compound into authority for the head term later

When a niche is genuinely too small to matter, say that too — `PoolTooSmall` exists for
this reason. Winnable and worthwhile are different tests and both must pass.

---

## Rule 4 — Separate what the market does from what THIS shop can do

The system knows a great deal about the market and almost nothing about the operator's
capacity, style, price point or authority. Two consequences:

* market demand is **never** the operator's demand (`opportunity.py` keeps these apart
  deliberately — do not collapse them)
* a recommendation must fit what the operator can actually make. The product profile in
  Settings is that constraint, and for personalized goods the labour minutes are the
  ceiling that usually binds

If a recommendation would require capability the system has never been told about, say
what it assumes rather than assuming silently.

---

## Rule 5 — Curated lists carry someone else's agenda

`trending-search-terms-v2` returns **Etsy's picks**, by criteria Etsy does not publish.
Every candidate from it carries `basis="etsy_curated"`, and it must never be presented
as "what is trending" — only as "what Etsy is promoting".

This is B-01 applied to candidate generation instead of survivors: the sample was
chosen by someone with different incentives, and inheriting it uncritically imports
those incentives as market truth.

---

## Rule 6 — n is small; say so

Two tracked shops, 76 listings, a handful of keyword rows. Almost nothing here is yet
statistically meaningful, and the honest posture is to show the sample size beside the
claim rather than to stop.

Before presenting any aggregate: how many observations, over how long, and would one
more change the answer? If yes, it is an anecdote — label it one.

**Put a number on it rather than a warning.** Etsy renders 12 SERP slots and about
half are ads, so a saturation share is measured on 6–11 listings. At n=6 the 95%
interval spans roughly ±35 points — wide enough to cover both the "thin" (5%) and
"crowded" (30%) thresholds at once, which means the sample cannot tell them apart.

`card_saturation` attaches that interval and **withholds** any bracket whose bounds
straddle a threshold (D-36). The case worth remembering:

> **0 out of 6 does not establish an empty bracket** — the true share could still be
> 39%. The oldest trap in this system (D-10: read 0% saturation as a loophole) is
> now caught by arithmetic before any rule has to fire.

So: never present a share from a page-one sample as a market share, and never let a
point estimate travel without its sample size. "33% offer free shipping" from two
hits in six is precisely the well-formed wrong number this repo is named after.

---

## Anti-patterns

- Sorting a recommendation list by volume
- A composite "opportunity score" with no inspectable inputs
- Tag advice for a listing whose problem is the photo or the price
- Treating marketplace demand as the operator's demand
- Presenting a curated list as an objective market view
- Any recommendation that does not survive "could this shop actually rank here?"
