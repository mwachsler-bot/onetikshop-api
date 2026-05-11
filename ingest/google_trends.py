"""
ingest/google_trends.py

DEPRECATED — pytrends removed.

pytrends is broken on server/datacenter IPs (Google 429 blocks).
This file is kept only as a compatibility shim.

All trend ingestion now uses:
  ingest/tiktok_shop_trends.py  — TikTok Creative Center + hashtags + keyword search
  ingest/google_trends_rss.py   — Google Trends RSS feed (general trending)

Do NOT import pytrends here. Do NOT use TrendReq.
"""
from ingest.tiktok_shop_trends import run_tiktok_product_trends as run_google_trends
from ingest.tiktok_shop_trends import DEFAULT_KEYWORDS

__all__ = ["run_google_trends", "DEFAULT_KEYWORDS"]
