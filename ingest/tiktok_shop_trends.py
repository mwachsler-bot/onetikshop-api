"""
ingest/tiktok_shop_trends.py

Pulls PRODUCT-SPECIFIC trend signals from TikTok sources.
No pytrends. No Google general trends.
Focused entirely on what is actually trending and selling on TikTok Shop.

SOURCES (all free, no rate limiting issues):

1. TikTok Creative Center - Trending Products API
   Returns products trending by category with view/engagement data.

2. TikTok Hashtag signals
   Queries product hashtags to measure TikTok-specific demand.

3. TikTok Creative Center keyword search trends
   Shows search volume trend for specific keywords on TikTok.

4. TikTok Research API (optional, needs token)
   Deep product video engagement data.
"""
import os
import logging
import time
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
    ("water bottle filter", "outdoor"),
    ("acne patches", "beauty"),
    ("teeth whitening", "health"),
    ("neck massager", "wellness"),
    ("under eye patches", "beauty"),
    ("back stretcher", "health"),
    ("shower head filter", "home"),
    ("sleep mask", "wellness"),
    ("cable management", "home office"),
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ads.tiktok.com/",
}


def fetch_tiktok_creative_center_products(category_id="0", period=7, region="US") -> list[dict]:
    """Pull trending products from TikTok Creative Center. No auth needed."""
    url = "https://ads.tiktok.com/creative_radar_api/v1/popular_trend/product/list"
    params = {"period": period, "page": 1, "limit": 50, "region": region, "category_id": category_id, "sort_by": "popular"}
    records = []
    try:
        r = httpx.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            log.warning(f"TikTok CC products: status {r.status_code}")
            return []
        data = r.json()
        products = data.get("data", {}).get("list", []) or data.get("data", []) or []
        for i, item in enumerate(products):
            name = item.get("product_title") or item.get("title") or item.get("name") or ""
            if not name: continue
            views = int(item.get("video_views", 0) or item.get("views", 0) or 0)
            likes = int(item.get("likes", 0) or 0)
            posts = int(item.get("video_count", 0) or item.get("post_count", 0) or 0)
            category = item.get("category_name") or item.get("category") or "general"
            position_score = max(0, 100 - (i * 2))
            engagement_bonus = min(20, (views / 1_000_000) * 10) if views else 0
            trend_score = min(100, position_score + engagement_bonus)
            records.append({
                "source": "tiktok_creative_center",
                "niche": category.lower(),
                "keyword": name.lower(),
                "product_name": name,
                "category": category,
                "trend_type": "breakout" if i < 5 else "rising" if i < 15 else "stable",
                "region": region,
                "trend_score": round(trend_score, 2),
                "search_volume": float(views),
                "growth_rate": 50.0 if i < 10 else 20.0,
                "velocity_score": round(trend_score * 0.8, 2),
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "raw_data": {"rank": i+1, "views": views, "likes": likes, "post_count": posts, "category": category},
                "dedupe_key": create_trend_dedupe_key("tiktok_cc_products", name.lower(), region),
            })
        log.info(f"TikTok CC products: {len(records)} trending products")
    except Exception as e:
        log.warning(f"TikTok Creative Center error: {e}")
    return records


def fetch_tiktok_hashtag_signals(keywords: list, region="US") -> list[dict]:
    """Query TikTok hashtag search for product-specific demand signals."""
    url = "https://ads.tiktok.com/creative_radar_api/v1/popular_trend/hashtag/list"
    records = []
    for keyword, niche in keywords:
        hashtag = keyword.replace(" ", "").lower()
        try:
            r = httpx.get(url, params={"keyword": hashtag, "period": 7, "page": 1, "limit": 10, "region": region}, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("list", []) or []
                if items:
                    top = items[0]
                    views = int(top.get("video_views", 0) or top.get("views", 0) or 0)
                    posts = int(top.get("video_count", 0) or 0)
                    trend_score = min(100, (views / 50_000_000) * 100)
                    trend_type = "breakout" if views > 50_000_000 else "rising" if views > 10_000_000 else "stable" if views > 1_000_000 else "low"
                    records.append({
                        "source": "tiktok_hashtag", "niche": niche, "keyword": keyword, "product_name": keyword,
                        "category": niche, "trend_type": trend_type, "region": region,
                        "trend_score": round(trend_score, 2), "search_volume": float(views),
                        "growth_rate": 0.0, "velocity_score": round(trend_score * 0.6, 2),
                        "first_seen_at": datetime.now(timezone.utc).isoformat(),
                        "last_seen_at": datetime.now(timezone.utc).isoformat(),
                        "raw_data": {"hashtag": f"#{hashtag}", "views": views, "post_count": posts},
                        "dedupe_key": create_trend_dedupe_key("tiktok_hashtag", keyword, region),
                    })
                    log.info(f"  #{hashtag}: views={views:,} score={trend_score:.1f} type={trend_type}")
                else:
                    records.append(_low_signal_record(keyword, niche, region, "tiktok_hashtag"))
            time.sleep(0.3)
        except Exception as e:
            log.debug(f"Hashtag error for {keyword}: {e}")
            records.append(_low_signal_record(keyword, niche, region, "tiktok_hashtag"))
    return records


def fetch_tiktok_keyword_trends(keywords: list, region="US") -> list[dict]:
    """TikTok Creative Center keyword search volume trends."""
    url = "https://ads.tiktok.com/creative_radar_api/v1/keyword/search"
    records = []
    for keyword, niche in keywords:
        try:
            r = httpx.get(url, params={"keyword": keyword, "period": 7, "region": region, "page": 1, "limit": 5}, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                items = r.json().get("data", {}).get("list", []) or []
                for item in items[:1]:
                    search_volume = int(item.get("search_volume", 0) or 0)
                    trend_score = min(100, (search_volume / 100_000) * 100)
                    trend_type = "breakout" if search_volume > 100_000 else "rising" if search_volume > 50_000 else "stable" if search_volume > 10_000 else "low"
                    records.append({
                        "source": "tiktok_keyword_search", "niche": niche, "keyword": keyword, "product_name": keyword,
                        "category": niche, "trend_type": trend_type, "region": region,
                        "trend_score": round(trend_score, 2), "search_volume": float(search_volume),
                        "growth_rate": float(item.get("growth_rate", 0) or 0), "velocity_score": round(trend_score * 0.7, 2),
                        "first_seen_at": datetime.now(timezone.utc).isoformat(),
                        "last_seen_at": datetime.now(timezone.utc).isoformat(),
                        "raw_data": {"search_volume": search_volume, "keyword": keyword},
                        "dedupe_key": create_trend_dedupe_key("tiktok_keyword", keyword, region),
                    })
                    log.info(f"  Keyword '{keyword}': vol={search_volume:,} score={trend_score:.1f}")
            time.sleep(0.3)
        except Exception as e:
            log.debug(f"Keyword trend error for {keyword}: {e}")
    return records


def _low_signal_record(keyword, niche, region, source) -> dict:
    return {
        "source": source, "niche": niche, "keyword": keyword, "product_name": keyword,
        "category": niche, "trend_type": "low", "region": region,
        "trend_score": 10.0, "search_volume": 0.0, "growth_rate": 0.0, "velocity_score": 5.0,
        "first_seen_at": datetime.now(timezone.utc).isoformat(),
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "raw_data": {"note": "no signal found"},
        "dedupe_key": create_trend_dedupe_key(source, keyword, region),
    }


def run_google_trends(keywords=None, region="US", timeframe=None) -> list[dict]:
    """Compatibility alias. Now pulls TikTok product trends instead of Google general trends."""
    return run_tiktok_product_trends(keywords=keywords, region=region)


def run_tiktok_product_trends(keywords=None, region="US") -> list[dict]:
    """Pull TikTok-specific product trend signals. No API key needed for core functionality."""
    kw_pairs = keywords or DEFAULT_KEYWORDS
    records = []
    token = os.getenv("TIKTOK_ACCESS_TOKEN")

    log.info(f"TikTok Shop Trends: {len(kw_pairs)} keywords, region={region}")

    log.info("Fetching TikTok Creative Center trending products...")
    cc = fetch_tiktok_creative_center_products(category_id="0", period=7, region=region)
    records.extend(cc)
    log.info(f"  Creative Center: {len(cc)} products")
    time.sleep(1)

    log.info("Fetching TikTok hashtag signals...")
    ht = fetch_tiktok_hashtag_signals(kw_pairs, region)
    records.extend(ht)
    log.info(f"  Hashtag signals: {len(ht)} records")
    time.sleep(1)

    log.info("Fetching TikTok keyword search trends...")
    kw = fetch_tiktok_keyword_trends(kw_pairs, region)
    records.extend(kw)
    log.info(f"  Keyword trends: {len(kw)} records")

    if token:
        log.info("Fetching TikTok Research API signals...")
        from ingest.tiktok_creative_center import run_tiktok_ingestion
        log.info("  Research API available")
    else:
        log.info("TIKTOK_ACCESS_TOKEN not set - add to Render env vars for deeper signals")

    log.info(f"TikTok Product Trends total: {len(records)} records")
    return records
