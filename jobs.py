"""
jobs.py - Scheduled ingestion and scoring job functions.
No cron dependency. Connect to Render cron, GitHub Actions, or APScheduler.
Usage: python jobs.py --job all|trends|meta|tiktok|amazon|score

NOTE: pytrends removed. Now uses google_trends_rss (RSS + optional CSE).
Works reliably on Render/server IPs without Google 429 blocks.
"""
import logging
import argparse
from datetime import datetime, timezone
from database import upsert
from scoring import score_all_products
from ingest.google_trends_rss import run_google_trends, DEFAULT_KEYWORDS
from ingest.meta_ad_library import run_meta_ingestion
from ingest.tiktok_creative_center import run_tiktok_ingestion
from ingest.amazon_data import run_amazon_ingestion

log = logging.getLogger(__name__)
DEFAULT_NICHE_KEYWORDS = list(DEFAULT_KEYWORDS)


def _save_records(table: str, records: list) -> int:
    """Batch upsert records to Supabase. Returns count saved."""
    if not records:
        return 0
    saved = 0
    for i in range(0, len(records), 50):
        batch = records[i:i+50]
        try:
            upsert(table, batch)
            saved += len(batch)
        except Exception as e:
            log.error(f"Failed to save batch to {table}: {e}")
    return saved


def run_google_trends_ingestion(keywords=None) -> dict:
    """
    Pull trend data via Google Trends RSS feed.
    No API key needed. Works on all server IPs.
    Optionally enriched with Google CSE if GOOGLE_CSE_API_KEY is set.
    """
    log.info("=== JOB: Google Trends (RSS) ===")
    records = run_google_trends(keywords or DEFAULT_NICHE_KEYWORDS)
    saved = _save_records("trends", records)
    log.info(f"Google Trends done: {saved} records saved.")
    return {"source": "google_trends_rss", "records_saved": saved}


def run_meta_ingestion_job(keywords=None, niche=None) -> dict:
    log.info("=== JOB: Meta Ad Library ===")
    kw_list = keywords or [kw for kw, _ in DEFAULT_NICHE_KEYWORDS]
    result = run_meta_ingestion(kw_list, niche=niche)
    ads   = _save_records("competitor_ads", result.get("competitor_ads", []))
    hooks = _save_records("hooks",          result.get("hooks", []))
    log.info(f"Meta done: {ads} ads, {hooks} hooks.")
    return {"source": "meta", "ads_saved": ads, "hooks_saved": hooks}


def run_tiktok_ingestion_job(keywords=None, niche=None) -> dict:
    log.info("=== JOB: TikTok ===")
    kw_list = keywords or [kw for kw, _ in DEFAULT_NICHE_KEYWORDS]
    result = run_tiktok_ingestion(kw_list, niche=niche)
    ads   = _save_records("competitor_ads", result.get("competitor_ads", []))
    hooks = _save_records("hooks",          result.get("hooks", []))
    log.info(f"TikTok done: {ads} ads, {hooks} hooks.")
    return {"source": "tiktok", "ads_saved": ads, "hooks_saved": hooks}


def run_amazon_ingestion_job(keywords=None, niche=None) -> dict:
    log.info("=== JOB: Amazon ===")
    kw_list = keywords or [kw for kw, _ in DEFAULT_NICHE_KEYWORDS]
    result = run_amazon_ingestion(kw_list, niche=niche)
    saved = _save_records("product_market_data", result.get("product_market_data", []))
    log.info(f"Amazon done: {saved} saved.")
    return {"source": "amazon", "records_saved": saved}


def run_product_scoring() -> dict:
    log.info("=== JOB: Product Scoring ===")
    results = score_all_products()
    log.info(f"Scoring done: {len(results)} products.")
    return {"products_scored": len(results)}


def run_all_ingestions(keywords=None) -> dict:
    """Run all ingestion sources then score. Safe to call as a daily cron."""
    log.info("=== JOB: Full Ingestion Pass ===")
    started = datetime.now(timezone.utc).isoformat()
    summary = {}
    summary["google_trends"] = run_google_trends_ingestion(keywords)
    summary["meta"]          = run_meta_ingestion_job(keywords)
    summary["tiktok"]        = run_tiktok_ingestion_job(keywords)
    summary["amazon"]        = run_amazon_ingestion_job(keywords)
    summary["scoring"]       = run_product_scoring()
    summary["started_at"]    = started
    summary["completed_at"]  = datetime.now(timezone.utc).isoformat()
    return summary


if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="OneTikShop MI Jobs")
    parser.add_argument("--job", choices=["all","trends","meta","tiktok","amazon","score"], default="all")
    parser.add_argument("--keyword", type=str, help="Single keyword to ingest")
    parser.add_argument("--niche",   type=str, help="Niche label")
    args = parser.parse_args()
    kw = [(args.keyword, args.niche or "unknown")] if args.keyword else None
    if   args.job == "all":    print(run_all_ingestions(kw))
    elif args.job == "trends": print(run_google_trends_ingestion(kw))
    elif args.job == "meta":   print(run_meta_ingestion_job([k for k,_ in kw] if kw else None, args.niche))
    elif args.job == "tiktok": print(run_tiktok_ingestion_job([k for k,_ in kw] if kw else None, args.niche))
    elif args.job == "amazon": print(run_amazon_ingestion_job([k for k,_ in kw] if kw else None, args.niche))
    elif args.job == "score":  print(run_product_scoring())
