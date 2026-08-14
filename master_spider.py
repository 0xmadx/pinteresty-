import concurrent.futures
import time
import argparse
import os
import json
from etsy.engines.master_niche_finder import MasterNicheFinder
from core.settings import ScraperConfig

def process_keyword(keyword, max_depth, max_nodes, deep_dive_limit):
    """
    Worker function to process a single keyword using MasterNicheFinder.
    """
    print(f"\n🚀 [MASTER SPIDER] Thread started for keyword: '{keyword}'")
    start_time = time.time()
    
    try:
        # Initialize the engine for this specific keyword
        engine = MasterNicheFinder(
            seed_keyword=keyword,
            max_depth=max_depth,
            max_nodes=max_nodes,
            deep_dive_limit=deep_dive_limit
        )
        
        # Run the crawl
        report = engine.run()
        
        elapsed = time.time() - start_time
        print(f"✅ [MASTER SPIDER] Completed '{keyword}' in {elapsed:.2f}s")
        return {"keyword": keyword, "status": "success", "report": report, "elapsed": elapsed}
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"❌ [MASTER SPIDER] Failed on '{keyword}': {str(e)}")
        return {"keyword": keyword, "status": "error", "error": str(e), "elapsed": elapsed}

from core.cookie_vault import RedisCookieVault

def wait_for_minimum_profiles(config: ScraperConfig, platform: str = "etsy", min_profiles: int = 3):
    """
    Blocks execution until the Redis vault has at least `min_profiles` working profiles for the given platform.
    """
    vault = RedisCookieVault(config)
    valid_set_key = f"valid_profiles:{platform}"
    
    print(f"\n🛡️ [PRE-FLIGHT CHECK] Checking for at least {min_profiles} valid '{platform}' profiles...")
    while True:
        count = vault.redis_client.scard(valid_set_key)
        if count >= min_profiles:
            print(f"✅ [PRE-FLIGHT CHECK] Passed! Found {count} valid profiles. Starting engines...")
            break
        print(f"⏳ [PRE-FLIGHT CHECK] Only found {count}/{min_profiles} valid profiles for '{platform}'. Waiting 5 seconds...")
        time.sleep(5)

def run_master_spider(keywords, max_workers=3, max_depth=2, max_nodes=50, deep_dive_limit=None):
    """
    Executes the MasterNicheFinder concurrently across a list of keywords.
    """
    # Wait for at least 3 profiles before we even start the engine
    config = ScraperConfig()
    wait_for_minimum_profiles(config, platform="etsy", min_profiles=3)

    print(f"\n=======================================================")
    print(f"🕸️  STARTING MASTER SPIDER CONCURRENT CRAWL")
    print(f"=======================================================")
    print(f"Target Keywords: {len(keywords)}")
    print(f"Max Workers: {max_workers}")
    print(f"Max Depth: {max_depth}")
    print(f"Max Nodes: {max_nodes}")
    print(f"Deep Dive Limit: {'Unlimited' if deep_dive_limit is None else deep_dive_limit}")
    print(f"=======================================================\n")
    
    results = []
    
    # Use ThreadPoolExecutor for concurrent I/O bound requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all jobs
        future_to_kw = {
            executor.submit(process_keyword, kw, max_depth, max_nodes, deep_dive_limit): kw 
            for kw in keywords
        }
        
        # Process results as they complete
        for future in concurrent.futures.as_completed(future_to_kw):
            kw = future_to_kw[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                print(f"⚠️ [MASTER SPIDER] Thread generated an exception for '{kw}': {exc}")
                results.append({"keyword": kw, "status": "fatal_error", "error": str(exc)})
                
    # Summary Report
    print(f"\n=======================================================")
    print(f"🏁 MASTER SPIDER RUN COMPLETE")
    print(f"=======================================================")
    
    successes = [r for r in results if r.get("status") == "success"]
    errors = [r for r in results if r.get("status") != "success"]
    
    print(f"Successfully scraped: {len(successes)} niches")
    print(f"Failed: {len(errors)} niches")
    
    if errors:
        print("\nErrors encountered:")
        for err in errors:
            print(f" - {err['keyword']}: {err.get('error')}")
            
    # Save a summary of the whole run
    os.makedirs("etsy/data/reports", exist_ok=True)
    timestamp = int(time.time())
    summary_path = f"etsy/data/reports/master_spider_summary_{timestamp}.json"
    
    summary = {
        "timestamp": timestamp,
        "keywords_processed": len(keywords),
        "success_count": len(successes),
        "error_count": len(errors),
        "results": results
    }
    
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)
        
    print(f"\nDetailed summary saved to: {summary_path}")
    print(f"=======================================================\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Master Spider concurrently across multiple keywords.")
    parser.add_argument("--keywords", nargs="+", required=True, help="List of seed keywords to scrape")
    parser.add_argument("--workers", type=int, default=3, help="Number of concurrent worker threads")
    parser.add_argument("--depth", type=int, default=2, help="Max depth for BFS crawl")
    parser.add_argument("--nodes", type=int, default=50, help="Max nodes per seed keyword")
    parser.add_argument("--limit", type=int, default=None, help="Deep dive limit (default: no limit)")
    
    args = parser.parse_args()
    
    run_master_spider(
        keywords=args.keywords,
        max_workers=args.workers,
        max_depth=args.depth,
        max_nodes=args.nodes,
        deep_dive_limit=args.limit
    )
