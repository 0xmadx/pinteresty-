> **Audit of 2026-09-01.** The operator said: *"I think you build the project based
> on biases and understanding of skills."* This is the check. 19 agents, 4 lenses,
> **40 claims raised and 13 survived** an adversarial pass — the audit was primed to
> find builder-bias, and two thirds of what it found did not hold.
>
> Verified by hand before publishing: blueprint.py is unreachable from MCP (grep
> returns zero), the calendar summary sentence was false, and the margin floors
> reject a product paying $37.70/hour.

# Is the shape of this project the assistant's instincts, or your needs?

I read the code and counted. Not the docs — the docs were written by the same mind I was asked to check.

---

## 1. ARE YOU RIGHT?

**Yes, mostly. Not entirely.**

Here is what is on disk today:

| | count |
|---|---|
| MCP tools (your only door in) | **34** |
| Skills (rules for the assistant) | 12 |
| Agents (fake job roles) | 9 |
| Decision-log entries | 66 |
| Python that runs | ~24,600 lines |
| Python you cannot reach from any tool | **~4,600 lines (19%)** |
| English prose written | ~13,900 lines |
| Prose written *for you* | ~1,400 lines (**7%**) |
| Listings launched | **0** |

**Where you are clearly right:**

- Five of the nine agents (`.claude/agents/cto.md`, `eng-manager`, `head-of-product`, `growth-strategist`, `risk-officer`) are a **pretend company** — a CTO who "reports to the CEO", a Risk Officer with a veto. You are a one-person shop. You are all five. And the project's own cost file already admits it: `docs/COST_POLICY.md:74` records *"Board meeting, 9 agents | killed | not worth it — the answer was already known: 0 launches."* Nothing in the 66 decisions explains why they were created.
- A whole web interface was built in two days (2026-08-19/20, 47 commits), had **zero users of any kind**, and was deleted twelve days later. Its design documents are still in the tree (`docs/blueprint/`, 534 lines), and `docs/START_HERE.md:154` still tells a reader to go build it.
- Roughly one in five lines of working Python cannot be reached from any tool you can use. Two of those files got **new commits today** — a bug fix inside `etsy/analytics/grid_analytics.py`, a file with zero connections to anything, on a day with zero launches.
- Two skills (`git-and-comments`, `system-architect`) are about how to write code and commit it. You did not need those authored.

**Where you are wrong — and this matters:**

- The **decision log is not engineering trivia**. I classified all 66 entries. About 70% by length are decisions you would recognise: "don't rank by market size", "nine of twelve Etsy filters lie", "price off page one, not the price band". That is your business knowledge, written down.
- The **money math and the guards are real work for you**, not for the builder. Several of them exist because a wrong number *actually reached you* and was caught. I list them in section 5. Removing them would bring the wrong numbers back.

So: the *rigour* served you. The *apparatus around the rigour* — the org chart, the deleted UI, the process documents — served the builder.

---

## 2. WHAT IT COVERS OF YOUR WEEK

Your week has six steps:

1. Decide what to make
2. Make it (design, POD setup, photos)
3. **Write the listing** — title, 13 tags, description
4. Price it
5. Publish
6. Learn from what sold

**The system covers step 1 about twenty times over.** Of 34 tools, most are a different way to look at a keyword: `discover`, `compare`, `analyze`, `keyword_crawl`, `deep_dive_keyword`, `scout`, `find_terms`, `cockpit`, `analyze_keyword`. Step 4 (pricing) is genuinely covered and genuinely good.

**Steps 2, 3, 5 and 6 are covered by almost nothing.**

Here is the sharpest single fact in this audit:

> `etsy/generators/blueprint.py` — 291 lines — **writes you a title, 13 valid tags, a price and a category.** It has 32 passing tests. It works.
>
> `grep "generators" mcp_server/` returns **0**.

You cannot reach it. The only way to run it is typing `python -m etsy.analytics.hunt` in a terminal, and you are not a developer.

It is not that nobody thought of you. It had a screen once — `etsy/ui/blueprint_page.py`, whose own first line read *"the last mile, from 'winnable' to a listing you paste."* That screen was **deleted this morning** when the UI was removed, and nothing replaced it.

And for the description — the long text on your listing page — there is nothing at all. The only description code in the repo is `etsy/generators/listing_generator.py:252`, which writes literally:

```
1. Snippet: ...
2. Connection: ...
3. Specs: ...
```

Three dots. That file has no tests, no connections, and has never produced a single output file.

**The honest fraction: the system does about 80% of "which keyword" and about 0% of "make the thing and write the listing."**

---

## 3. THE REFUSAL PROBLEM

Is it telling you a hard truth, or is it set so nothing can ever pass? **Both. Here are the actual numbers.**

The rule is one line, `etsy/analytics/discover.py:118-126`:

```
ratio = searches ÷ listings
ratio ≥ 1.00  → "winnable"
ratio ≥ 0.25  → "contested"
otherwise     → "wall"
```

Against the real database (`market_intelligence.db`, measured just now):

| verdict | rows |
|---|---|
| wall | **7,154** |
| contested | 22 |
| weak_intent | 7 |
| winnable | **2** |

7,185 rows, 2,303 different keywords, **two** ever called winnable.

**Three separate things are wrong here.**

**(a) The code knows the number is unfair and says so in English instead of fixing it.** Lines 128-145 of that same file are an 18-line comment explaining that Etsy's listing count is a *broad* match, so a long phrase is "pushed toward `wall` by construction rather than by the market." The fix was never written as code. The instruction to compare a keyword against its *siblings* (children of the same seed) exists only as a note telling the reading agent to do it in its head. Every row already stores its seed. Nobody groups by it.

**(b) The label is used as a filter, not a label.** `mcp_server/tools_decide.py:69-71` keeps only winnable and contested. Run live: a pool of 1,716 rows in, **2 rows out**, 1,714 hidden. Meanwhile the engine that wrote the pool says in its own comment "nothing is filtered out — the reader decides." The tool and the engine disagree.

**(c) But — and this is the honest part — fixing the threshold will not make winners appear.** The median ratio for a two-word phrase is 0.004. That is 60 times below the cut. The market really is crowded. The problem is not that the answer is "no". The problem is that "no" is delivered as **silence** instead of *"here are the five least-bad options and exactly what we don't know about each."*

**The calendar is the worst case of this.** It is the stated purpose of the whole project, and it has **never once** been able to say "list this."

- A row becomes actionable only if `profitable is True` (`calendar_engine.py:214`).
- `profitable` only gets a value if a **cost profile** is passed in (`:162`).
- **None of the four places that call it passes one** — the MCP tool, the daily scheduler, the command line, and the read layer.
- Result: **45 of 45** recorded calendar rows say `actionable: false`. Not because of the market. Because of one missing argument.

And then it prints a sentence that is false. Today's output says:

> "Every dated moment is either unmatched or backed only by wall terms."

Two lines above it, on the same screen, sits `halloween badge reel — 29,458 searches / 44,944 listings = 0.655`. That is well above the wall line. It is not a wall. The sentence is wrong, and it is the line most likely to be read as the verdict.

**Also: do not trust the 136 "go" verdicts.** `etsy/engines/master_niche_finder.py` writes go/no-go from price alone — the file contains zero references to winnability. 132 of those 136 "go"s are on terms the wall gate rejects, and every one was judged as a **digital download at zero cost**, because line 21 of that file defaults everything to digital. You sell POD, handmade and personalised too.

---

## 4. WHAT TO CHANGE

**Cheap plumbing — hours, not days. Code exists, door missing.**

1. **Fix the calendar's false last sentence** (`calendar_engine.py:280-285`). Report "rankable" (already computed, line 217) separately from "actionable". When something is rankable but unpriced, say *"1 term qualifies but has no cost profile"* — never "nothing fits".
2. **Pass the cost profile through all four call sites** and expose it on the calendar tool. Make it your explicit choice. Do **not** auto-pick it silently — the personalised profile turns halloween into **-130%**.
3. **Stop hiding the walls.** Return the ranked list with the label attached (`tools_decide.py:69-71`). Two rows from 1,716 is not a shortlist.
4. **Show the basis on verdicts.** `verdict_log.explain()` already has a field saying "this was profit-only, no supply check" — and throws it away before you see it. ~3 lines.

**Real work — days. Never built.**

5. **One new tool: `listing_blueprint(term, product_type)`.** This is the highest-value item in the whole audit. It wraps working, tested code. Be realistic: it needs a private call (spends your seller account), a search pass plus ~6 listing fetches, and a profile — call it **3-4 hours**, not one line.
6. **Sibling ranking.** Compare each child keyword against the other children of the same seed. Report it as an extra column, **never as the verdict** — a percentile verdict would crown the best child of a dead niche, which is exactly the wrong-number failure the wall rule prevents.
7. **Description help** needs a new parser first. Today only Etsy's short share-snippet is captured, not the real description text.
8. **Delete:** the five board agents, `docs/blueprint/` (and repair the six documents that point at it), and the cold orphan modules from August.

**And the one that beats all of them:** you have **0 launches**. `record_launch` is now reachable from MCP. One real listing, published and recorded, turns every verdict in this system from a guess into something that can be graded. Nothing above substitutes for that.

---

## 5. WHAT NOT TO CHANGE

These are not caution for caution's sake. Each one was added **after** a wrong number reached you.

- **The cost-profile gate on the calendar.** Before it (commit `1a671bb`, today), the calendar showed `halloween badge reel` at **+85.5% margin, go = yes** — computed at zero cost. Under your real personalised profile it is **-130%**. Remove the gate and that lie comes straight back.
- **Pricing off page one instead of Etsy's price band** (D-46). The band gave a $5.21 cost ceiling — POD impossible. The 20 listings that actually rank gave **$12.69** — plausible. Same term, same day.
- **Ranking by demand-per-listing, not search volume** (D-31). `home decor` has 310,467 searches and 0.14 searches per listing. `backpack name tag` has 69,874 and **2.79**. The first is a wall. Volume ranking put it first.
- **"Absent is not zero."** A badge that didn't load means *unmeasured*, not *no sales*. Turning those into 0 would silently mark good products dead.
- **Refusing to rank when the numbers can't separate the candidates** (`can_discriminate`). A ranking of things that are actually tied is a coin flip wearing a suit.
- **Never putting a competitor's shop id in a private call** (D-29). Your seller account is the one thing here that cannot be replaced.
- **The append-only history tables.** 536 competitor rank rows are already stored. A day-over-day change cannot be backfilled — if you stop recording, that data is gone forever.

---

**The one-line answer to your question:** the *thinking* in this project is yours — winnability, margin floors, refusing to guess. The *scaffolding* around it is the builder's — an org chart, a deleted website, 4,600 lines you cannot reach, and a keyword-finder built twenty times while "write my listing" was built twice and unplugged both times.