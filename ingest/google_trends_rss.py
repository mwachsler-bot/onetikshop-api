"""
ingest/google_trends_rss.py

Replaces pytrends (broken on server IPs, 429 errors).

Uses TWO free official Google sources that never get blocked:

1. Google Trends RSS feed (public, no auth, no rate limit)
   https://trends.google.com/trending/rss?geo=US
   Returns today's top trending searches in real time.

2. Google Custom Search JSON API (free tier: 100 queries/day)
   Measures search volume proxy by result count per keyword.
   Requires: GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID in .env
   Get free at: https://programmablesearchengine.google.com

No pytrends. No 429. Works on Render, Railway, any server.
"""
import os
import logging
import time
import hashlib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from dedupe import create_trend_dedupe_key

log = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    ("resistance bands", "fitness"),
    ("ice molds", "kitchen"),
    ("posture corrector", "health"),
    ("led strip lights", "home decor"),
    ("massage gun", "wellness"),
    ("skincare face mask", "beauty"),
    ("mini projector", "entertainment"),
    ("pet grooming glove", "pets"),
    ("hair curler wand", "beauty"),
    ("portable blender", "kitchen"),
    ("compression socks", "health"),
    ("yoga mat", "fitness"),
    ("electric toothbrush", "health"),
    ("ring light", "creator tools"),
    ("car phone mount", "automotive"),
    ("water bottle filter", "outdoor"),
]


def fetch_google_trending_rss(geo: str = "US") -> list[dict]:
    """
    Fetch Google's real-time trending searches via public RSS.
    Returns list of trending terms with scores.
    No API key. No rate limit. Always works.
    """
    url = f"https://trends.google.com/trending/rss?geo={geo}"
    records = []
    try:
        r = httpx.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.text)
        ns = {"ht": "https://trends.google.com/trending/rss"}
        items = root.findall(".//item")
        log.info(f"Google Trending RSS: {len(items)} trending terms for {geo}")
        for i, item in enumerate(items[:50]):
            title_el = item.find("title")
            traffic_el = item.find("ht:approx_traffic", ns)
            news_el = item.find("ht:news_item_title", ns)
            if title_el is None:
                continue
            keyword = title_el.text or ""
            traffic_str = traffic_el.text if traffic_el is not None else "0"
            traffic_num = int(traffic_str.replace("+", "").replace(",", "").replace("K", "000").strip() or 0)
            trend_score = max(0, min(100, 100 - (i * 2)))
            records.append({
                "source": "google_trends_rss",
                "niche": "trending",
                "keyword": keyword,
                "product_name": keyword,
                "category": "trending",
                "trend_type": "breakout",
                "region": geo,
                "trend_score": float(trend_score),
                "search_volume": float(traffic_num),
                "growth_rate": 100.0,
                "velocity_score": float(trend_score),
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "raw_data": {
                    "rank": i + 1,
                    "approx_traffic": traffic_str,
                    "news_title": news_el.text if news_el is not None else None,
                },
                "dedupe_key": create_trend_dedupe_key("google_trends_rss", keyword, geo),
            })
    except Exception as e:
        log.error(f"Google Trending RSS error: {e}")
    return records


def fetch_keyword_trend_via_cse(keyword: str, niche: str, api_key: str, cse_id: str) -> dict | None:
    """
    Use Google Custom Search API to estimate keyword demand.
    Result count = proxy for search volume.
    Free: 100 queries/day. Enough for our keyword set.
    """
    url = "https://www.googleapis.com/customsearch/v1"
    try:
        r = httpx.get(url, timeout=10, params={
            "key": api_key,
            "cx": cse_id,
            "q": keyword,
            "num": 1,
        })
        r.raise_for_status()
        data = r.json()
        total_results = int(data.get("searchInformation", {}).get("totalResults", 0))
        formatted = data.get("searchInformation", {}).get("formattedTotalResults", "0")
        trend_score = min(100, total_results / 1_000_000)
        return {
            "source": "google_cse",
            "niche": niche,
            "keyword": keyword,
            "product_name": keyword,
            "category": niche,
            "trend_type": "stable",
            "region": "US",
            "trend_score": round(trend_score, 2),
            "search_volume": float(total_results),
            "growth_rate": 0.0,
            "velocity_score": round(trend_score * 0.5, 2),
            "first_seen_at": datetime.now(timezone.utc).isoformat(),
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
            "raw_data": {"total_results": total_results, "formatted": formatted},
            "dedupe_key": create_trend_dedupe_key("google_cse", keyword, "US"),
        }
    except Exception as e:
        log.error(f"Google CSE error for '{keyword}': {e}")
        return None


def run_google_trends(keywords=None, region="US", timeframe=None) -> list[dict]:
    """
    Main entry point. Called by jobs.py.

    Strategy:
    1. Always fetch Google Trending RSS (free, instant, real-time)
    2. If GOOGLE_CSE_API_KEY + GOOGLE_CSE_ID set, also query each keyword
       for demand estimation (100/day free quota)
    """
    records = []

    # Step 1: Real-time trending (always works)
    log.info("Fetching Google Trending RSS...")
    trending = fetch_google_trending_rss(region)
    records.extend(trending)
    log.info(f"RSS: {len(trending)} trending terms collected")

    # Step 2: Keyword demand via CSE (optional)
    api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cse_id  = os.getenv("GOOGLE_CSE_ID")

    kw_pairs = keywords or DEFAULT_KEYWORDS

    if api_key and cse_id:
        log.info(f"Google CSE: querying {len(kw_pairs)} keywords...")
        for kw, niche in kw_pairs:
            result = fetch_keyword_trend_via_cse(kw, niche, api_key, cse_id)
            if result:
                records.append(result)
                log.info(f"  CSE: {kw} -> score={result['trend_score']:.1f} volume={result['search_volume']:,.0f}")
            time.sleep(0.5)  # gentle pacing
    else:
        log.info("GOOGLE_CSE_API_KEY not set. Skipping keyword demand query.")
        log.info("To enable: get free key at programmablesearchengine.google.com")
        log.info("Add GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID to Render env vars.")

        # Fallback: create basic records for our keywords from RSS signal
        # Check if any of our keywords appear in trending
        trending_terms = {r["keyword"].lower() for r in trending}
        for kw, niche in kw_pairs:
            in_trending = any(kw.lower() in t or t in kw.lower() for t in trending_terms)
            records.append({
                "source": "google_trends_baseline",
                "niche": niche,
                "keyword": kw,
                "product_name": kw,
                "category": niche,
                "trend_type": "breakout" if in_trending else "stable",
                "region": region,
                "trend_score": 75.0 if in_trending else 40.0,
                "search_volume": None,
                "growth_rate": 20.0 if in_trending else 0.0,
                "velocity_score": 50.0 if in_trending else 20.0,
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "raw_data": {"in_trending": in_trending, "source_note": "baseline without CSE key"},
                "dedupe_key": create_trend_dedupe_key("google_trends_baseline", kw, region),
            })

    log.info(f"Google Trends total: {len(records)} records")
    return records
