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
    # db 0. This project used to mirror a shared db 0 into a private db 1
    # (core/vault_mirror.py, D-33) because pinterest-apify also read db 0. That
    # project now runs its own separate Redis (pinterest-redis, port 6380) and
    # never touches this database, so the mirror had nothing left to defend
    # against and was retired (D-49). This is the only vault now.
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

    # How many REAL accounts the operator runs, per platform (2026-08-14).
    # The vault counts profile *names*, and a browser re-saved under six names looks
    # like six profiles while being one session — so the name count says nothing about
    # capacity or identity diversity. These are the truth the count is measured
    # against: fewer distinct sessions than this means an account stopped syncing;
    # more means duplicates are accumulating.
    EXPECTED_SESSIONS: str = os.environ.get(
        "EXPECTED_SESSIONS", "etsy=1,etsy_private=1,pinterest=2")

    @property
    def expected_sessions(self) -> dict:
        out = {}
        for pair in self.EXPECTED_SESSIONS.split(","):
            if "=" not in pair:
                continue
            platform, _, count = pair.partition("=")
            try:
                out[platform.strip()] = int(count)
            except ValueError:
                continue
        return out
