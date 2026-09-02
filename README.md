# Etsy Market Intelligence

**Find out what to list, when to list it, and whether it will actually make you
money — using data Etsy only shows to sellers.**

You talk to it in plain English. It answers with numbers it can prove, and it tells
you when it does not know.

```
You:  compare these — home decor, backpack name tag, halloween badge reel

It:   term                    searches/mo   listings    ratio   verdict
      backpack name tag            63,588     24,671     2.58   winnable
      halloween badge reel         29,458     44,944     0.65   contested
      home decor                  497,430  1,478,573     0.34   wall

      home decor has 8x the traffic of backpack name tag — and 8x worse odds.
      1.5 million listings are already there.
```

That last line is the whole point. **Big market ≠ opportunity.**

*(Those are real numbers, measured 2026-09-01. Every figure this tool shows you can
be traced back to the call that produced it.)*

---

## Who this is for

You sell on Etsy — print-on-demand, handmade, digital downloads, personalised
goods — and you are tired of guessing. You want to know *before* you spend a
weekend making something whether anyone searches for it, whether they buy, and
whether you clear a profit after Etsy's fees.

**You do not need to know how to code.** You do need to follow a setup once.

### Who this is NOT for

- **You want a website to log into.** This is not a SaaS. It runs on your computer.
- **You want it in 5 minutes.** Realistic setup is **30–60 minutes**, and it needs
  Docker and a Chrome extension.
- **You want it to list products for you.** It never touches your shop. It advises;
  you decide and you list.
- **You want to run it for clients.** It logs in as *your own* Etsy account. Doing
  that with other people's accounts is a different thing entirely — see
  [Limits](#honest-limits).

---

## Why it is different from eRank / Marmalead / Alura

Those tools show search volume and competition. So does this. The difference is
what it does with them.

| | Typical keyword tool | This |
|---|---|---|
| Ranks by | search volume | **searches ÷ listings** — can you actually rank |
| Tells you *when* | ❌ | ✅ Pinterest takeoff dates → "list by 16 Sept" |
| Checks profit | rarely | ✅ your real costs, fees, and your own hourly rate |
| When unsure | shows a number anyway | **refuses, and says why** |
| Your data | on their servers | on your machine |

**It is built to refuse.** If a sample is too small to tell "empty niche" from
"crowded niche", it says so instead of showing a percentage. That is the feature
most keyword tools do not have.

---

## Before you start

You will need:

| | why |
|---|---|
| **A computer** (Windows/Mac/Linux) | it runs locally |
| **Python 3.11+** | the engine |
| **Docker Desktop** | runs the small session service |
| **Google Chrome** | a browser extension supplies the login |
| **An Etsy account** | ideally a seller account — that is where the good data is |
| **Claude Code** or Claude Desktop | how you talk to it |

Optional: a [Printify](https://printify.com) token if you want print-on-demand
cost checks.

> ⚠️ **It uses your own Etsy login.** That is why it can see real search volume and
> conversion rates that public tools cannot. It is also why you should read
> [Limits](#honest-limits) before running it hard.

---

## Install

### 1. Get the code

```bash
git clone <this-repo>
cd etsy-scrapper
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # Mac/Linux
```

### 2. Settings

```bash
cp .env.example .env
```

The defaults work. Only add a `PRINTIFY_API_TOKEN` if you want POD costing.

### 3. Start the session service

```bash
docker compose up -d redis go-api
```

### 4. Install the Chrome extension

1. Open `chrome://extensions`
2. Turn on **Developer mode** (top right)
3. Click **Load unpacked** → choose the `chrome_extension/` folder
4. Pin it, click it, and set:
   - **Profile Name** — anything, e.g. `My Shop`
   - **Etsy account** — pick **"My seller account"** if you are logged into Shop
     Manager, or **"Buyer account"** if not

Full detail: [`chrome_extension/README.md`](chrome_extension/README.md)

### 5. Log in, then check

Open Etsy in Chrome and sign in. Then:

```bash
.venv/Scripts/python.exe -m core.vault_status
```

You want **"Vault is green"**. If not, it tells you exactly what is missing.

### 6. Connect it to Claude

Edit `.mcp.json` and replace both paths with **your** folder:

```json
{
  "mcpServers": {
    "etsy-market-intel": {
      "command": "C:\\your\\path\\etsy-scrapper\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.server"],
      "cwd": "C:\\your\\path\\etsy-scrapper"
    }
  }
}
```

> ⚠️ Those paths ship pointing at the original author's machine. **You must change
> them** or nothing will connect.

Restart Claude Code. Ask it *"check my vault status"* — if it answers, you are done.

Longer walkthrough: [`docs/QUICKSTART.md`](docs/QUICKSTART.md)

---

## Using it

You do not run commands. **You ask.** Claude picks the right tool.

### Finding something to sell

| Ask | What happens |
|---|---|
| *"what should I list this week?"* | the calendar — moments with deadlines and terms |
| *"compare badge reel, sticker sheet, and enamel pin"* | one ranked table |
| *"find sub-niches under halloween badge reel"* | opens a term into its children |
| *"what do people search near 'badge reel'?"* | Etsy's own autocomplete — free |
| *"is dog collar worth doing?"* | full check: demand, competition, timing, profit |

### Checking the money

| Ask | What happens |
|---|---|
| *"will $18 work for a felt garland?"* | profit after fees, materials, your hours |
| *"can print-on-demand make money on this?"* | price ceiling and lead-time check |
| *"what do the top sellers charge?"* | page-one prices, not the misleading average |

### Watching competitors

| Ask | What happens |
|---|---|
| *"who ranks for felt garland?"* | every ranked shop and position |
| *"is anyone climbing?"* | rank over time — the thing snapshots cannot show |

### After you list something

| Ask | What happens |
|---|---|
| *"record my launch, listing 1234, for halloween badge reel"* | starts tracking it |
| *"how is my listing doing?"* | rank history, daily while it is new |

**This is the important one.** Until you record a launch, every recommendation is
an untested guess. Once you do, the system starts grading itself.

---

## The three sources, and why all three

| Source | Answers | Cost |
|---|---|---|
| **Etsy Private** (your seller login) | real search volume, conversion, seasonal curves | precious — used last |
| **Etsy Public** (normal browsing) | who ranks, prices, tags, competition | unlimited |
| **Pinterest** | *when* demand starts rising — weeks before Etsy | free |

Pinterest is why it can say **"list by 16 September"**. Trends appear on Pinterest
before people search Etsy. No keyword tool can tell you the date.

---

## Skills and agents (the part that makes answers trustworthy)

The folders `.claude/skills/` and `.claude/agents/` are **rules Claude must follow**
when it uses this system. You do not run them — they load automatically.

**Skills** stop bad conclusions. Examples of what they enforce:

- Never rank by search volume — always searches-per-listing
- A missing number means *"nobody checked"*, never *"zero"*
- Etsy's own filters lie — **9 of 12** were tested and cannot be trusted
- If the data cannot separate two options, say so instead of picking

**Agents** are specialists you can call: a backend engineer, a UX designer, a CTO,
a risk officer, a growth strategist. Ask *"get the growth strategist's view on
this niche"* and Claude answers wearing that hat, with that hat's rules.

Why you should care: **these are the difference between a confident answer and a
correct one.** They exist because this system has produced wrong numbers before,
and each rule is a scar.

---

## Honest limits

**Read this part.** It is the part most tools leave out.

- **It advises; it never acts.** It cannot list, edit, or price anything in your
  shop. One tool writes — recording a launch *you already made* — and that is all.
- **It uses your Etsy session.** Heavy use could get an account rate-limited. There
  is a known issue where a rate-limit can drop your session from rotation; the fix
  is written out in [`docs/OPERATOR_FIXES.md`](docs/OPERATOR_FIXES.md) and is one
  small edit.
- **It is single-user.** One person, one shop. It is not built to serve clients,
  and the login model does not multiply — see [`ROADMAP.md`](ROADMAP.md).
- **It is not calibrated yet.** It needs **10 recorded launches** before it can
  learn how accurate its own predictions are. Until then it is a well-reasoned
  opinion, not a track record — and it says so.
- **Most terms are walls.** That is not a bug. Etsy is saturated. A tool that finds
  you a "winner" every time is lying.
- **Scraping is against most sites' terms of service.** You are using your own
  account at your own risk. Get advice before doing this commercially.

---

## Cost

**Free.** No subscription. Runs on your machine. The only optional paid piece is a
Printify account if you want POD costs, and Printify itself has a free tier.

---

## Docs

| For | Read |
|---|---|
| Setup, step by step | [`docs/QUICKSTART.md`](docs/QUICKSTART.md) |
| Every tool, in detail | [`docs/MCP.md`](docs/MCP.md) |
| What a term means | [`docs/GLOSSARY.md`](docs/GLOSSARY.md) |
| Why it works this way | [`docs/GOAL.md`](docs/GOAL.md) |
| Contributing / architecture | [`CLAUDE.md`](CLAUDE.md), [`docs/DECISION_LOG.md`](docs/DECISION_LOG.md) |

---

## The one thing to remember

> **A term with 2 million listings is a wall, not an opportunity.**

Rank by whether you can win, never by how big the market is. Everything else here
is built to protect that one idea.
