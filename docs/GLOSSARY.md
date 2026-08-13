# GLOSSARY

Terms used consistently across every document. When a doc uses one of these, it
means exactly this.

---

## The four modes

| Term | Meaning |
|---|---|
| **FIND** | Discover candidate niches. Outward. Pinterest-led, free, wide. |
| **JUDGE** | Decide whether to compete and where. Outward. Scoring + gap + platform. |
| **OPERATE** | Watch the operator's own shops and listings. Inward. |
| **LEARN** | Check whether predictions were right; tune the weights. The loop. |

## The three sources

| Term | Authoritative for | Never trust for |
|---|---|---|
| **Pinterest** | momentum, seasonality, audience, click/save intent, holiday timing | absolute magnitude (all 0–100 indices) |
| **Etsy Private** | search volume, true CVR, price buyers pay | supply; it's **metered** |
| **Etsy Public** | supply count, competitor quality, tags, reviews, cart intent | its sales/views are *derived* unless a daily-sales badge exists |

## The guards (non-negotiable)

| Term | Meaning |
|---|---|
| **Measured vs derived** | Whether a number was observed or computed. Tagged on every stored value (`cvr_source`, `sales_source`, `profit_source`). |
| **Sentinel** | A capped placeholder posing as a number: `100.01` (Pinterest "10,000%+"), "20+ in cart", "Only 3 left". **Clamp; never average.** |
| **`noisy`** | A Pinterest term whose recent series never exceeds 25 on the 0–100 scale. Produces fake +900% velocities. Must survive the join to the scorer. |
| **`collected_at`** | When a value was fetched. On every row. Stale data looks identical to fresh data without it. |
| **`freshness_floor`** | The *oldest* `collected_at` among a derived record's inputs. A score is only as fresh as its stalest ingredient. |
| **Confidence gate** | A score is only as trustworthy as its weakest input. Defaulted CVR or noisy momentum → low-confidence, flagged, never a clean number. |
| **Empty-bracket trap** | A 0% competition bracket usually means *nobody wants it*, not that a loophole was found. Demand must be shown to hold inside the bracket. |

## Scoring & profit

| Term | Meaning |
|---|---|
| **Percentile rank** | Each variable converted to its rank within the candidate pool (0–1) before weighting. Fixes the incompatible-units bug. |
| **`pool_id` / `pool_size`** | Which pool a score was computed in. #1 of 5 ≠ #1 of 500; a percentile score is meaningless without it. |
| **SERP strength** | How hard the top-10 competitors are to beat (review counts, badges). A cost variable — subtracts from the score. |
| **Intent ratio** | Pinterest clicks ÷ saves. High = purchase intent. High saves, low clicks = aspiration, won't convert. |
| **Margin floor** | The per-type minimum margin below which a niche is a no-go regardless of demand: digital 70%, physical 35%, personalized 50%. |
| **Labor cap** | For personalized products, the ceiling on units/week set by the operator's own hands. Demand above it isn't opportunity. |
| **CAC** | Customer acquisition cost — what it costs to get one visitor. ~0 for organic Pinterest traffic; the hinge of the Shopify-vs-Etsy decision. |

## Architecture

| Term | Meaning |
|---|---|
| **Bronze / Silver / Gold** | Medallion layers: raw immutable → cleaned + guards applied → derived and disposable. |
| **The guard boundary** | The Bronze→Silver transform. The single place sentinels are clamped, `noisy` set, freshness stamped. One place to audit. |
| **Source adapter** | The one layer that knows a provider exists. Emits a normalized record so everything above is source-blind. |
| **Append-only / SCD Type 2** | Time-varying values get a new row, never an overwrite. What makes LEARN honest. |
| **Point-in-time correctness** | Evaluating a prediction against the inputs *as they were when it was made* — not current values. Requires frozen snapshots. |
| **Budget allocator** | Token bucket + priority queue that decides which candidates get metered Etsy calls. |
| **Local derivation** | Computing a value from data already fetched instead of making a request. The cheapest call is the one never made. |

## Product

| Term | Meaning |
|---|---|
| **The 7 dimensions** | Geographic, Format, Quality, Feature, Occasion, Colour, Shipping speed — the axes the gap-finder slices. **Not all apply to all product types** (shipping is meaningless for digital). |
| **Gap bracket** | The specific filter combination where supply collapses while demand holds. Becomes the product's positioning. |
| **Searched-for vs discovered** | Etsy demand = someone typed it (→ Etsy). Pinterest demand = someone saw it (→ Shopify/Pinterest). Decides the platform. |
| **Two front doors** | Input is either a **keyword** (discovery mode) or a **listing URL** (X-ray mode, which yields 13 candidate keywords). |
| **Failure mode** (LEARN) | Why a launch failed: wrong niche / SEO / timing / price / product. Uncategorized failure teaches nothing. |
| **Estimate error ratio** | actual ÷ predicted. Its median is the system's systematic bias — the highest-value number LEARN produces. |
