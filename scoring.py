"""
scoring.py - Deterministic product scoring engine. No AI. Pure math.

Weights: trend_velocity 20%, engagement 15%, margin 15%, saturation 15%,
creative_diversity 15%, supplier_confidence 10%, review_quality 5%, return_risk 5%
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional
from database import upsert, select
from dedupe import normalize_product_name

log = logging.getLogger(__name__)

WEIGHTS = {
    "trend_velocity_score": 0.20,
    "engagement_score": 0.15,
    "margin_score": 0.15,
    "saturation_score": 0.15,
    "creative_diversity_score": 0.15,
    "supplier_confidence_score": 0.10,
    "review_quality_score": 0.05,
    "return_risk_score": 0.05,
}

def calculate_trend_velocity_score(trend_score=0, growth_rate=0, velocity_score=0) -> float:
    base = min(trend_score, 100)
    growth_bonus = min(growth_rate * 0.5, 20)
    velocity_bonus = min(velocity_score * 0.3, 10)
    return min(100.0, max(0.0, base + growth_bonus + velocity_bonus))

def calculate_engagement_score(views=0, likes=0, comments=0, shares=0, ad_longevity_days=0) -> float:
    if views == 0: engagement_rate = 0.0
    else: engagement_rate = ((likes + comments * 2 + shares * 3) / views) * 100
    rate_score = min(engagement_rate * 10, 60)
    longevity_score = min(ad_longevity_days / 90 * 40, 40)
    return min(100.0, max(0.0, rate_score + longevity_score))

def calculate_margin_score(cost=None, retail_price=None, estimated_margin=None) -> float:
    margin = estimated_margin
    if margin is None and cost and retail_price and retail_price > 0:
        margin = ((retail_price - cost) / retail_price) * 100
    if margin is None: return 40.0
    if margin >= 70: return 100.0
    elif margin >= 60: return 85.0
    elif margin >= 50: return 70.0
    elif margin >= 40: return 55.0
    elif margin >= 30: return 35.0
    else: return 15.0

def calculate_saturation_score(competitor_count=0, saturation_raw=None) -> float:
    if saturation_raw is not None: return max(0.0, 100.0 - saturation_raw)
    if competitor_count < 10: return 95.0
    elif competitor_count < 50: return 80.0
    elif competitor_count < 150: return 65.0
    elif competitor_count < 300: return 45.0
    elif competitor_count < 500: return 30.0
    else: return 10.0

def calculate_creative_diversity_score(unique_hooks=0, unique_formats=0, total_ads=0) -> float:
    if total_ads == 0: return 50.0
    hook_score = min(unique_hooks * 8, 50)
    format_score = min(unique_formats * 12, 30)
    volume_bonus = min(total_ads * 0.5, 20)
    return min(100.0, max(0.0, hook_score + format_score + volume_bonus))

def calculate_supplier_confidence_score(supplier_rating=0, supplier_orders=0, has_multiple_suppliers=False, shipping_days=30) -> float:
    if supplier_rating == 0: return 40.0
    rating_score = min((supplier_rating / 5.0) * 60, 60)
    order_score = min(supplier_orders / 1000 * 20, 20)
    multi_bonus = 10 if has_multiple_suppliers else 0
    ship_score = max(0, 10 - (shipping_days - 7) * 0.5)
    return min(100.0, max(0.0, rating_score + order_score + multi_bonus + ship_score))

def calculate_review_quality_score(rating=0, review_count=0, review_velocity=0) -> float:
    if rating == 0 and review_count == 0: return 40.0
    rating_score = (rating / 5.0) * 50
    count_score = min(review_count / 500 * 30, 30)
    velocity_score = min(review_velocity * 2, 20)
    return min(100.0, max(0.0, rating_score + count_score + velocity_score))

def calculate_return_risk_score(return_risk_raw=None, category="") -> float:
    if return_risk_raw is not None: return max(0.0, 100.0 - return_risk_raw)
    cat = (category or "").lower()
    HIGH_RISK = {"clothing", "shoes", "apparel", "electronics", "tech", "gadgets"}
    MEDIUM_RISK = {"beauty", "skincare", "supplements", "health"}
    LOW_RISK = {"home", "kitchen", "pets", "office", "outdoor", "fitness", "tools"}
    if any(k in cat for k in HIGH_RISK): return 35.0
    elif any(k in cat for k in MEDIUM_RISK): return 60.0
    elif any(k in cat for k in LOW_RISK): return 85.0
    else: return 55.0

def calculate_final_product_score(component_scores: dict) -> tuple[float, str, str]:
    weighted = sum(component_scores.get(key, 0) * weight for key, weight in WEIGHTS.items())
    final = round(min(100.0, max(0.0, weighted)), 2)
    if final >= 80: status, reason = "launch_candidate", f"Exceptional score {final:.1f}/100."
    elif final >= 68: status, reason = "strong_test", f"Strong score {final:.1f}/100. Ready for test spend."
    elif final >= 55: status, reason = "test", f"Moderate score {final:.1f}/100. Worth small budget test."
    elif final >= 40: status, reason = "watch", f"Below threshold {final:.1f}/100. Monitor first."
    else: status, reason = "reject", f"Low score {final:.1f}/100. Too risky or saturated."
    if component_scores.get("margin_score", 100) < 20:
        status, reason = "reject", "Rejected: margin too low."
    if component_scores.get("saturation_score", 100) < 15:
        status, reason = "reject", "Rejected: market heavily saturated."
    return final, status, reason

def score_all_products() -> list[dict]:
    log.info("Starting product scoring run...")
    results = []
    products = select("product_market_data", order="-created_at", limit=500)
    if not products:
        log.warning("No products in product_market_data.")
        return []
    grouped: dict[str, list] = {}
    for p in products:
        key = p.get("normalized_product_name") or normalize_product_name(p.get("product_name", ""))
        grouped.setdefault(key, []).append(p)
    for norm_name, rows in grouped.items():
        primary = rows[0]
        trends = select("trends", filters={"keyword": norm_name}, limit=10)
        best_trend = max(trends, key=lambda t: t.get("trend_score", 0), default={})
        ads = select("competitor_ads", filters={"product_name": primary.get("product_name", "")}, limit=50)
        unique_hooks = len(set(a.get("hook", "") for a in ads if a.get("hook")))
        unique_formats = len(set(a.get("platform", "") for a in ads if a.get("platform")))
        avg_longevity = 0
        if ads:
            lons = []
            for a in ads:
                if a.get("first_seen_at"):
                    try:
                        start = datetime.fromisoformat(a["first_seen_at"].replace("Z", "+00:00"))
                        lons.append((datetime.now(timezone.utc) - start).days)
                    except Exception:
                        pass
            avg_longevity = sum(lons) / len(lons) if lons else 0
        total_views = sum(a.get("views", 0) or 0 for a in ads)
        total_likes = sum(a.get("likes", 0) or 0 for a in ads)
        total_comments = sum(a.get("comments", 0) or 0 for a in ads)
        total_shares = sum(a.get("shares", 0) or 0 for a in ads)
        components = {
            "trend_velocity_score": calculate_trend_velocity_score(
                trend_score=float(best_trend.get("trend_score") or 0),
                growth_rate=float(best_trend.get("growth_rate") or 0),
                velocity_score=float(best_trend.get("velocity_score") or 0),
            ),
            "engagement_score": calculate_engagement_score(
                views=total_views, likes=total_likes, comments=total_comments,
                shares=total_shares, ad_longevity_days=int(avg_longevity),
            ),
            "margin_score": calculate_margin_score(
                cost=primary.get("cost"), retail_price=primary.get("retail_price"),
                estimated_margin=primary.get("estimated_margin"),
            ),
            "saturation_score": calculate_saturation_score(saturation_raw=primary.get("saturation_score")),
            "creative_diversity_score": calculate_creative_diversity_score(
                unique_hooks=unique_hooks, unique_formats=unique_formats, total_ads=len(ads),
            ),
            "supplier_confidence_score": calculate_supplier_confidence_score(
                supplier_rating=float(primary.get("supplier_score") or 0),
            ),
            "review_quality_score": calculate_review_quality_score(
                rating=float(primary.get("rating") or 0),
                review_count=int(primary.get("review_count") or 0),
                review_velocity=float(primary.get("review_velocity") or 0),
            ),
            "return_risk_score": calculate_return_risk_score(
                return_risk_raw=primary.get("return_risk_score"),
                category=primary.get("category") or "",
            ),
        }
        final, status, reason = calculate_final_product_score(components)
        row = {
            "product_name": primary.get("product_name", norm_name),
            "normalized_product_name": norm_name,
            "niche": primary.get("niche"),
            "category": primary.get("category"),
            **components,
            "final_score": final,
            "score_breakdown": {"components": components, "weights": WEIGHTS},
            "recommendation_status": status,
            "reason": reason,
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            upsert("product_scores", row, on_conflict="normalized_product_name")
            results.append(row)
            log.info(f"  Scored: {norm_name[:40]} score={final:.1f} status={status}")
        except Exception as e:
            log.warning(f"  Failed to save score for {norm_name}: {e}")
    log.info(f"Scoring complete. {len(results)} products scored.")
    return results
