# GOAL — what this is for

*The north star. Every design decision traces back to something here. When a
choice is unclear, this document decides it.*

---

## The one-line goal (decided 2026-08-12)

> **A weekly calendar that says what to list, when to list it, and whether it will
> make money — with a keyword search as the second door.**

Not a niche checker. Every competitor is a niche checker; the calendar is the part
they cannot build, because it needs Pinterest's takeoff dates joined to Etsy's real
demand and a profit model willing to say no.

| | Decision | Ref |
|---|---|---|
| Home screen | **Calendar first**, search always in the top bar | D-20 |
| Channels | **Etsy only for now**, data model stays channel-aware | D-21 |
| Product types | **All three** — and the type is **detected**, not assumed | D-22 |
| Fees & costs | **Settings ships first**; nothing hardcoded | D-23 |

The three questions it answers, in order — **what**, **when**, **whether it pays** —
then it checks itself: did the prediction hold? See `architecture/09_build_plan.md`.

---

## Who

A single operator running their **own Etsy shops**. Sells a mix:

- **Digital** (printables, downloads) — no COGS, no shipping, infinite scale
- **Physical** — real goods, real shipping, supplier-capped
- **Personalized physical** — premium price, thin competition, **capped by their
  own hands**

Not a SaaS today. Possibly a SaaS later — the architecture allows it, but every
choice is made for one operator first.

---

## The problem being solved

Picking what to sell on Etsy is guesswork. The operator has three data sources that
each know something the others don't, and no way to combine them into a decision:

- **Pinterest** knows what's *becoming* popular (momentum, audience, aesthetic
  demand) but only in relative terms — no absolute numbers.
- **Etsy Private** knows what's *actually searched and bought* (volume, CVR, real
  prices, and the top competitor listings in the same response). Believed metered;
  no limit has ever been observed (D-14).
- **Etsy Public** knows *who you'd be fighting* (supply, competitor quality,
  reviews, tags) but its sales figures are estimates, not measurements.

Separately they're trivia. Combined, they answer a real question.

---

## What the machine must do

**Two decisions, per product idea:**

1. **Should I make this?** — score the opportunity with **profit at the center**,
   find the gap where competition is thin, and say go or no-go *per product type*
   (the same keyword can be a yes as a digital printable and a no as a personalized
   physical).
2. **Where do I sell it?** — Etsy (free search traffic, high fees), Shopify (own
   the margin and the customer, but bring your own traffic), or a Pinterest shop.
   The answer depends on whether demand is **searched-for** or **discovered**.

**Two halves, four modes:**

- **Outward — FIND & JUDGE:** what should I make, and can I win there?
- **Inward — OPERATE & LEARN:** how are my own shops doing, and *was the machine
  right?*

The inward half is what makes it compound. Without it, it's a recommendation
engine that never learns.

---

## Success looks like

| | Success | Failure |
|---|---|---|
| **Decision** | "Make this as a digital printable, list on Etsy, launch by Sept 12, beat these 3 flaws" | a dashboard of charts the operator still has to interpret |
| **Profit** | verdicts driven by margin after fees, COGS, and labor | ranking by revenue and losing money on winners |
| **Honesty** | every number labeled measured or derived; low-confidence says so | a plausible wrong number that looks authoritative |
| **Learning** | after 10 launches, the weights are fitted to real outcomes | predictions never checked |
| **Timing** | launch dates computed per term, type-aware (physical adds supplier lead) | "launch 6 weeks before peak" applied blindly to everything |

---

## Non-goals (explicitly out of scope)

- **Not a general SEO tool.** It serves this operator's shops.
- **Not real-time.** Weekly batches are correct; nothing needs streaming.
- **Not multi-user today.** One operator. SaaS is a later evolution, not a
  current requirement.
- **Not a scraper improvement project.** The data-access layer is treated as an
  input. This project is the analysis and decision system built on top.
- **Not an AI product yet.** But data is captured today so a model is possible
  later (frozen feature vectors + real outcomes = a training set).

---

## The constraints that shape every design choice

1. ~~**Etsy Private quota is the scarce resource**~~ — **superseded, see D-14.**
   No quota was ever observed: no counter, no 429, and the two code comments claiming
   a cost contradicted each other. The operator tested the endpoint directly and found
   no limit. The scarce resource is **unused surface**, not API budget — the system
   reached a fraction of the parameters, filters and endpoints available to it
   (`08_capability_map.md`). The architecture is now *crawl wide everywhere and join
   the three sources*, not *ration the metered call*.
   The detection remains (`SessionManager.rate_limited`) so a real limit would
   announce itself rather than be absorbed as a session error, which is how the
   original belief survived unexamined.
2. **The failure mode is a plausible wrong number, not a crash.** Every guard in
   the system exists to prevent one. This is why measured-vs-derived tagging,
   sentinel clamping, and the `noisy` flag are non-negotiable.
3. **Time can't be retrofitted.** Predictions must snapshot their inputs, and
   time-varying values must never be overwritten — or the learning loop is a lie.
4. **The scale is small.** Megabytes, one user, weekly batches. Every "big data"
   tool is wrong here. Embedded stores, in-process compute, one container.
5. **Sources must be swappable.** Prototyping on one data source today, official
   or commercial APIs later. Nothing above the adapter may know where data came
   from.

---

## Why "profit, not revenue" is the central idea

The original architecture estimated revenue and treated a big number as a win. It
had **no cost input anywhere**. That's the flaw that made everything else
untrustworthy, because:

- a digital product at $6 with ~97% margin can beat a physical at $38 with 30%;
- a personalized product with great margin is worthless if it needs 40
  made-to-order units a week and the operator has time for 15;
- the highest-revenue option in a real three-way comparison was a **no-go** on
  margin.

**Revenue ranks the wrong things.** Profit — after Etsy fees, COGS, shipping, and
the operator's own labor — ranks the right ones. Everything else in the system
feeds that.

---

## The one-line test

> Does this change help the operator decide **what to make and where to sell it**,
> with an honest number attached?

If yes, build it. If no, it's a feature looking for a justification.
