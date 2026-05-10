"""
ingest/google_trends.py - Google Trends ingestion via pytrends.
Free, no API key required. Rate-limited: sleep 65s between batches.
"""
import logging
import time
from datetime import datetime, timezone
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
]

SLEEP_BETWEEN_BATCHES = 65

def run_google_trends(keywords=None, region="US", timeframe="today 3-m") -> list[dict]:
    """
    Pull trend data for (keyword, niche) tuples.
    Returns normalized trend records ready for Supabase insertion.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        log.error("pytrends not installed. Run: pip install pytrends")
        return []

    if keywords is None:
        keywords = DEFAULT_KEYWORDS

    records = []
    batches = [keywords[i:i+5] for i in range(0, len(keywords), 5)]

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            log.info(f"Sleeping {SLEEP_BETWEEN_BATCHES}s (Google Trends rate limit)...")
            time.sleep(SLEEP_BETWEEN_BATCHES)

        kw_list = [k for k, _ in batch]
        niche_map = {k: n for k, n in batch}

        try:
            pt = TrendReq(hl="en-US", tz=360, timeout=(10, 30), retries=2, backoff_factor=0.5)
            pt.build_payload(kw_list, timeframe=timeframe, geo=region)
            df = pt.interest_over_time()
            if df is None or df.empty:
                log.warning(f"No data for batch {kw_list}")
                continue
            if "isPartial" in df.columns:
                df = df.drop(columns=["isPartial"])
            try:
                related = pt.related_queries()
            except Exception:
                related = {}

            for keyword in kw_list:
                if keyword not in df.columns: continue
                series = df[keyword].dropna()
                if series.empty: continue
                current = float(series.iloc[-1])
                week_ago = float(series.iloc[-8]) if len(series) > 7 else current
                month_ago = float(series.iloc[-31]) if len(series) > 30 else current
                if current > week_ago * 1.30: trend_type = "breakout"
                elif current > week_ago * 1.10: trend_type = "rising"
                elif current < week_ago * 0.85: trend_type = "falling"
                else: trend_type = "stable"
                growth_rate = ((current - month_ago) / max(month_ago, 1)) * 100
                rq = related.get(keyword, {})
                records.append({
                    "source": "google_trends",
                    "niche": niche_map.get(keyword, "unknown"),
                    "keyword": keyword,
                    "product_name": keyword,
                    "category": niche_map.get(keyword, "unknown"),
                    "trend_type": trend_type,
                    "region": region,
                    "trend_score": round(current, 2),
                    "growth_rate": round(growth_rate, 2),
                    "velocity_score": round(max(0, growth_rate), 2),
                    "first_seen_at": datetime.now(timezone.utc).isoformat(),
                    "last_seen_at": datetime.now(timezone.utc).isoformat(),
                    "raw_data": {"timeframe": timeframe, "region": region, "current": current, "week_ago": week_ago, "month_ago": month_ago},
                    "dedupe_key": create_trend_dedupe_key("google_trends", keyword, region),
                })
                log.info(f"  Trend: {keyword} score={current:.0f} {trend_type} growth={growth_rate:+.1f}%")
        except Exception as e:
            log.error(f"Google Trends batch error {kw_list}: {e}")

    log.info(f"Google Trends: {len(records)} records collected.")
    return records
