import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

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
    # From search_suggesstion.py
    SUGGEST_ENDPOINT: str = "/api/v3/ajax/public/search/zero-pane-trending-searches/true"
    # From typing_search suggestion.py
    TYPING_SUGGEST_ENDPOINT: str = "/suggestions_ajax.php"
    
    # Browser fingerprint to impersonate with curl_cffi
    BROWSER_FINGERPRINT: str = "chrome124"
    
    # Manual Cookie Override
    DATADOME_COOKIE: str = os.environ.get("DATADOME_COOKIE", "")
    
    # Playwright Persistent Context (Use local profile to avoid Windows lock issues)
    CHROME_EXECUTABLE_PATH: str = r"C:\Users\0xdevy\AppData\Local\Google\Chrome SxS\Application\chrome.exe"
    # Pointing to a local folder so we don't collide with the user's running browser
    CHROME_USER_DATA_DIR: str = r"C:\Users\0xdevy\Desktop\eso esty\data\chrome_profile"
    
    # Cookie refresh interval (seconds)
    COOKIE_REFRESH_INTERVAL: int = 3600 # Wait an hour between playwright runs
    
    # Request settings
    REQUEST_TIMEOUT: int = 30
    MAX_RETRIES: int = 3
    
    # Playwright Automation Settings
    PLAYWRIGHT_HEADLESS: bool = False # Keep headful to solve Captcha/DataDome
    PLAYWRIGHT_TIMEOUT: int = 60000 # Wait 60s for user to solve challenge if needed
