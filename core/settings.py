import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class ScraperConfig:
    # Proxy Settings (Critical for Akamai/DataDome)
    USE_PROXY: bool = os.environ.get("USE_PROXY", "False").lower() in ("true", "1", "t", "yes")
    PROXY_URL: str = os.environ.get("PROXY_URL", "") # Format: http://user:pass@host:port
    
    # Redis Settings (replaces .env for cookies)
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    # Target site
    BASE_URL: str = "https://www.etsy.com"
    SEARCH_ENDPOINT: str = "/search"
    # From search_suggesstion.py
    SUGGEST_ENDPOINT: str = "/api/v3/ajax/public/search/zero-pane-trending-searches/true"
    # From typing_search suggestion.py
    TYPING_SUGGEST_ENDPOINT: str = "/suggestions_ajax.php"
    
    # Browser fingerprint to impersonate with curl_cffi
    BROWSER_FINGERPRINT: str = "chrome124"
    
    # Manual Cookie Override — refreshed by core/cookie_server.py + the Chrome extension,
    # the ONLY session-sync mechanism in this project. Browser automation (Playwright et
    # al.) is prohibited; its dead config was removed 2026-08-11 (F-14).
    DATADOME_COOKIE: str = os.environ.get("DATADOME_COOKIE", "")

    # Request settings
    REQUEST_TIMEOUT: int = 30
    MAX_RETRIES: int = 3
