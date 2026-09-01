---
name: etsy-market-intelligence
description: Use when deciding WHICH data to gather, from which platform, and what it is worth to a seller — the marketer/analyst lens over the three data sources. Covers the discovery→analysis→value chain, which platform owns which question, what to store for compounding value, and the roles (engineer builds, operator confirms). Trigger when planning a data-gathering feature, evaluating a new endpoint's value, designing what to store, or asking "is this signal worth building on".
---

# Etsy Market Intelligence

The third lens. `etsy-pipeline-work` asks *is the number true*; `etsy-seo-and-opportunity`
asks *is it the right number to show first*; this asks **is it worth gathering at all,
and what does a seller DO with it.**

The other two keep you honest and sharp. This one keeps you pointed at value — so the
machine gathers what compounds into an edge, not what is merely easy to scrape.

The reference for what each endpoint returns is `docs/architecture/11_endpoint_reference.md`.
This skill is how to THINK about that surface as a market analyst.

---

## The one mental model

**Private = demand truth. Public = competition truth. Pinterest = audience truth.**

Each platform owns a question the other two cannot answer. Gathering is a question of
*which truth do I need*, never *which endpoint is handy*.

| To learn… | Ask… | Because |
|---|---|---|
| is there real demand, and when does it peak | **Etsy Private** | only the seller tool has true volume, CVR, and the 12-month cycle |
| who am I up against, and how do they rank | **Etsy Public** | competitor listings, tags, SERP — all public, never risk the seller account |
| who wants this, and are they buyers or dreamers | **Pinterest** | demographics + click-vs-save intent, which Etsy has at no price |

If a feature would answer its question from the wrong platform, it is wrong — most
often it burns the seller account (D-29) to learn something public could tell it.

---

## The value chain — gather in this order, and why

The order is not arbitrary. Each stage narrows the field so the *expensive, scarce*
calls (private, seller-account) are spent only on what already looks worth it.

```
1 DISCOVER (cheap, wide)     Pinterest trends/shopping/spotlight · Etsy trending · seed crawl
2 QUALIFY  (public, free)    SERP: real competition, tags, product type, category
3 MEASURE  (private, scarce) results-data: true volume/CVR/price · chart-series: the cycle
4 VALUE    (local)           winnability × profit gate × timing → is it worth listing
5 STORE    (append-only)     everything, with provenance and a timestamp
```

**Spend scarce calls last.** Discovery is free and wide; the private measure is the
scarce truth. A hunt that runs results-data on 100 raw ideas wastes the one tier that
authenticates as the seller. A hunt that discovers 100, qualifies to 20 on public data,
and measures those 20 privately is the same answer for a fifth of the risk.

---

## What to STORE — the compounding asset

The product is not a single answer; it is a **growing map of the market** that gets
faster and sharper the more it runs (the flywheel). Store to compound:

| Store | From | Why it compounds |
|---|---|---|
| the keyword graph (term → children, sized) | seed crawl | a second crawl reuses sized nodes; the tree is the moat |
| the taxonomy tree (real categories seen) | breadcrumbs | replaces guessing taxonomy_id integers |
| every demand reading, timestamped | results-data | a second reading a month later IS the trend |
| competitor listings over time | public SERP + shop | review velocity = validated winners, the unbiased outcome set |
| seasonal cycles | chart-series | last year's cycle predicts this year's list-by date |

**Store the boring readings too.** A term that measured badly is still a real
observation, and the value of the whole system is time-series — a single reading is a
level, not a trend. Never discard a measurement because it was disappointing.

⚠️ **Provenance travels with every stored value** (measured / derived / default /
etsy_curated). A number whose origin is lost is a number that will be trusted more than
it deserves — the failure this whole system exists to prevent.

---

## The rulings that keep gathering disciplined

**Alphabet Soup is not needed** on Etsy or Pinterest. Appending a–z to a seed to harvest
autocomplete is what you do with only a dumb search box. Both platforms have native
recursive keyword trees that return *semantic* neighbours *already sized* —
`get_similar_keywords` (Etsy, ~165 with volume+supply) and `related_terms`/`prefix_match`
(Pinterest, with momentum). Alphabet Soup would be a strictly worse substitute for what
already exists.

**Curated lists carry someone else's agenda.** Etsy's trending terms and Pinterest's
spotlight are what those platforms chose to promote, by criteria they do not publish.
Gather them, but tag `etsy_curated` and never present them as objective market truth
(B-01 at the point of discovery).

**A signal is worth building on only when it is verified to return data.** The endpoint
reference marks each ✅/⚠️/❓. Building on a ❓ or ⚠️ signal (e.g. Pinterest demographics,
which probed empty) is building on a hope. Probe first; the reference is the record.

---

## Who does what (the roles)

This system has three seats, and confusing them wastes everyone's time:

| Role | Owns | Does NOT |
|---|---|---|
| **Operator / CEO** (the human) | what to sell, real costs, which competitors matter, confirm/kill a direction | write code, or supply numbers the machine can measure itself |
| **Engineer** (Claude, here) | build it, verify endpoints live, keep the guards, report honestly | decide product direction, or invent a cost/number to fill a gap |
| **The analyst lens** (this skill) | which data is worth gathering and what it means | override a measured number with an opinion |

The operator confirms direction and supplies only what cannot be measured (costs,
capacity, which shops to watch). The engineer builds and never fabricates a number to
move past an edge case. When the two disagree about a number, the wire settles it —
probe, do not argue.

---

## Anti-patterns

- Spending a private (seller-account) call to learn something public could answer
- Gathering a curated list and calling it "the market"
- Building on an endpoint the reference marks ⚠️/❓ without probing it first
- Discarding a disappointing measurement instead of storing it as a real reading
- Alphabet-Soup keyword harvesting when the native keyword tree exists
- Storing a number without its provenance
