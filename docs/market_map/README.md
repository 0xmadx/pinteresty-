# Market Map — the shared knowledge base

The one place the three roles meet. Built so the operator (CEO), the engineer (Claude),
and the analyst lens are all looking at the same verified picture instead of
rediscovering the data surface by accident.

## The two folders

| Folder | Question it answers | Who leans on it |
|---|---|---|
| **`reference/`** | *What does this endpoint DO — exact params, payloads, what it returns, verified or not* | engineer + analyst |
| **`analysis/`** | *What is it WORTH — what a seller does with it, and how the sources combine* | CEO + analyst |

`reference/` is the wire truth. `analysis/` is the meaning. Neither is allowed to drift
from the other: an analysis claim must point at a `reference/` fact, and a `reference/`
fact carries a ✅/⚠️/❓ verification mark so no analysis is ever built on a hope.

## The files

```
reference/
  pinterest.md       every Pinterest page/tab, endpoint, ALL params, payload, verified
  etsy_private.md    the seller tool — demand truth (volume, CVR, cycle, keyword tree)
  etsy_public.md     competitor truth (SERP, listings, tags, product type)

analysis/
  pinterest.md       what Pinterest's data is worth, page by page
  etsy.md            what Etsy's two tiers are worth
  combinations.md    THE POINT — how the three sources join into an edge no one source has
```

## The one mental model (everything traces to this)

**Private = demand truth · Public = competition truth · Pinterest = audience truth.**

Each platform owns a question the other two cannot answer. See `analysis/combinations.md`
for how they compound.

## The three roles (from the `etsy-market-intelligence` skill)

| Role | Owns | Never |
|---|---|---|
| **Operator / CEO** | what to sell, real costs, which competitors matter, confirm/kill a direction | writes code, or supplies a number the machine can measure |
| **Engineer** (Claude) | build it, verify endpoints live, keep the guards, report honestly | decides product direction, or invents a number |
| **Analyst lens** | which data is worth gathering and what it means | overrides a measured number with an opinion |

When two disagree about a number, **the wire settles it — probe, do not argue.** This
whole folder is the record of those probes.

## Verification legend

✅ verified live (date) · ⚠️ wired but returned empty/None when probed · ❓ never probed ·
❌ confirmed dead. Every endpoint carries one.

## Relationship to the rest of docs

- `docs/architecture/11_endpoint_reference.md` — the one-page summary; this folder is the
  full version it points to.
- `docs/architecture/09_build_plan.md` — what we build with all this.
- `.claude/skills/etsy-market-intelligence` — the discipline for USING it.
