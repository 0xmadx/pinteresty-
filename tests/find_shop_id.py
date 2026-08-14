import re
html = open("dashboard.html", encoding="utf-8").read()

# Look for patterns like "shopId": 12345 or "shop_id": "12345" or data-shop-id="12345"
patterns = [
    r'shop_id["\s:=]+(\d+)',
    r'shopId["\s:=]+(\d+)',
    r'data-shop-id=["\']?(\d+)',
    r'shop/(\d+)',
]

found = set()
for p in patterns:
    matches = re.findall(p, html)
    found.update(matches)

print("Found shop IDs:", list(found))

# Also let's find the user_id just in case
print("User ID:", re.search(r'data-user-id=["\']?(\d+)', html).group(1) if re.search(r'data-user-id=["\']?(\d+)', html) else "None")
