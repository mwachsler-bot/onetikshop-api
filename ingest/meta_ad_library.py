"""
ingest/meta_ad_library.py - Meta Ad Library ingestion.
Official Graph API, free with Facebook developer account.
Requires META_ACCESS_TOKEN env var.
"""
import os, logging, time
from datetime import datetime, timezone
import httpx
from dedupe import create_ad_dedupe_key, create_hook_dedupe_key, classify_hook, extract_hook_from_text

log = logging.getLogger(__name__)
META_VERSION = "v19.0"
META_BASE = f"https://graph.facebook.com/{META_VERSION}/ads_archive"
SLEEP_SEC = 2.0
AD_FIELDS = ",".join(["id","page_name","page_id","ad_creative_bodies","ad_creative_link_titles","ad_snapshot_url","ad_delivery_start_time","ad_delivery_stop_time","publisher_platforms","impressions","spend","languages"])

def _days_running(start_str, stop_str=None):
    if not start_str: return 0
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end = datetime.fromisoformat(stop_str.replace("Z", "+00:00")) if stop_str else datetime.now(timezone.utc)
        return max(0, (end.date() - start.date()).days)
    except Exception: return 0

def _spend_tier(spend_lower):
    if not spend_lower: return None
    try:
        s = int(spend_lower)
        if s < 100: return "micro"
        if s < 1000: return "small"
        if s < 10000: return "medium"
        return "large"
    except Exception: return None

def run_meta_ingestion(keywords, niche=None, token=None, limit_per_kw=50):
    token = token or os.getenv("META_ACCESS_TOKEN")
    if not token:
        log.warning("META_ACCESS_TOKEN not set. Set it in .env to activate Meta Ad Library ingestion.")
        return {"competitor_ads": [], "hooks": []}
    ads_out, hooks_out = [], []
    with httpx.Client(timeout=30) as client:
        for keyword in keywords:
            log.info(f"Meta Ad Library: {keyword}")
            time.sleep(SLEEP_SEC)
            try:
                r = client.get(META_BASE, params={"access_token": token, "search_terms": keyword, "ad_type": "ALL", "ad_reached_countries": '["US"]', "fields": AD_FIELDS, "limit": min(limit_per_kw, 100)})
                if r.status_code == 400: log.warning(f"Meta 400: {r.text[:200]}"); continue
                r.raise_for_status()
                for ad in r.json().get("data", []):
                    ad_id = str(ad.get("id", ""))
                    if not ad_id: continue
                    start_str = ad.get("ad_delivery_start_time", "")
                    stop_str = ad.get("ad_delivery_stop_time", "")
                    days = _days_running(start_str, stop_str)
                    is_active = not bool(stop_str)
                    bodies = ad.get("ad_creative_bodies", [])
                    titles = ad.get("ad_creative_link_titles", [])
                    body_text = bodies[0] if bodies else ""
                    headline = titles[0] if titles else ""
                    spend = ad.get("spend", {})
                    impr = ad.get("impressions", {})
                    views = int(impr.get("lower_bound") or 0)
                    engagement = min(100, days * 0.5 + (views / 10000) * 20)
                    ad_row = {
                        "source": "meta_ad_library", "platform": "meta", "niche": niche,
                        "product_name": keyword, "brand_name": ad.get("page_name"),
                        "ad_url": ad.get("ad_snapshot_url"),
                        "hook": extract_hook_from_text(body_text),
                        "primary_text": body_text[:1000] if body_text else None,
                        "headline": headline[:300] if headline else None,
                        "views": views, "engagement_score": round(engagement, 2),
                        "first_seen_at": start_str or datetime.now(timezone.utc).isoformat(),
                        "last_seen_at": stop_str or datetime.now(timezone.utc).isoformat(),
                        "raw_data": {"days_running": days, "is_active": is_active, "spend_tier": _spend_tier(spend.get("lower_bound"))},
                        "dedupe_key": create_ad_dedupe_key("meta_ad_library", ad_id),
                    }
                    ads_out.append(ad_row)
                    if body_text:
                        hook_text = extract_hook_from_text(body_text)
                        if hook_text:
                            c = classify_hook(hook_text)
                            hooks_out.append({"source": "meta_ad_library", "platform": "meta", "niche": niche, "product_name": keyword, "brand_name": ad.get("page_name"), "hook_text": hook_text, "hook_type": c["hook_type"], "emotional_angle": c["emotional_angle"], "source_ad_id": ad_id, "source_url": ad.get("ad_snapshot_url"), "views": views, "engagement_score": round(engagement, 2), "raw_data": {"offer_type": c["offer_type"]}, "dedupe_key": create_hook_dedupe_key(hook_text, "meta", niche or "")})
            except Exception as e:
                log.error(f"Meta error for {keyword}: {e}")
    log.info(f"Meta: {len(ads_out)} ads, {len(hooks_out)} hooks.")
    return {"competitor_ads": ads_out, "hooks": hooks_out}
