# Etsy Sales Trackers

This module contains tools for estimating individual listing sales on Etsy, which Etsy hides from the public API and listing pages.

## Methodology

Etsy obscures exact views and sales for individual listings, but they **do** expose the **Total Sales** and **Total Reviews** for an entire Shop on their public homepage (e.g. `1,200 Sales`). 

We use two pipelines to calculate listing sales based on these shop-level metrics:

### 1. The Daily Tracker (`daily_tracker.py`)
Runs on a schedule (e.g. daily) to scrape the shop's total sales. By comparing today's total sales to yesterday's total sales, we can calculate the **Daily Sales Delta** (how many items the shop sold in the last 24 hours).

**Usage:**
```python
python daily_tracker.py
```
*Stores data locally in `tracking_data.json`.*

### 2. The Ratio Estimator (`ratio_estimator.py`)
Calculates the `Sales-to-Review Ratio` for a shop (Total Sales / Total Reviews). It then multiplies this ratio by a specific Listing's review count to estimate that listing's lifetime sales.

**Usage:**
```python
from etsy_trackers.ratio_estimator import estimate_listing_sales
estimate_listing_sales("LISTING_ID")
```

## Architecture
- `core/shop_scraper.py`: Contains the `ShopScraper` class which handles fetching and parsing the `shop-home-header` HTML to reliably extract the Total Sales and Total Reviews count, with fallback regex support for shops that hide their "sold history" link.
- `tracking_data.json`: A local JSON database holding the baseline and history of tracked shops for the Daily Tracker.

*(Note for Claude: If you are building automated pipelines or adding competitor analysis, you can import `ShopScraper` or `estimate_listing_sales` directly into your agents/pipelines).*
