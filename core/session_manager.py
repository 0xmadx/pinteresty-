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
        # How many 429s this session has seen. Read it after a run to answer, with
        # evidence, whether Etsy actually throttles — a question the whole pipeline's
        # quota-rationing design assumes an answer to but has never measured.
        self.rate_limited = 0

    def _build_session(self) -> requests.Session:
        # Impersonate Chrome 124 to pass TLS fingerprinting checks (Akamai/DataDome)
        session = requests.Session(impersonate=self.config.BROWSER_FINGERPRINT)
        
        # Apply Proxy if configured
        if self.config.USE_PROXY and self.config.PROXY_URL:
            session.proxies = {"http": self.config.PROXY_URL, "https": self.config.PROXY_URL}
            
        # Akamai and Datadome strictly check that the TLS fingerprint (chrome124) perfectly
        # matches the HTTP User-Agent. We explicitly force the UA and basic browser headers.
        import os, re
        from dotenv import load_dotenv
        load_dotenv()
        
        user_agent = os.getenv("BROWSER_USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        
        # Extract Chrome version from the User-Agent string
        chrome_version = "124"
        match = re.search(r"Chrome/(\d+)\.", user_agent)
        if match:
            chrome_version = match.group(1)
            
        session.headers.update({
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": f'"Chromium";v="{chrome_version}", "Google Chrome";v="{chrome_version}", "Not-A.Brand";v="99"',
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
                # OBSERVATION ONLY — the retry/cookie behaviour below is deliberately
                # unchanged (access layer). What is added is the ability to tell a rate
                # limit apart from a stale session, because they were indistinguishable:
                # every one of these printed "blocked or unauthorized" and then waited for
                # the extension to push a cookie. For a 429 that remedy does nothing, and
                # the caller ended up reading a throttle as an auth problem.
                #
                # This matters beyond diagnostics. The whole pipeline rations the private
                # API on the belief that it is quota-limited, and NOTHING in this system
                # has ever detected a limit — so the belief has never been tested. Naming
                # a 429 when it happens is what makes that testable.
                if response.status_code == 429:
                    self.rate_limited += 1
                    print(f"⚠️  RATE LIMITED (429) — this is Etsy throttling, NOT a stale "
                          f"cookie. Attempt {attempt + 1}/{self.config.MAX_RETRIES}. "
                          f"Refreshing the session will not help; slow down or back off.")
                else:
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
