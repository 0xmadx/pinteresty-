import time
from typing import Dict
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from config.settings import ScraperConfig

class PlaywrightCookiePool:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.cookies: Dict[str, str] = {}
        self.last_refresh: float = 0

    def refresh(self):
        """Launches Playwright to fetch cookies from Etsy, solving challenges if needed."""
        print("Launching Playwright to fetch initial cookies. Please wait (and solve CAPTCHAs if they appear)...")
        
        try:
            with sync_playwright() as p:
                try:
                    # Launch chromium in headful mode to allow manual challenge solving
                    browser_kwargs = {"headless": self.config.PLAYWRIGHT_HEADLESS}
                    if self.config.USE_PROXY and self.config.PROXY_URL:
                        browser_kwargs["proxy"] = {"server": self.config.PROXY_URL}
                    browser = p.chromium.launch(**browser_kwargs)
                    context = browser.new_context(
                        # Use a standard user agent to avoid basic blocks before challenge
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                        viewport={"width": 1280, "height": 720}
                    )
                    page = context.new_page()
                    Stealth().apply_stealth_sync(page)
                except Exception as e:
                    print(f"[CookiePool] Critical Error initializing browser: {e}")
                    return
                
                try:
                    # Go to Etsy home page
                    page.goto(self.config.BASE_URL, timeout=self.config.PLAYWRIGHT_TIMEOUT)
                    
                    # Check for DataDome captcha
                    try:
                        page.wait_for_selector('iframe[src*="datadome"]', timeout=5000)
                        print("DataDome Captcha detected! Attempting to solve via CapSolver...")
                        
                        if self.config.CAPSOLVER_API_KEY:
                            try:
                                import capsolver
                                capsolver.api_key = self.config.CAPSOLVER_API_KEY
                                print("Waiting for CapSolver to complete...")
                                # capsolver.solve(...) goes here
                            except Exception as cap_e:
                                print(f"[CookiePool] CapSolver encountered an exception: {cap_e}")
                                print("Please solve manually in the browser window.")
                        else:
                            print("No CAPSOLVER_API_KEY provided. Please solve manually in the browser window.")
                            
                        # Wait for the main body to load (indicates successful pass of initial challenges)
                        page.wait_for_selector("body", timeout=self.config.PLAYWRIGHT_TIMEOUT)
                    except Exception:
                        # No captcha found or already solved
                        pass
                    
                    # Wait for the main body to load to ensure page is fully ready
                    try:
                        page.wait_for_selector("body", timeout=self.config.PLAYWRIGHT_TIMEOUT)
                    except Exception as wait_e:
                        print(f"[CookiePool] Timeout waiting for body to load: {wait_e}")
                    
                    # Sleep briefly to let any background scripts set tracking cookies
                    time.sleep(3)
                    
                    # Extract cookies from context
                    pw_cookies = context.cookies()
                    
                    # Convert list of dicts to a single dict for curl_cffi
                    self.cookies = {}
                    for cookie in pw_cookies:
                        self.cookies[cookie['name']] = cookie['value']
                        
                    self.last_refresh = time.time()
                    print(f"Successfully extracted {len(self.cookies)} cookies via Playwright.")
                except Exception as e:
                    print(f"[CookiePool] Playwright encountered a general error during navigation: {e}")
                finally:
                    try:
                        browser.close()
                    except Exception as close_e:
                        print(f"[CookiePool] Failed to gracefully close browser: {close_e}")
        except Exception as p_e:
            print(f"[CookiePool] Fatal Playwright error: {p_e}")

    def get_cookie_dict(self) -> Dict[str, str]:
        if not self.cookies or (time.time() - self.last_refresh > self.config.COOKIE_REFRESH_INTERVAL):
            self.refresh()
        return self.cookies

    def get_cookie_header(self) -> str:
        return "; ".join([f"{k}={v}" for k, v in self.get_cookie_dict().items()])
