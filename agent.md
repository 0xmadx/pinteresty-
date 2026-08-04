
---

# 🛰️ Antigravity Scraper

> A modular, browser-impersonating web scraping framework built on `curl_cffi` with live Chrome Canary cookie pooling.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Module Reference](#module-reference)
- [Cookie Pool](#cookie-pool)
- [Browser Impersonation](#browser-impersonation)
- [Development](#development)
- [Troubleshooting](#troubleshooting)

---

## Overview

Antigravity Scraper is a production-ready scraping framework designed to mimic real browser behavior as closely as possible. It extracts live cookies using a dynamically launched Playwright browser (with stealth injections) and uses `curl_cffi` to impersonate browser TLS/JA3 fingerprints — making detection significantly harder than standard `requests` or `httpx`.

### Key Features

| Feature | Description |
|---------|-------------|
| 🔐 **Playwright Stealth Auth** | Automatically defeats initial bot protections using `playwright-stealth` to grab live session cookies |
| 🎭 **Browser Impersonation** | Uses `curl_cffi` to match Chrome/Safari TLS & HTTP/2 signatures |
| 🧩 **CapSolver Integration** | Automatically detects and solves DataDome captchas via CapSolver API |
| 🌍 **Proxy Synchronization** | Injects identical proxies natively into both Playwright (cookie gathering) and the HTTP client (scraping) to prevent IP mismatch |
| 🛡️ **Robust Error Handling** | Fully wraps browser lifecycle and navigation in exception handlers for self-healing |
| 🧩 **Modular Design** | Clean separation of HTTP, parsing, and business logic |
| ⌨️ **Typing Simulation** | Simulates human keystroke patterns to evade behavioral detection |
| 🔁 **Auto-Refresh** | Automatically refreshes cookies on auth failure |
| 📦 **Typed Models** | Pydantic schemas for all data structures |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        main.py                               │
│                    (Entry Point)                             │
└───────────────────────┬─────────────────────────────────────┘
                        │
        ┌───────────────┼───────────────┐
        ▼               ▼               ▼
┌──────────────┐ ┌─────────────┐ ┌──────────────┐
│   Config     │ │ Cookie Pool │ │   Session    │
│  (settings)  │ │(Playwright) │ │   Factory    │
└──────┬───────┘ └──────┬──────┘ └──────┬───────┘
       │                │               │
       └────────────────┴───────────────┘
                          │
                          ▼
               ┌─────────────────────┐
               │   SearchService     │
               │  (Orchestration)    │
               └──────────┬──────────┘
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
    ┌────────────┐ ┌──────────┐ ┌──────────┐
    │   Search   │ │  Parser  │ │  Typing  │
    │   Client   │ │  (Soup)  │ │  Events  │
    │  (HTTP)    │ │ (Pure)   │ │ (Human)  │
    └────────────┘ └──────────┘ └──────────┘
```

### Separation of Responsibilities

| Layer | Responsibility | File |
|-------|---------------|------|
| **Config** | Constants, paths, timeouts | `config/settings.py` |
| **Core** | Cookie extraction, session building | `core/` |
| **Models** | Pydantic data validation | `models/schemas.py` |
| **Scraper** | HTTP requests & HTML parsing | `scraper/` |
| **Service** | Business logic & orchestration | `services/search_service.py` |

---

## Quick Start

```bash
# 1. Clone & enter directory
git clone <repo-url>
cd antigravity_scraper

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Run (a browser window will pop up briefly to grab auth cookies)

# 5. Run
python main.py
```

---

## Installation

### Prerequisites

- Python 3.10+
- Chrome Canary (installed and logged into target site)
- Windows / Linux / macOS

### Dependencies

```bash
pip install curl_cffi beautifulsoup4 lxml pydantic playwright playwright-stealth python-dotenv capsolver
playwright install chromium
```

Or use the provided `requirements.txt`:

```text
curl_cffi>=0.7.0
beautifulsoup4>=4.12.0
lxml>=5.0.0
pydantic>=2.0.0
playwright>=1.40.0
playwright-stealth>=1.0.6
python-dotenv>=1.0.0
capsolver>=1.0.1
```

### Environment Variables

Create a `.env` file in the root of the project to enable API solving and proxies:

```env
CAPSOLVER_API_KEY=your_api_key_here
USE_PROXY=False
PROXY_URL=http://user:pass@host:port
```

---

## Configuration

Edit `config/settings.py` to match your environment:

```python
@dataclass(frozen=True)
class ScraperConfig:
    # CapSolver Settings
    CAPSOLVER_API_KEY: str = os.environ.get("CAPSOLVER_API_KEY", "")
    
    # Proxy Settings (Critical for Akamai/DataDome)
    USE_PROXY: bool = os.environ.get("USE_PROXY", "False").lower() in ("true", "1", "t", "yes")
    PROXY_URL: str = os.environ.get("PROXY_URL", "") # Format: http://user:pass@host:port
    
    # Target site
    BASE_URL: str = "https://www.etsy.com"
    SEARCH_ENDPOINT: str = "/search"
    SUGGEST_ENDPOINT: str = "/api/v3/ajax/public/search/zero-pane-trending-searches/true"
    TYPING_SUGGEST_ENDPOINT: str = "/suggestions_ajax.php"
    
    # Browser fingerprint to impersonate
    BROWSER_FINGERPRINT: str = "chrome124"
    
    # Cookie refresh interval (seconds)
    COOKIE_REFRESH_INTERVAL: int = 3600
    
    # Request settings
    REQUEST_TIMEOUT: int = 30
    MAX_RETRIES: int = 3

    # Playwright Automation Settings
    PLAYWRIGHT_HEADLESS: bool = False # Keep headful to allow Captcha observation if API fails
    PLAYWRIGHT_TIMEOUT: int = 60000
```

### Available Fingerprints

| Fingerprint | Description |
|-------------|-------------|
| `chrome124` | Chrome 124 on Windows |
| `chrome125` | Chrome 125 on Windows |
| `safari17_2_1` | Safari 17.2.1 on macOS |
| `safari15_5` | Safari 15.5 on macOS |
| `firefox124` | Firefox 124 |

---

## Usage

### Basic Search

```python
from config.settings import ScraperConfig
from core.cookie_pool import PlaywrightCookiePool
from core.session_factory import ImpersonatedSession
from scraper.search_client import SearchClient
from scraper.parser import SearchParser
from services.search_service import SearchService

# Initialize
config = ScraperConfig()
cookie_pool = PlaywrightCookiePool(config)
session = ImpersonatedSession(config, cookie_pool)

# Build components
client = SearchClient(session, config)
parser = SearchParser()
service = SearchService(client, parser)

# Execute search
results = service.full_search_pipeline("your keyword", pages=2)

for page in results:
    for item in page.items:
        print(f"{item.title} -> {item.url}")
```

### Get Suggestions Only

```python
suggestions = client.get_suggestions("partial quer")
for s in suggestions:
    print(s.text)
```

### Query Discovery (SEO/Research)

```python
# Discover related queries up to 2 levels deep
discovered = service.discover_queries("seed keyword", depth=2)
print(discovered)
```

### Custom Parsing Selectors

```python
# If the site changes layout, update selectors without touching HTTP code
selectors = {
    "result_container": "div.search-result-item",
    "title": "h2.result-title",
    "url": "a.result-link",
    "description": "p.result-desc"
}

raw = client.search("query")
parsed = parser.parse_search_results(raw, selector_config=selectors)
```

---

## Module Reference

### `core/cookie_pool.py`

Uses Playwright and `playwright-stealth` to launch a real browser, navigate to the target site, wait for security checks to pass, and extract session cookies.

```python
cookie_pool = PlaywrightCookiePool(config)
cookie_pool.refresh()                    # Launches Playwright to get cookies
cookies = cookie_pool.get_cookie_dict()  # Dict for curl_cffi
header = cookie_pool.get_cookie_header() # Raw Cookie header string
```

### `core/session_factory.py`

Builds impersonated sessions with automatic retry and cookie refresh.

```python
session = ImpersonatedSession(config, cookie_pool)
response = session.get("https://example.com")
session.refresh_cookies()  # Force refresh
```

### `scraper/search_client.py`

Handles all HTTP operations. Stateless regarding parsing.

| Method | Purpose |
|--------|---------|
| `get_suggestions(query)` | Autocomplete API |
| `search(query, page)` | Main search GET |
| `simulate_typing(query)` | Human-like keystroke simulation |

### `scraper/parser.py`

Pure HTML parsing. No network calls.

```python
parser = SearchParser()
result = parser.parse_search_results(search_response)
token = parser.extract_csrf_token(html)
```

### `services/search_service.py`

High-level orchestration.

| Method | Description |
|--------|-------------|
| `full_search_pipeline(query, pages)` | Type → Suggest → Search → Parse |
| `quick_search(query)` | Search + parse only |
| `discover_queries(seed, depth)` | Recursive suggestion expansion |

---

## Cookie Pool

### How It Works

1. Launches a Chromium browser via Playwright (synchronizing proxy configuration with `curl_cffi`).
2. Injects evasions using `playwright-stealth` to remove automation signatures (e.g., `navigator.webdriver`).
3. Navigates to the target domain and evaluates the page for bot blocks.
4. If a DataDome or reCAPTCHA challenge is detected, it automatically attempts to solve it using the CapSolver API. If CapSolver fails or is unconfigured, it gracefully falls back to waiting for manual user intervention (if headful).
5. Extracts all cookies from the browser context and formats them for `curl_cffi`.
6. Safely closes the browser so scraping can continue swiftly in the background.

### Security Notes

- The initial browser automation handles JavaScript challenges that `curl_cffi` cannot execute.
- Once cookies are extracted, the heavy browser is closed, keeping resource usage extremely low.

### Manual Cookie Refresh

```python
# Refresh on demand
cookie_pool.refresh()
session.refresh_cookies()
```

---

## Browser Impersonation

### Why `curl_cffi`?

Standard libraries like `requests` or `httpx` have detectable TLS/JA3 fingerprints. `curl_cffi` impersonates real browsers by:

- Matching TLS cipher suites
- Matching JA3/JA4 fingerprints
- Matching HTTP/2 settings & headers
- Matching TLS extensions (ALPN, SNI, etc.)

### Verification

Test your fingerprint at:
- https://tls.browserleaks.com/json
- https://www.deviceinfo.me/

```python
# Test impersonation
response = session.get("https://tls.browserleaks.com/json")
print(response.json())
```

---

## Development

### Adding a New Scraper Module

1. Create a new client in `scraper/` inheriting from `BaseSearchScraper`
2. Implement `get_suggestions()`, `search()`, `simulate_typing()`
3. Add corresponding parser methods in `scraper/parser.py`
4. Wire into `SearchService` or create a new service

### Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
# Logs: cookie extraction, request retries, typing delays, parse results
```

### Testing

```bash
# Run with a test query
python -c "from main import main; main()"

# Test cookie extraction standalone
python test_playwright.py
```

---

## Troubleshooting

### "Playwright timeout or Captcha loop"

- Check if your `CAPSOLVER_API_KEY` is set in the `.env` file and has sufficient balance.
- If CapSolver is disabled, ensure `PLAYWRIGHT_HEADLESS = False` so you can manually solve challenges if DataDome blocks you.
- Ensure `USE_PROXY` is enabled if you are hitting IP rate limits.

### "401/403 Forbidden"

- Refresh cookies: `cookie_pool.refresh()`
- Check if session expired in Canary (re-login)
- Verify `BASE_URL` and endpoints are correct
- Try a different `BROWSER_FINGERPRINT`

### "Empty results"

- Inspect `response.raw_html` to see if HTML structure changed
- Update selectors in `SearchParser.parse_search_results()`
- Check if the site uses JavaScript rendering (may need additional handling)

### Slow performance

- Reduce `simulate_typing()` delays
- Disable typing simulation for batch jobs: use `quick_search()`
- Add connection pooling via `session.session`

---

## License

MIT License — use responsibly and in accordance with target site Terms of Service.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

<p align="center">
  Built with 🛰️ to fly under the radar.
</p>