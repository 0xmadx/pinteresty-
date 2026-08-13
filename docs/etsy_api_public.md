# Etsy Public API Layer

This directory contains the scraping clients designed to emulate a standard Google Chrome user browsing the public Etsy website. It is designed to navigate around Etsy's bot systems by utilizing standard requests, dynamic cookie injection, and HTML parsing.

## 1. `api.py` (The Core Client)
The central `EtsyPublicAPI` class.
* **Purpose:** Handles raw HTTP requests to Etsy's public HTML pages (e.g., search grids, shop pages).
* **Mechanism:** Automatically loads the `COOKIE` from the root `.env` file (which is constantly updated by the Chrome Extension relay) to bypass blocks.

## 2. `listing_api.py` (Listing Data Extractor)
Scrapes specific Etsy listing pages (`https://www.etsy.com/listing/ID`).
* **Purpose:** Extracts core metrics like `shop_name`, `favorites`, `in_cart`, exact `reviewCount` from LD+JSON, and hidden SEO tags.
* **💥 Live Demand Overrides:** Specifically utilizes BeautifulSoup to rip out dynamic, live urgency badges ("17 people bought this today", "In 20+ carts"). It uses Regex to parse these into exact integers (`daily_sales`, `daily_views`, `scarcity_stock`) so downstream pipelines can use hard math instead of guessing.

## 3. `reviews_api.py` (Deep-Dive Review Fetcher)
Extracts raw customer review text and dates.
* **Purpose:** Uses Etsy's internal, paginated API endpoint (`/api/v3/ajax/shop/ID/reviews`) to fetch up to 100 recent reviews for a listing.
* **Auth Requirement:** Requires a `csrf_token` extracted from the public HTML page by `listing_api.py` in order to successfully authenticate the request.
