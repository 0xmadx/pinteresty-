# Core Directory

This directory contains the foundational, shared utilities that power the entire architecture. Rather than executing scraping pipelines themselves, these scripts provide the central database, AI, and Anti-Bot services that the `etsy/` and `pinterest/` engines rely on.

## 1. `database.py` (The Central Intelligence)
The single source of truth for the entire arbitrage system.
* **Purpose:** Uses SQLite to maintain `market_intelligence.db`, permanently unifying the silos of Private Etsy Data, Public Competitor Data, DeepSeek Flaws, and Pinterest Trends.
* **Key Tables:** 
  * `keywords`: Stores Volume, Competition, and Private CVR.
  * `listings`: Stores exact estimated sales, velocity, and AI-identified flaws.
  * `trends`: Stores the demographic and aesthetic trend data mapped by Claude Code on Pinterest.

## 2. `cookie_server.py` (The Anti-Bot Relay)
The backbone of our automated cookie-syncing strategy.
* **Purpose:** A local FastAPI server (`localhost:8000`) that constantly listens for incoming POST requests from the custom Chrome Extension.
* **How It Works:** When the Chrome Extension detects a freshly minted DataDome cookie or Pinterest auth token, it beams it to this server. This script then programmatically updates the `.env` file and `pinterest_cookies.json`, allowing the Python scrapers to completely bypass bot-protection without manual intervention.

## 3. `llm_client.py` (The DeepSeek Wrapper)
A dedicated, decoupled client for interacting with AI.
* **Purpose:** Currently configured specifically for the DeepSeek API. It is used by `sentiment_analytics.py` to process massive batches of negative customer reviews and output hyper-concise 3-bullet-point summaries of a product's biggest flaws. 

## 4. `shop_scraper.py`
A modular utility script.
* **Purpose:** Takes an Etsy shop name and scrapes its overall lifetime `total_sales` and `total_reviews`. This allows the pipeline to calculate a "Sales Ratio" to estimate listing-level sales when "Live Demand" badges aren't present.

## 5. Other Utilities
* `graph_db.py`: Foundational graph logic for mapping out semantic keyword webs.
* `session_manager.py` & `endpoints_manager.py`: Base networking configurations for managing HTTP sessions and headers.
