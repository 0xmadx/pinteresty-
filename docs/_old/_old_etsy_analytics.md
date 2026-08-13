




# Etsy Analytics Pipelines

This directory contains the 4 core data extraction and calculation pipelines. They form the backbone of the "Public API Scraping Layer", transforming raw HTML into structured arbitrage data and saving it directly into the central `market_intelligence.db`.

## 1. `single_listing_analytics.py` (The Target Sniper)
Analyzes a single Etsy listing to calculate its precise financial metrics.

* **Input:** A specific 10-digit Listing ID and the Private CVR (defaults to 0.02).
* **How It Works:**
  1. Scrapes the listing page for basic info (Favorites, In Cart).
  2. Scrapes the Shop's Total Sales and Total Reviews to generate a "Sales Ratio".
  3. Estimates Lifetime Sales by multiplying the listing's exact Review Count by the Shop's Sales Ratio.
  4. Scrapes recent review dates to calculate current "Velocity" (Hot, Steady, Slow).
* **💥 Live Demand Override:** Actively scans the HTML for urgency badges (e.g., *"17 people bought this today"*, *"In 20+ carts"*, *"Only 3 left"*). If a daily sales badge is found, it completely ignores the "Sales Ratio" guess and uses exact math to project a 30-day run rate.
* **Output:** Saves metrics (`price`, `est_sales`, `est_views`, `velocity`, `daily_sales`, `scarcity_stock`) to the `listings` table in `market_intelligence.db`.

## 2. `grid_analytics.py` (The Competitor Batch Scanner)
Runs a batch analysis on a specific Etsy search keyword to size up the competition.

* **Input:** A seed keyword (e.g., "leather journal") and optional search filters.
* **How It Works:**
  1. Pulls the top ranking listings for the keyword.
  2. Automates Phase 1 through 3 of `single_listing_analytics` for every single competitor found in the grid.
  3. Scrapes all unique shops in a single batch to drastically reduce network requests.
* **💥 Live Demand Override:** Every single competitor in the grid is scanned for Live Demand signals. If a competitor has a "Daily Sales" badge, their estimated sales are overridden with hard math.
* **Output:** Upserts the exact market landscape into the `listings` table in `market_intelligence.db`.

## 3. `sentiment_analytics.py` (The DeepSeek Review Analyst)
Uses AI to identify the biggest flaws in a competitor's product so you can build a better version.

* **Input:** A specific 10-digit Listing ID.
* **How It Works:**
  1. Utilizes the hidden `deep_dive_reviews` GraphQL endpoint to fetch a massive payload of up to 100 recent reviews.
  2. Filters out the 5-star reviews and isolates negative feedback (1 to 4 stars).
  3. Pipes the negative text directly to the DeepSeek API.
  4. DeepSeek generates a hyper-concise, 3-bullet-point summary of the product's top flaws (e.g., *"Clasp breaks easily", "Smaller than advertised"*).
* **Output:** Saves the Top 3 Flaws text directly to the `top_flaws` column in the `listings` table.

## 4. `seo_analytics.py` (The Reverse-Engineer)
Extracts the exact tags and materials a competitor is using to rank on page 1.

* **Input:** A specific 10-digit Listing ID.
* **How It Works:**
  1. Scrapes the raw HTML page and targets the hidden SEO tags.
  2. Extracts the exact 13 Tags and Materials used by the seller.
* **Output:** Generates a JSON report in `seo/cache/` containing the exact blueprint for how the listing ranks organically.
