import re
html = open("dashboard.html", encoding="utf-8").read()

patterns = [
    (r'shop_id["\s:=]+(\d+)', 'shop_id'),
    (r'shopId["\s:=]+(\d+)', 'shopId'),
    (r'data-shop-id=["\']?(\d+)', 'data-shop-id'),
    (r'shop/(\d+)', 'shop/'),
]

for p, name in patterns:
    if re.search(p, html):
        print(f"Matched {name}")
