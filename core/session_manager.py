import os
from curl_cffi import requests
from core.settings import ScraperConfig

class SessionManager:
    """
    Manages the curl_cffi session, strictly enforcing the Chrome124 TLS fingerprint
    and automatically injecting the DataDome cookie from the .env file.
    """
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        # Impersonate Chrome 124 to pass TLS fingerprinting checks (Akamai/DataDome)
        session = requests.Session(impersonate=self.config.BROWSER_FINGERPRINT)
        
        # Apply Proxy if configured
        if self.config.USE_PROXY and self.config.PROXY_URL:
            session.proxies = {"http": self.config.PROXY_URL, "https": self.config.PROXY_URL}
            
        # Akamai and Datadome strictly check that the TLS fingerprint (chrome124) perfectly
        # matches the HTTP User-Agent. We explicitly force the UA and basic browser headers.
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
                
        # Manually override DataDome cookie from config (.env)
        # We re-read it from os.environ directly in case the background server updated it recently
        datadome_cookie = os.environ.get("DATADOME_COOKIE", self.config.DATADOME_COOKIE)
        if datadome_cookie:
            session.cookies.set("datadome", datadome_cookie, domain=".etsy.com")
            
        return session

    def _execute_with_retry(self, method, url, cookies=None, **kwargs):
        for attempt in range(self.config.MAX_RETRIES):
            # 1. Apply endpoint-specific cookies (uaid, csrf, etc) from cURL
            if cookies:
                for k, v in cookies.items():
                    self.session.cookies.set(k, v, domain=".etsy.com")
                    
            # 2. Force the live DataDome cookie from .env
            current_cookie = os.environ.get("DATADOME_COOKIE")
            if current_cookie:
                self.session.cookies.set("datadome", current_cookie, domain=".etsy.com")
                
            if method.upper() == 'GET':
                response = self.session.get(url, **kwargs)
            else:
                response = self.session.post(url, **kwargs)
                
            # Check for bot block or auth failure
            if response.status_code in (401, 403, 429) or "datadome" in response.text.lower():
                print(f"Request blocked or unauthorized: {response.status_code} (attempt {attempt + 1}/{self.config.MAX_RETRIES}).")
                # Wait for the user's extension to automatically sync a new cookie
                if attempt < self.config.MAX_RETRIES - 1:
                    import time
                    print("Waiting 5s to see if Chrome extension pushes a new cookie to .env...")
                    time.sleep(5)
                    from dotenv import load_dotenv
                    load_dotenv(override=True)
            else:
                return response
                
        # Return the last response even if it failed, so the caller can handle it
        return response

    def get(self, url, cookies=None, **kwargs):
        return self._execute_with_retry('GET', url, cookies=cookies, **kwargs)
        
    def post(self, url, cookies=None, **kwargs):
        return self._execute_with_retry('POST', url, cookies=cookies, **kwargs)

    def request(self, method, url, cookies=None, **kwargs):
        return self._execute_with_retry(method, url, cookies=cookies, **kwargs)
