# Reference — Printify

**Cost truth, not demand truth.** `etsy/api/printify/client.py`. Sits at the END of
the funnel — the analysis decides *what* to make; Printify answers *what it costs to
make it*. Never a source of demand signal, never called to discover a niche.

**This platform had no reference doc before 2026-08-27** despite being a full third
API client, added 2026-08-19, central to POD costing (D-46) and the `pod_quote` /
`pod_check` MCP tooling. Written to the same standard as the other two.

Legend: ✅ verified live · ❌ confirmed absent from this API.

---

## Auth
`Authorization: Bearer {PRINTIFY_API_TOKEN}` — the token lives in `.env` (untracked).
**No unauthenticated fallback, on purpose**: a silent 401 would look like an empty
catalog rather than a missing token. `RATE_LIMIT_PER_MINUTE = 600` is Printify's
documented ceiling, recorded for whoever sizes a future sweep.

The token carries `products.write` and `orders.write`. **Nothing in this client uses
them** — every method is a `GET`. Creating a product to read its cost would be an
account modification and is explicitly the operator's call, never this module's.

---

## `blueprints()` ✅ verified 2026-08-19
`GET /catalog/blueprints.json` — the full catalog. **2,059 products** at last count.
No filtering server-side; the whole list comes back in one call.

## `print_providers(blueprint_id)` ✅
`GET /catalog/blueprints/{id}/print_providers.json` — who can actually make one
given blueprint. A blueprint can have several providers with different prices,
locations and lead times; this is what makes provider choice a real decision rather
than a fixed cost.

## `variants(blueprint_id, provider_id)` ✅
`GET /catalog/blueprints/{id}/print_providers/{pid}/variants.json` → `.variants`.
Sizes, colours, print areas for one blueprint+provider pair. **No price field on a
catalog variant** — see below, this is the whole reason `pod_costing` treats COGS as
operator-confirmed rather than computed.

## `shipping(blueprint_id, provider_id)` ✅
`GET /catalog/blueprints/{id}/print_providers/{pid}/shipping.json` — per-country cost
and **handling time**. The one genuinely load-bearing field for timing decisions:
Printify handling is measured at **10 days on every towel provider**, so a 7-day
Etsy delivery-speed bracket is structurally closed to POD regardless of price —
this is a fact `shipping()` supplies directly, no separate lookup needed.

## `shops()` ✅
`GET /shops.json` — the operator's connected Printify shops. Account-level, not
catalog-level; exists mainly as a sanity check that the token is live.

---

## What this API does NOT give — the important half

**No production cost, anywhere in the catalog.** `cost` exists only on a *product*
object — i.e. after something has been created inside a shop. There is no
`blueprint_cost()` and one must not be invented: COGS enters this system as an
**operator-confirmed number** (D-27 — no figure the operator has not confirmed is
treated as fact), and `pod_costing` keeps it `None` until supplied rather than
defaulting to something plausible.

**The Premium-subscription discount cannot be read from the catalog either** — same
shape as cost: it only shows up on created products.

**v2 catalog endpoints 404 on a personal access token.** Only v1 is reachable this
way; not investigated further since v1 covers everything this project needs.

---

## What this platform is worth, and where it fits

`pod_check.py` / `/pod` (D-46) prices the POD margin ceiling off **page-one actual
prices**, not the private API's market-wide median band — measured roughly 2× higher
($25.19 vs $11.70–$14.30 on one term) and the difference is the gap between "POD
looks impossible" and "POD looks plausible." Printify never asserts "profitable" —
it hands back a COGS ceiling plus a handoff, because it structurally cannot know the
supplier's real price.

**The discipline:** Printify is read-only here and stays that way. It answers
*can this be made, by whom, shipped how fast, at what shipping cost* — never *should
this be made* (that is the profit gate) and never *is anyone searching for this*
(that is Etsy Private).
