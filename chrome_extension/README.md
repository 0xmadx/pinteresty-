# The Chrome extension

This is how the system gets sessions. There is no login flow of its own — a real
person browses in a real Chrome window, and this extension quietly captures the
cookies and hands them to the vault. See `CLAUDE.md` rule 6: no Playwright, no
headless browsers, ever. This is the only capture mechanism, on purpose.

## Install it (unpacked — it isn't on the Chrome Web Store)

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked** and select this folder (`chrome_extension/`).
4. Pin the extension so its icon stays visible in the toolbar.

## Set it up, once per browser profile you use

Click the extension icon to open the popup. It asks for two things:

- **Profile Name** — free text, e.g. `Seller_Account_1`. Just a label for you;
  the vault generates its own internal id (`profile_<random>`) separately.
- **Etsy account in this browser** — a dropdown with three options:
  - *"— not signed in to Etsy —"*
  - *"Buyer account (public scraping)"*
  - *"My seller account (Shop Manager)"*

The popup's own hints matter, so here they are verbatim:

> Only Etsy needs this — we can't tell a buyer login from a seller login by
> looking. **Pinterest syncs automatically**, so you can keep both open in one
> browser.

> Don't mark a seller-logged-in browser as *Buyer* — that puts your seller
> session in the competitor-scraping pool.

That second line is not a formality. If you mark your seller session as Buyer,
the system will try to use it to scrape competitors — which is exactly the thing
D-29 exists to prevent (`etsy_private` authenticates as *you*, the one
unreplaceable asset here).

## The one step the popup doesn't tell you: capturing `shop_id`

Setting the dropdown to *"My seller account"* is not enough by itself. The
system only learns your `shop_id` by watching you visit a Shop Manager page —
specifically a URL matching `/shop/<digits>/...`. So after signing in as your
seller account:

1. Go to Etsy → **Shop Manager** (or any URL like
   `etsy.com/your/shops/<your-shop-id>/...`).
2. Load that page once, signed in.
3. That's it — the extension captures `shop_id` from the URL itself.

Skip this and `etsy_private` will show a session with no `shop_id`, which reads
as unusable even though you're signed in. This is the single most common reason
a fresh setup looks broken when it isn't — see `docs/QUICKSTART.md` step 5.

## Checking it worked

From the repo root:

```bash
.venv/Scripts/python.exe -m core.vault_status
```

A profile you just captured should show up with a recent heartbeat. If it
doesn't, the extension isn't running, isn't signed in, or hasn't POSTed yet —
reload the Etsy/Pinterest tab once signed in and check again.
