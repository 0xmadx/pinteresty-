# Which model, how much effort, and when NOT to fan out

Written 2026-09-01 after two audit workflows spent ~3.7M subagent tokens in one
session. They earned it — between them they found the `chart-series` truncation,
the discriminate mapping, the phantom columns and the 429 eviction, all live
wrong-number bugs. But that is the exception, and this file exists so the
exception does not become the habit.

---

## The rule that saves the most: don't fan out

**Model choice is a rounding error next to the decision to run 19 agents.**

| approach | rough cost | when it is right |
|---|---|---|
| Do it directly | 1× | almost always |
| One subagent | ~3–5× | a search across many files where you only need the conclusion |
| A workflow (10–20 agents) | **~50–200×** | rarely |

A workflow is worth it when **the answer is unknown and the cost of being wrong is
high** — a full-system audit, an adversarial review before a risky change. It is
*not* worth it for:

- anything you already know the answer to (a "board meeting" that confirms the
  obvious produces expensive prose)
- implementing a decision that is already made
- writing docs, tests, or a feature with a clear spec
- exploring a codebase you have already explored this session

⚠️ **The tell:** if you can predict roughly what the agents will say, do not run
them. Prediction means you already have the answer and are buying confidence, not
information.

---

## Model

Opus is for work where **a wrong answer is subtle and expensive** — where it looks
right and reaches the operator. That is a narrow set.

| model | use for | why |
|---|---|---|
| **opus** | analytics, parsers, pipelines · architecture calls · risk with a veto · adversarial verification | this project's failure mode is *a plausible wrong number, not a crash*. Those are the places it hides |
| **sonnet** | implementation against a written spec · MCP tool wiring · frontend · docs · tests · applying stated rules | the rules are already written down; following them is not the hard part |
| **haiku** | mechanical search, formatting, file inventory | no judgement involved |

Current assignment (`.claude/agents/*.md`): **3 opus, 5 sonnet.** All eight were
opus when first written — that was the expensive default applied without thought,
and it is exactly the mistake this file exists to stop.

---

## Effort

| effort | for |
|---|---|
| `low` | mechanical edits, renames, formatting, running a known command |
| `medium` | **the default.** Most implementation |
| `high` | genuinely ambiguous debugging; a design with real trade-offs |
| `xhigh` / `max` | reserve for adversarial verification of a claim you are about to act on |

Raising effort on a task whose rules are already written does not buy accuracy —
it buys re-derivation of things the skill file already says.

---

## What was actually expensive here, measured

| | tokens | verdict |
|---|---|---|
| SEO/batch audit, 19 agents | ~1.95M | **worth it** — 4 live bugs, incl. 8 of 11 seasonal curves missing |
| Goal/SaaS audit, 19 agents | ~1.78M | **worth it, expensive** — 44 claims raised, **14 survived** |
| Board meeting, 9 agents | killed | **not worth it** — the answer was already known: 0 launches |

That 44 → 14 ratio is the honest headline: **two thirds of what a fan-out
"finds" does not survive being checked.** Budget for the verify phase or do not
run the fan-out at all.

---

## Cheaper habits that lose nothing

1. **Probe the wire.** One live call has repeatedly beaten a page of reasoning
   (D-24). It is also nearly free.
2. **Grep before you theorise.** `classify()` having zero call sites took one grep
   and overturned three documents.
3. **Read the decision log first.** Most "should we…" questions are already
   answered there, at zero cost.
4. **Let the skills do the work.** They are loaded on trigger and already hold the
   caveats — re-deriving them at high effort is paying twice.
5. **Write the failing test first.** Cheaper than a review pass, and it stays.

---

## The standing question before any expensive run

> **What decision changes based on the answer?**

If nothing changes, do not run it. Most of the value in this project has come from
one grep, one live probe, or one test — not from a fan-out.
