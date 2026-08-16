# How we work

The operating model. Written 2026-08-16 after a long session that built a working
machine but lost the thread — because there was no agreed way of working, only a pile of
tasks.

---

## The three seats

| Seat | Owns | Never |
|---|---|---|
| **Operator / CEO** (you) | what to sell · real costs · which competitors matter · confirm or kill a direction · **what the tools actually look like** | writes code · supplies a number the machine can measure itself |
| **Engineer** (Claude) | build it · verify on the wire · keep the guards · report honestly | decides product direction · invents a number to fill a gap |
| **The lenses** (skills) | which data is worth gathering · is the number true · is it the right number to show first | override a measured number with an opinion |

**When we disagree about a fact, the wire settles it.** Probe, do not argue. That rule
has been right every time it was applied, in both directions — it caught my wrong
"filters don't work" and it confirmed the operator's UI knowledge.

---

## The asymmetry that makes this work

The operator sees the **product**; the engineer sees the **wire**. Neither view is
complete:

* Probing endpoints alone missed an entire tab, mislabelled working filters as broken,
  and nearly reported a number 100× too small.
* Reading the UI alone cannot tell you a field is always empty, or that a listing page
  sometimes returns the *shop's* review count instead of the listing's.

So the highest-value sessions are the ones where both views are on the same screen. That
is what `web-surface-mapping` is for.

---

## The loop

```
1  OPERATOR points        "map this page" / "this niche matters" / "that number is wrong"
2  ENGINEER probes        verify on the wire, never assume — screenshot + network + API
3  BOTH read together     the operator names what a marketer would do with it
4  ENGINEER writes        reference (what it does) + analysis (what it is worth)
5  ENGINEER builds        smallest useful thing, tested, committed atomically
6  OPERATOR confirms      keep / kill / redirect
```

Step 3 is the one that was missing for most of this project, and its absence is why the
work felt directionless despite passing tests.

---

## Where things live

```
docs/
  HOW_WE_WORK.md       this file
  GOAL.md              the north star — what the product IS
  DECISION_LOG.md      why anything is the way it is (D-01…)
  market_map/          THE SHARED MAP
    reference/         what each endpoint DOES — params, payloads, verified marks
    analysis/          what it is WORTH — per platform, then combinations
  architecture/        system design, build plan, session layer, gaps
  blueprint/           UI structure
  _archive/            superseded — kept for history, not current truth

.claude/skills/        the enforced lenses (see below)
```

---

## The lenses (skills), and when each fires

| Skill | Asks | Read before |
|---|---|---|
| `etsy-pipeline-work` | **is the number true?** | touching any pipeline, API client, or parser |
| `etsy-seo-and-opportunity` | **is it the right number to show first?** | ranking, scoring, or recommending anything |
| `etsy-market-intelligence` | **is this worth gathering at all?** | planning data work or judging an endpoint's value |
| `web-surface-mapping` | **what does this tool actually expose?** | a browser session mapping a site |
| `system-architect` · `bias-aware-analysis` · `ui-builder` · `git-and-comments` | design · bias · UI · commits | as their descriptions say |

The first three are deliberately a set: one catches a wrong number, one catches a correct
number shown in the wrong order, one catches gathering the wrong thing entirely. All
three cost the operator a wasted launch, and only the first looks like a bug.

---

## Rules that have already paid for themselves

1. **Probe the wire before theorising.** Three plausible, documented explanations for the
   empty tables were all wrong; one live call settled it in seconds (D-24).
2. **Diff response keys against the keys the code reads.** The same snake_case bug hid at
   four separate layers and emptied every table for the project's life.
3. **Absent is not zero.** A value that did not parse is unknown, never 0 (N-02).
4. **Refuse rather than guess.** Every refusal in this system exists because the
   alternative was a confident wrong number.
5. **Never spend the seller account on something public can answer** (D-29).
6. **Rank by winnability, not market size** (D-31).
7. **Store every reading, with provenance and a timestamp.** Value compounds only with
   time; a single reading is a level, not a trend.

---

## Branching

- **Docs, skills, mapping** → straight onto the working branch. Additive and safe.
- **Deletions or risky refactors** → a branch, so undo is free.
- **Agents/subagents** → not for this project. The work depends on shared session
  context and the operator's live browser; a cold agent re-derives everything and cannot
  see the screen.

---

## What "done" looks like for a piece of work

- verified on the wire (or explicitly marked ❓ if not)
- guards intact — no refusal removed to make something pass
- tested offline, all suites green
- committed atomically with the **why** in the body
- the map updated if the surface changed
