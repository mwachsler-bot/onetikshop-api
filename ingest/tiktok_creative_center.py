"""
ingest/tiktok_creative_center.py - TikTok Commercial Content API ingestion.
Requires TIKTOK_ACCESS_TOKEN env var. Returns placeholder if not configured.
"""
import os, logging, time
from datetime import datetime, timezone
import httpx
from dedupe import create_ad_dedupe_key, create_hook_dedupe_key, classify_hook, extract_hook_from_text

log = logging.getLogger(__name__)
TIKTOK_BASE = "https://open.tiktokapis.com/v2/research/adlib/ad/query/"

def run_tiktok_ingestion(keywords, niche=None, token=None, max_per_kw=50):
    token = token or os.getenv("TIKTOK_ACCESS_TOKEN")
    if not token:
        log.warning("TIKTOK_ACCESS_TOKEN not set. Get one at developers.tiktok.com -> Research API.")
        return {"competitor_ads": [], "hooks": [], "_placeholder": True, "_message": "TIKTOK_ACCESS_TOKEN not configured."}
    ads_out, hooks_out = [], []
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=30) as client:
        for keyword in keywords:
            log.info(f"TikTok Creative Center: {keyword}")
            time.sleep(1.2)
            try:
                r = client.get(TIKTOK_BASE, headers=headers, params={"fields": "id,video_info,ad_text,first_shown_date,last_shown_date,status,reach,advertiser_business_name", "search_term": keyword, "max_count": min(max_per_kw, 50)})
                if r.status_code == 401: log.warning("TikTok token expired."); break
                if r.status_code != 200: log.warning(f"TikTok {r.status_code} for {keyword}"); continue
                for ad in r.json().get("data", {}).get("ads", []):
                    ad_id = str(ad.get("id", ""))
                    ad_text = ad.get("ad_text", "")
                    video = ad.get("video_info", {})
                    first_ts = ad.get("first_shown_date")
                    last_ts = ad.get("last_shown_date")
                    days = 0
                    if first_ts and last_ts:
                        try: days = max(0, (datetime.fromtimestamp(last_ts).date() - datetime.fromtimestamp(first_ts).date()).days)
                        except Exception: pass
                    reach = ad.get("reach", {})
                    views = int(reach.get("lower_bound") or 0)
                    engagement = min(100, days * 0.5 + (views / 100000) * 30)
                    ad_row = {
                        "source": "tiktok_commercial_api", "platform": "tiktok", "niche": niche,
                        "product_name": keyword, "brand_name": ad.get("advertiser_business_name"),
                        "media_url": video.get("video_url"),
                        "hook": extract_hook_from_text(ad_text),
                        "primary_text": ad_text[:1000] if ad_text else None,
                        "views": views, "engagement_score": round(engagement, 2),
                        "first_seen_at": datetime.fromtimestamp(first_ts, tz=timezone.utc).isoformat() if first_ts else datetime.now(timezone.utc).isoformat(),
                        "last_seen_at": datetime.fromtimestamp(last_ts, tz=timezone.utc).isoformat() if last_ts else datetime.now(timezone.utc).isoformat(),
                        "raw_data": {"days_running": days, "is_active": ad.get("status") == "ACTIVE", "thumbnail_url": video.get("cover_image_url")},
                        "dedupe_key": create_ad_dedupe_key("tiktok_commercial_api", ad_id),
                    }
                    ads_out.append(ad_row)
                    if ad_text:
                        hook_text = extract_hook_from_text(ad_text)
                        c = classify_hook(hook_text)
                        hooks_out.append({"source": "tiktok_commercial_api", "platform": "tiktok", "niche": niche, "product_name": keyword, "brand_name": ad.get("advertiser_business_name"), "hook_text": hook_text, "hook_type": c["hook_type"], "emotional_angle": c["emotional_angle"], "source_ad_id": ad_id, "views": views, "engagement_score": round(engagement, 2), "raw_data": {"offer_type": c["offer_type"]}, "dedupe_key": create_hook_dedupe_key(hook_text, "tiktok", niche or "")})
            except Exception as e:
                log.error(f"TikTok error for {keyword}: {e}")
    log.info(f"TikTok: {len(ads_out)} ads, {len(hooks_out)} hooks.")
    return {"competitor_ads": ads_out, "hooks": hooks_out}
