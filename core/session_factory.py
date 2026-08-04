from curl_cffi import requests
from config.settings import ScraperConfig
from core.cookie_pool import PlaywrightCookiePool

class ImpersonatedSession:
    def __init__(self, config: ScraperConfig, cookie_pool: PlaywrightCookiePool):
        self.config = config
        self.cookie_pool = cookie_pool
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session(impersonate=self.config.BROWSER_FINGERPRINT)
        
        # Apply Proxy if configured
        if self.config.USE_PROXY and self.config.PROXY_URL:
            session.proxies = {"http": self.config.PROXY_URL, "https": self.config.PROXY_URL}
            
        # Akamai and Datadome strictly check that the TLS fingerprint (chrome124) perfectly
        # matches the HTTP User-Agent. We explicitly force the UA and basic browser headers 
        # to match what Playwright Stealth is using.
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        })
            
        # Update session cookies with what we extracted
        cookie_dict = self.cookie_pool.get_cookie_dict()
        if cookie_dict:
            for k, v in cookie_dict.items():
                session.cookies.set(k, v, domain=".etsy.com")
        return session

    def refresh_cookies(self):
        self.cookie_pool.refresh()
        cookie_dict = self.cookie_pool.get_cookie_dict()
        if cookie_dict:
            for k, v in cookie_dict.items():
                self.session.cookies.set(k, v, domain=".etsy.com")

    def _execute_with_retry(self, method, url, **kwargs):
        for attempt in range(self.config.MAX_RETRIES):
            if method == 'GET':
                response = self.session.get(url, **kwargs)
            else:
                response = self.session.post(url, **kwargs)
                
            # Check for bot block or auth failure
            if response.status_code in (401, 403, 429) or "datadome" in response.text.lower():
                print(f"Request blocked or unauthorized: {response.status_code} (attempt {attempt + 1}/{self.config.MAX_RETRIES}). Refreshing cookies...")
                self.refresh_cookies()
            else:
                return response
                
        # Return the last response even if it failed, so the caller can handle it
        return response

    def get(self, url, **kwargs):
        return self._execute_with_retry('GET', url, **kwargs)
        
    def post(self, url, **kwargs):
        return self._execute_with_retry('POST', url, **kwargs)
