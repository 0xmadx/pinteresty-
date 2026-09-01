# Quickstart — from a fresh clone to your first real answer

This is the one path, in order. Nothing else to read first. Once it's running,
`README.md` is the reference and `docs/ONBOARDING.md` is the "traps to avoid"
briefing — read those next, not before.

A few words that will come up: **the vault** is the Redis database holding your
session cookies — think of it as "where the system keeps you logged in" so it
doesn't ask you to sign in every time. **The extension** is what fills it, by
watching you browse normally in Chrome.

**Setting this up inside WSL (Linux on Windows) instead?** This page assumes
Windows + Docker Desktop directly. For a full WSL walkthrough — including how
Chrome (which stays on Windows) reaches services running inside WSL — see
[`docs/WSL_TUTORIAL.md`](WSL_TUTORIAL.md) instead.

## 1. Clone and install

```bash
git clone git@github.com:0xmadx/main-scraper-.git
cd main-scraper-
python -m venv .venv
.venv\Scripts\pip.exe install -r requirements.txt
```

Always use `.venv\Scripts\python.exe` from here on — the system Python doesn't
have the packages this needs.

## 2. Set up your `.env`

```bash
copy .env.example .env
```

Open `.env` and paste in `PRINTIFY_API_TOKEN` (get one at printify.com →
Settings → Connections → Generate token) if you want the POD-costing tools.
Everything else already has a working default — leave it alone for now.

## 3. Start the vault

```bash
docker compose up -d redis go-api
```

This starts two things: **Redis** (the vault itself) and a small **Go server**
that the Chrome extension talks to. Requires Docker Desktop running first.

## 4. Install the Chrome extension and sign in

Follow **`chrome_extension/README.md`** — it covers loading the extension
unpacked, what its popup asks for, and one non-obvious step (visiting your Shop
Manager once so the system captures your `shop_id`). Do that now, then come
back here.

## 5. Confirm the vault sees you

```bash
.venv/Scripts/python.exe -m core.vault_status
```

Look for `Vault is green — live calls will work.` at the bottom. If it isn't
green, the output tells you exactly which platform is missing and what to do —
usually "open Chrome and sign in" or "visit Shop Manager once" (step 4 again).

## 6. Pull your first real data

```bash
.venv/Scripts/python.exe -m core.scheduler --once
```

This runs whatever daily jobs are due — keyword sweeps, competitor checks, the
calendar. It's also registered to run automatically every morning at 07:00 once
`run_scheduler.cmd` is set up as a Windows scheduled task (see `README.md`), but
running it manually now gets you today's data immediately.

## 7. Look at it — wire up your agent (this is the interface)

**There is no web UI.** The HTML screens and the optional read server were
deleted on 2026-09-01 (D-52) — they were built once, never revisited, and the
server had no callers. You read this system by *asking it*, through an MCP
client (Claude Code, Claude Desktop, Antigravity).

Follow **`docs/MCP.md`**. One thing to know before you do: the project's
`.mcp.json` hardcodes an absolute path to wherever it was originally cloned.
**If your clone lives somewhere else, edit that path first** — otherwise it
fails quietly (an empty result that looks like "no data yet," not a clear error).

Then ask it `vault_status` first, and `calendar` for what to list this week.

## What's next

- **`README.md`** — the full command reference.
- **`docs/ONBOARDING.md`** — real traps this project has already hit, so you
  don't rediscover them the hard way.
- **`docs/MCP.md`** — the whole agent surface, and where DeepSeek is allowed to
  touch the system.
