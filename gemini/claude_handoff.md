# Gemini to Claude Handoff: Architectural Refactoring & Cleanup

**Author:** Gemini (Antigravity Agent)
**Date:** August 2026
**Purpose:** Hand over the structural, deployment, and security changes made to the Etsy Niche Decision Machine to Claude. This ensures Claude has exact context on *why* the architecture changed, *how* the components now interact, and *where* things were moved.

---

## 1. Project Cleanup & Structure
The root directory was cluttered with testing scripts and JSON dumps. I sanitized the environment for production deployment.

- **Moved Files:**
  - All exploratory and unit test scripts (e.g., `find_shop_id.py`, `test_session.py`, `test_system.py`) were moved to `/tests`.
  - All raw JSON output dumps were moved to `/data`.
- **Sanitized `.env`:** 
  - Stripped out all hardcoded `COOKIES`, `X_CSRF_TOKEN`, and `SHOP_ID` values. 
  - The system is now 100% reliant on the Redis Cookie Vault for authentication. Added `REDIS_URL` as the primary configuration variable.

## 2. Resolving the Multi-Account Deadlock (Critical Architecture Fix)
Before my intervention, the `EtsyPrivateAPI` and `SessionManager` had a circular dependency and a multi-account flaw:

### The Problem:
1. **The Flaw:** `EtsyPrivateAPI.__init__` would scrape the Etsy dashboard *once* to find the `operator_shop_id` and `x-csrf-token`, and hardcode them into `self.headers` and `self.operator_shop_id`. But `SessionManager` dynamically rotates profiles from Redis on *every request*. If Profile A was hardcoded in `__init__`, but Profile B was grabbed for a request, Etsy would throw a 401/403.
2. **The Deadlock:** `SessionManager.auto_discover_shop_id()` tried to fetch the dashboard to find the `shop_id`. But `VaultGuardian` (in `core/cookie_vault.py`) was programmed to reject/drop any private profile that *didn't already have* a `shop_id` to prevent bans. 

### The Solution:
- **Relied on the Chrome Extension:** The Chrome Extension (`background.js`) already flawlessly intercepts `shop_id` (from URLs) and `x-csrf-token` (from headers) and POSTs them to the Go Cookie Server.
- **Deleted Python Auto-Discovery:** Completely removed `SessionManager.auto_discover_shop_id()` and removed dashboard scraping from `EtsyPrivateAPI.__init__`.
- **Dynamic Request Injection:** Modified `SessionManager._execute_with_retry()`. Now, when it pulls a specific profile from Redis, it reads the profile's `shop_id` and `csrf_token`. It dynamically replaces the `{shop_id}` template in the API URL and injects the `x-csrf-token` into the headers *for that specific request only*.

*Files changed: `core/session_manager.py`, `etsy/api/private/api.py`*

## 3. Resolving the IP/User-Agent Mismatch
### The Problem:
`SessionManager._build_session()` was hardcoding a Windows Chrome 124 User-Agent string. Meanwhile, the Chrome Extension was running on whatever the user's actual browser was. DataDome and Etsy could easily spot a mismatch between the cookies' origin, the TLS fingerprint (`curl_cffi` impersonation), and the hardcoded User-Agent.

### The Solution:
1. **Go Server Update:** Modified `cookie_server_go/main.go`. Added `UserAgent string` to the `Payload` struct and updated `updateCookieHandler` to parse it from the extension and save it to the Redis Hash.
2. **Python Update:** Modified `SessionManager._build_session()`. It now accepts `user_agent` as an argument. When `_execute_with_retry()` grabs a profile from Redis, it reads the exact `user_agent` string saved by the extension and injects it into the `curl_cffi` session. This perfectly aligns the session signature with the original cookie.

*Files changed: `cookie_server_go/main.go`, `core/session_manager.py`*

## 4. Current State & Workflow
If Claude is continuing the build (like the UI or further capabilities), note the following rules established by this cleanup:

1. **Isolation is mathematically enforced.** Public cookies (`etsy`) and private cookies (`etsy_private`) live in completely separate sets in Redis. The Python layer requests them explicitly via `platform="etsy"` or `platform="etsy_private"`. Do not break this.
2. **No hardcoded authentication.** Do not add global authentication parameters to API clients. Everything must be passed dynamically via `SessionManager._execute_with_retry()` relying on the specific profile checked out of the vault.
3. **Docker is the source of truth.** The infrastructure is managed by `docker-compose.yml`. The Go server is deployed alongside Redis and the Python scraper. The Python code runs inside a container, accessing Redis via the Docker network.

**Claude, proceed with the UI build or the next phase of the project brief using this stabilized foundation.**
