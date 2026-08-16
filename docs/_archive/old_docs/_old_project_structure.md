# Etsy Arbitrage Engine: Project Structure

This document outlines the entire architecture of the repository. The system is designed to be highly modular, separating the raw scraping APIs from the analytical math pipelines and the high-level orchestration engines.

## 📂 Root Directory
* **`market_intelligence.db`**: The central SQLite database (The Brain). All engines, scrapers, and AI models read and write to this single source of truth.
* **`.env`**: Contains all your secret keys (DeepSeek API) and the dynamic `DATADOME_COOKIE` injected by the Chrome Extension relay.
* **`pinterest_cookies.json`**: Contains the live Pinterest Auth tokens injected by the Chrome Extension relay.

## 📂 /core (Foundational Utilities)
Shared utilities that power the entire architecture.
* **`database.py`**: The SQLite schema and `MarketDatabase` client for reading/upserting data.
* **`cookie_server.py`**: A FastAPI relay server that listens for incoming cookies from the Chrome Extension and updates local files.
* **`llm_client.py`**: The dedicated DeepSeek AI wrapper.
* **`shop_scraper.py`**: Scrapes shop lifetime metrics to calculate "Sales Ratios".

## 📂 /etsy (The Etsy Scraping Engine)
The primary logic for interacting with the Etsy marketplace.

### `/etsy/api` (The Extractors)
* **`/public`**: Tools to scrape public HTML (Search Grids, Listing Pages). Utilizes the `DATADOME_COOKIE` to bypass bot protection. Extracts **Live Demand Signals** (e.g., "17 bought today").
* **`/private`**: Tools to spoof Etsy's internal iOS/Android apps using `tls_client`. Used to pull hidden **True CVR** and **Search Volume**.

### `/etsy/analytics` (The Math Pipelines)
Transforms raw HTML into structured arbitrage metrics.
* **`single_listing_analytics.py`**: Analyzes a single listing to estimate or calculate its exact lifetime/monthly sales and velocity.
* **`grid_analytics.py`**: Batch-analyzes the top 10 competitors for a keyword to calculate total market saturation and sales velocity.
* **`sentiment_analytics.py`**: Scrapes negative reviews and feeds them to DeepSeek to identify the Top 3 Product Flaws.
* **`seo_analytics.py`**: Extracts the exact 13 Tags and Materials used by a listing to rank on Page 1.

### `/etsy/engines` (The Orchestrators)
The "Master" scripts that chain multiple analytical pipelines together.
* **`master_arbitrage.py`**: The Hybrid Engine. Pulls Private CVR/Volume, Pulls Public Saturation, calculates the Arbitrage Gap, and generates a 7-Dimensional Score.
* **`master_listing_analyzer.py`**: The X-Ray Tool. You drop a URL, and it sequentially runs Single Listing, Sentiment, and SEO analytics.
* **`private_blueprint.py`**: The Niche Finder. Recursively spiders the Private API autosuggest to find thousands of hidden "Blue Ocean" keywords.

### `/etsy/generators` (The AI Copywriters)
* **`listing_generator.py`**: Ingests the competitor's SEO Tags and DeepSeek Flaws to automatically generate a superior, highly-optimized Title, Description, and Tag list.

## 📂 /pinterest (The Trend Synergy Engine)
Managed by Claude Code, this folder contains the logic for predictive trend analysis.
* Designed to track demographic and aesthetic trends (dominant colors, fashion waves) and save them to `market_intelligence.db` so you can verify if an Etsy supply gap aligns with a Pinterest demand spike.

## 📂 /chrome_extension (The Keep-Alive )
A custom Google Chrome Extension.
* **`background.js`**: Keeps Etsy and Pinterest tabs open in your browser, automatically refreshing them every 4 minutes.
* **Purpose**: Forces your browser to naturally generate fresh DataDome and Auth cookies, which are then immediately POSTed to the `cookie_server.py` relay in the `/core` directory.

## 📂 /docs (Documentation)
Contains all detailed breakdown files for the specific directories listed above:
* `core_architecture.md`
* `etsy_analytics.md`
* `etsy_api_public.md`
* `etsy_api_private.md`
* `etsy_engines.md`
* `etsy_generators.md`
