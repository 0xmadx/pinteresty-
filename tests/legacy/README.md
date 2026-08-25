# tests/legacy — pre-refactor probes, NOT the test gate

**The real test suite does not live here.** It lives beside the code it tests —
`core/test_*.py`, `etsy/analytics/test_*.py`, `etsy/ui/test_*.py`, and so on. That
is 58 offline suites and 1,543 assertions, it needs no network, and a green run of
it is the release gate.

These nine files are older. They date from the Gemini-era session refactor
(last touched 2026-08-14, commit `3a7a106`) and were written to probe the **access
layer** by hand while it was being stabilised: dynamic profile pooling, `{shop_id}`
URL injection, fetching a shop id, checking a session end to end.

## Why they are kept

They still import modules that exist (`core.session_manager`, `core.cookie_vault`,
`core.endpoints_manager`, `core.shop_scraper`), so they are not dead — and the
access layer is the one part of this system that is hardest to reason about
without a live probe. When a session problem needs diagnosing by hand, these are a
reasonable starting point.

## Why they are not in the gate

- **They are live.** They hit real Etsy and a real Redis vault. Their results
  depend on whether the extension is beaming and whether the mirror is fresh
  (D-33), so they cannot gate anything — a suite whose outcome moves with session
  state is not a regression test.
- **Some test capabilities that were deliberately removed.** `find_shop_id.py`
  and `test_fetch_shop_id.py` predate the deadlock fix that *deleted*
  `auto_discover_shop_id()`; the `{shop_id}` placeholder is now filled per-request
  from the vault profile, so "discover the shop id" is no longer a thing the
  system does.
- **They were never counted.** The suite runner walks `core/`, `etsy/`,
  `pinterest/` and `mcp_server/`, so `tests/` has never been part of any reported
  number.

## Before running one

They talk to the live vault, so refresh the mirror first or they will read a stale
copy and fail in a way that looks like a code problem:

```bash
.venv/Scripts/python.exe -m core.vault_status
```

**Do not extend these, and do not add new session-handling code here.** The access
layer is read-only to contributors without the operator's explicit say-so — see
rule 6 in `CLAUDE.md`.
