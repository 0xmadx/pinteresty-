---
name: web-surface-mapping
description: Use when mapping a website's real capability through a logged-in browser — finding every page, filter, endpoint, parameter and payload a marketing/SEO tool actually exposes, and what each is worth to a seller. Trigger when the operator says "map this site", "what does this tool do", "find the endpoints", "use my browser", or when a data source's true surface is unknown and probing the API alone has missed things.
---

# Web Surface Mapping

Map a marketing tool the way an SEO hunter does: **click every control, watch every
request, and write down what each is worth.** Not "what does this API return" — *what
can a seller learn here that they cannot learn anywhere else.*

Use with the Chrome extension (`mcp__claude-in-chrome__*`) against the operator's own
logged-in browser. Their session is the point: these tools show nothing useful logged
out, and the whole surface is invisible from the API alone.

---

## Why this exists

Probing endpoints in isolation misses things — verified, repeatedly, on this project:

* An entire tab was missed because nothing in the code named it.
* Filters were called "not supported" when they 500'd from the **wrong value format**
  (`gender=female` fails, `gender=1` works). The feature was there all along.
* A number displayed as "300% MoM" is stored as `3` — a **×100 display scaling** that
  would have been reported 100× too small.
* The most valuable signal on a page was the one the API buried and the UI led with.

The UI is the specification. The API is the implementation. When they disagree, the UI
tells you what the tool is *for*.

---

## The method

### 1. Inventory the surface before touching anything
Screenshot every page and tab. List: pages → sections → controls (filters, toggles,
sorts, dropdowns, date pickers). Do not click yet. You are building a map of *what
exists*, so nothing is missed later because it was never seen.

Ask of each screen: **what decision is this screen for?** A tool's layout is its
designers' theory of the user's workflow — the order and prominence of panels tells you
what the vendor thinks matters most.

### 2. Read the page as a marketer, not a scraper
Before the network tab, look at what a human sees:

* **What is the headline metric?** The one the UI leads with is the one the vendor
  believes drives decisions. (A tool leading with "outbound clicks" over "saves" is
  telling you purchase intent is the point.)
* **What is shown as a shape, not a number?** Sparklines, phase badges ("Rising",
  "Approaching"), colour coding. These encode judgements the raw API only hints at.
* **What is visual/qualitative?** Thumbnails, example images, editorial copy. A trend is
  often an *aesthetic*, not a keyword — no endpoint returns that, and it changes what a
  seller makes.
* **What is adjacent?** Panels placed together are meant to be read together. That
  adjacency is a join the vendor is suggesting.

### 3. Then exercise every control with the network tab open
For each filter/toggle, one at a time:

1. note the request BEFORE
2. apply the control
3. capture the request AFTER
4. record: **param name · exact wire format · what changed in the response**

**Capture the exact format, never infer it.** Case, separators, and encoding are where
this goes wrong: labels may be title-case on screen and lowercase on the wire;
apostrophes stripped; spaces kept or hyphenated; lists comma-joined or repeated;
enums numeric or string. Try the obvious format, and when it fails, try the others
before concluding the feature does not exist.

Combine two filters and confirm they compose. Push limits (a page size, a count) to find
the real ceiling — vendors often accept far more than the UI sends, which is free
breadth for the same request.

### 4. Diff the UI against the API
For every number on screen, find its field in the response and check:

* **scaling** — is the display value the stored value? (`3` shown as "300%")
* **rounding** — "4.6k" against an exact 4580
* **derivation** — is the shown figure computed from fields, or returned directly?
* **absence** — a field present in the schema but always empty is DEAD; record it as
  dead so nobody builds on it. A field the UI shows but the API omits is computed
  client-side.

### 5. Write it down in two halves
Separate *what it does* from *what it is worth* — they have different readers and
different lifetimes:

| File | Contains |
|---|---|
| **reference** | pages, endpoints, every param, exact wire format, payload, response shape, verification mark |
| **analysis** | what a seller does with it, which decision it serves, what it uniquely answers, what it cannot answer |

Mark every fact: ✅ verified live (with date) · ⚠️ wired but returned empty · ❓ never
probed · ❌ confirmed dead. **An analysis claim must point at a verified reference fact.**

---

## What to extract for each control

```
CONTROL      the UI label the operator sees
PARAM        the wire parameter name
FORMAT       exact accepted value(s) — with a real example
DEFAULT      what the UI sends when untouched
EFFECT       what measurably changed in the response
LIMITS       max/min, and what value returns an error
COMBINES     does it compose with the others?
WORTH        what a seller learns from it that they could not otherwise
```

The last line is the one that matters and the one most often skipped.

---

## The marketer's questions, per surface

Score each page against these. A tool rarely answers all four, and knowing which one it
owns is how sources get combined later:

| Question | Reveals |
|---|---|
| **Is it rising?** | momentum, timing, lead time before a market crowds |
| **Who wants it?** | demographics, audience language for the listing copy |
| **Are they buyers?** | intent — clicks/purchases vs saves/bookmarks |
| **Can I win it?** | competition, supply, saturation |

A source that answers "rising" but not "can I win it" is a *leading indicator*, not a
decision — and pairing it with a source that answers the other is where the edge is.

---

## Boundaries

**Read-only.** Click filters, open panels, read responses. Do NOT: log in, submit forms,
change account settings, publish, purchase, or accept terms. If a control would change
the operator's account or spend money, stop and describe it instead.

**The operator's session is theirs.** Use the browser they hand you and never move
credentials out of it.

**No headless automation** where the project forbids it — this is an interactive session
in the operator's real browser, which is exactly why it is allowed.

---

## Working with the operator

They know the tool; you know the wire. That asymmetry is the whole method:

* When they say a filter exists and your probe 500s, **they are right and your format is
  wrong** — this has happened and cost real time.
* Ask them to point at what they actually use. The features a working seller ignores are
  usually noise, whatever the vendor's layout implies.
* Watch a real decision end to end — *"I look here, this number makes me care, so I check
  there, then I decide."* That workflow is the product spec, and it is invisible in any
  API.

---

## Anti-patterns

- Mapping endpoints without ever opening the UI
- Concluding a feature is unsupported because one value format errored
- Recording what a field is called but not what it is worth
- Trusting a displayed number to be the stored number
- Treating a curated/promoted list as objective market truth
- Leaving a signal marked "probably works" — probe it or mark it ❓
