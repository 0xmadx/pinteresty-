import re
import json
from pathlib import Path

bash_path = Path("pinterest/endpoints/request-example.sh")
with open(bash_path, "r", encoding="utf-8") as f:
    content = f.read()

match = re.search(r"-b '([^']+)'", content)
if match:
    cookie_str = match.group(1)
    cookies = {}
    for item in cookie_str.split(';'):
        item = item.strip()
        if not item: continue
        if '=' in item:
            k, v = item.split('=', 1)
            cookies[k.strip()] = v.strip()
            
    with open("pinterest_cookies.json", "w") as f:
        json.dump({
            "cookie_string": cookie_str,
            "cookie_json": cookies
        }, f, indent=4)
    print("✅ Extracted cookies from bash file to pinterest_cookies.json")
else:
    print("❌ Could not find cookie string in bash file.")
