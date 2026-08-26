# Running this in WSL — a complete beginner's tutorial

This is a **separate**, fuller walkthrough from `docs/QUICKSTART.md`. QUICKSTART
assumes Windows + Docker Desktop and moves fast. This one assumes you've never
used WSL before, explains *why* each step exists, and — the part that actually
matters — explains **which pieces run where**, because that's the one thing
that's genuinely different about a WSL setup and the one thing that silently
breaks if you don't understand it.

Read the whole "How the pieces connect" section before typing anything. Everything
after it is just commands.

---

## 1. What WSL actually is (in one paragraph)

WSL (Windows Subsystem for Linux) is a real Linux system running *inside* your
Windows machine — not a virtual machine you have to babysit, just a Linux
terminal you can open like any other program. We're using it because this
project's Python tooling, Docker workflow, and file conventions are all
Linux-native, and running them from a genuine Linux shell avoids a whole class
of Windows-path and line-ending problems. You already have it: `Ubuntu` showed
up running when we checked earlier.

---

## 2. How the pieces connect (read this first — this is "linking nodes")

This is the part a tutorial usually skips, and it's the part that actually
confuses people. Four things exist, and they don't all run in the same place:

```
                    YOUR WINDOWS DESKTOP
   ┌─────────────────────────────────────────────────┐
   │                                                   │
   │   Chrome (real browser, you browsing normally)    │
   │        │                                          │
   │        │  the extension watches you sign in,      │
   │        │  then POSTs cookies to...                │
   │        ▼                                          │
   │   http://localhost:8000  ◄─────────────────────┐  │
   │                                                 │  │
   └─────────────────────────────────────────────────┼──┘
                                                       │
                    WSL — UBUNTU (a real Linux box)   │
   ┌────────────────────────────────────────────────┼──┐
   │                                                 │  │
   │   Docker containers (redis, go-api, ...)  ◄─────┘  │
   │        │                                          │
   │        ▼                                          │
   │   Redis — THE VAULT (your session cookies live    │
   │   here)                                            │
   │        ▲                                          │
   │        │  Python reads sessions from here          │
   │   Python (venv, this repo's code)                  │
   │                                                     │
   └─────────────────────────────────────────────────────┘
```

**The one fact that makes this all work:** Docker Desktop's WSL2 integration
makes `localhost` mean the same thing on both sides. When a Docker container
running *inside* WSL publishes port 8000, Windows Chrome can reach it at
`http://localhost:8000` as if it were running on Windows directly. You don't
have to configure networking for this — it's automatic — but it's worth
understanding *why* it works, because when it doesn't (see Troubleshooting), this
is the first thing to check.

**What stays on Windows, always:** Chrome, and therefore the extension. There's
no way around this — the extension needs a real, visible browser window for you
to sign into Etsy and Pinterest in, and WSL doesn't give you that easily. Nobody
should try to make Chrome run inside WSL for this; it's more trouble than it's
worth for zero benefit.

**What moves into WSL:** everything else — Docker, Redis, the Python code, and
(if you choose) the AI agent tooling (Claude Code) that talks to the MCP server.

---

## 3. Before you start — three things to check

**3a. Confirm WSL and Ubuntu are set up.** Open PowerShell and run:

```powershell
wsl -l -v
```

You should see `Ubuntu` with `STATE: Running` or `Stopped` (either is fine —
Windows starts it automatically the moment you open an Ubuntu terminal). If
`Ubuntu` isn't listed at all, run `wsl --install -d Ubuntu` and restart when it
asks.

**3b. Turn on Docker Desktop's WSL integration.** This is the step people miss,
and it's why `docker` "doesn't exist" inside a fresh WSL terminal even though
Docker Desktop is running:

1. Open **Docker Desktop** on Windows.
2. **Settings → Resources → WSL Integration**.
3. Turn on the toggle for **Ubuntu**.
4. Apply & Restart.

**3c. Open an Ubuntu terminal.** Windows Start menu → type `Ubuntu` → open it.
Everything from here on happens inside that window, not PowerShell.

---

## 4. Set up the project — inside the Ubuntu terminal

**Why not just use the Windows copy from WSL?** You could technically reach
`/mnt/c/Users/...` from WSL, but don't — cloning fresh into WSL's own Linux
filesystem is both much faster (Windows-mounted paths are slow from Linux) and
gives you the clean, genuinely separate copy you're after.

```bash
cd ~
git clone git@github.com:0xmadx/main-scraper-.git etsy-hunter
cd etsy-hunter
```

If `git clone` asks about SSH keys and you don't have one set up inside WSL yet,
the simplest fix for a first run is cloning over HTTPS instead:

```bash
git clone https://github.com/0xmadx/main-scraper-.git etsy-hunter
```

**Python and dependencies** (Linux commands — different from the Windows
`.venv\Scripts\...` you may have seen elsewhere):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

From now on, either keep that terminal's `source .venv/bin/activate` active, or
prefix every command with `.venv/bin/python`. (This is the WSL equivalent of
`.venv\Scripts\python.exe` on Windows — same idea, different path style.)

**Your `.env`:**

```bash
cp .env.example .env
nano .env
```

Paste in `PRINTIFY_API_TOKEN` if you have one (printify.com → Settings →
Connections → Generate token). `Ctrl+O`, Enter, `Ctrl+X` to save and exit
`nano`. Everything else already has a working default.

---

## 5. Start the vault — still inside Ubuntu

```bash
docker compose up -d redis go-api
```

This is the exact same `docker compose` command you'd run on Windows — the
difference is *where* it runs, and because of the WSL integration from step 3b,
it talks to the same Docker Desktop engine either way.

Confirm both are up:

```bash
docker ps
```

You should see `scraper-redis` and `cookie-server-go`, both `Up`.

⚠️ **If you already had the Windows-side version of this project running**, its
Redis is also trying to use port 6379, and one of the two will fail to start
with a "port already in use" error. Decide which one you're actually using —
if it's this WSL copy, stop the old one first (from the *old* project's folder,
`docker compose down`). Don't run both at once; see Troubleshooting if this
happens after you thought you'd stopped the old one.

---

## 6. Install the Chrome extension — back on Windows

This is the one step that happens **outside** WSL, because Chrome lives on
Windows. Open Windows File Explorer, navigate to your WSL files (type
`\\wsl$\Ubuntu\home\<your-username>\etsy-hunter\chrome_extension` in the address
bar, or open Ubuntu's file manager via `explorer.exe .` from inside the
`chrome_extension` folder in your WSL terminal), and follow
**`chrome_extension/README.md`** from there — loading it unpacked, what the
popup asks for, and the Shop Manager step that captures your `shop_id`.

Because of the port-forwarding from section 2, the extension posting to
`http://localhost:8000` reaches the Go server running inside WSL without any
extra setup.

---

## 7. Confirm it all actually links up

Back in the Ubuntu terminal:

```bash
.venv/bin/python -m core.vault_status
```

Look for `Vault is green — live calls will work.` If Windows Chrome successfully
posted your cookies and WSL's Python can see them, this is the proof the whole
diagram in section 2 is actually working end to end.

---

## 8. Run it

```bash
.venv/bin/python -m core.scheduler --once
```

Then open the result — from the WSL terminal you can jump straight to it in
your Windows browser:

```bash
explorer.exe etsy/data/ui/index.html
```

---

## 9. MCP — wiring an AI agent to this WSL copy

If you're running **Claude Code from inside WSL** (recommended — it works
natively there, and then everything, including the agent, is in one place),
`.mcp.json` in this repo already works as-is once you're `cd`'d into
`~/etsy-hunter` — the paths inside it are WSL-native and don't need Windows-path
editing the way the original repo's did.

If you're instead running Claude Code or Antigravity **on Windows** and want it
to reach into this WSL copy, the MCP server command needs to go through `wsl.exe`:

```json
{
  "mcpServers": {
    "etsy-hunter": {
      "command": "wsl.exe",
      "args": ["-d", "Ubuntu", "--",
                "/home/<your-username>/etsy-hunter/.venv/bin/python",
                "-m", "mcp_server.server"],
      "cwd": "/home/<your-username>/etsy-hunter"
    }
  }
}
```

Replace `<your-username>` with your actual WSL username (run `whoami` inside
Ubuntu if unsure). Full tool list and usage: `docs/MCP.md`.

---

## 10. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `docker: command not found` inside Ubuntu | WSL integration not turned on | Step 3b — Docker Desktop → Settings → Resources → WSL Integration |
| Redis/go-api won't start, "port already in use" | The Windows-side copy of this project is already running its own Redis on the same port | `docker compose down` from the OTHER project's folder first |
| `vault_status` shows the vault as empty right after signing in | Sessions take a moment to POST; also confirm the extension is actually loaded and pointed at `localhost:8000` (see `chrome_extension/README.md`) | Reload the Etsy/Pinterest tab once, wait a few seconds, re-run `vault_status` |
| Chrome extension seems to do nothing at all | Extension not loaded, or loaded from the wrong (old) folder | Recheck `chrome://extensions`, confirm it's pointed at THIS clone's `chrome_extension/` folder |
| Everything in WSL feels slow | The repo was cloned into `/mnt/c/...` instead of WSL's own filesystem | Re-clone into `~/etsy-hunter` (your Linux home), not a `/mnt/c/` path |
| `git clone` hangs or asks for a password you don't have | No SSH key set up in WSL yet | Use the HTTPS clone URL shown in step 4 instead |

---

## What's next

Once `vault_status` is green and you've seen `index.html` render — you're set
up. From here, `README.md` and `docs/ONBOARDING.md` are the same documents a
Windows setup would point you to; nothing about using the system day-to-day
differs based on where it's installed.
