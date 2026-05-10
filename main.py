"""
OneTikShop Market Intelligence Backend v2
==========================================
FastAPI backend. Service role key server-side only.
All write endpoints require BACKEND_SHARED_SECRET header.
"""
import os
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("main")

from database import upsert, select, count
from dedupe import (
    normalize_product_name, create_product_dedupe_key,
    classify_hook, extract_hook_from_text,
)
from scoring import score_all_products
from jobs import (
    run_google_trends_ingestion, run_meta_ingestion_job,
    run_tiktok_ingestion_job, run_amazon_ingestion_job,
    run_all_ingestions,
)

SHARED_SECRET = os.environ.get("BACKEND_SHARED_SECRET", "")

app = FastAPI(
    title="OneTikShop Market Intelligence API",
    version="2.0.0",
    description="Backend-first market data layer. No AI for ingestion or scoring.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def require_secret(x_secret: str = Header(None, alias="X-Secret")):
    if not SHARED_SECRET:
        raise HTTPException(500, "BACKEND_SHARED_SECRET not configured on server.")
    if x_secret != SHARED_SECRET:
        raise HTTPException(403, "Invalid or missing X-Secret header.")
    return True


class ManualIngestItem(BaseModel):
    product_name: str
    niche: str
    category: Optional[str] = None
    cost: Optional[float] = None
    retail_price: Optional[float] = None
    estimated_margin: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    views: Optional[int] = None
    source: str = "manual"
    notes: Optional[str] = None


class IngestRequest(BaseModel):
    keywords: Optional[list[str]] = None
    niche: Optional[str] = None


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "services": {
            "supabase": bool(os.getenv("SUPABASE_URL")),
            "meta_ads": bool(os.getenv("META_ACCESS_TOKEN")),
            "tiktok_api": bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
            "amazon_api": bool(os.getenv("AWS_ACCESS_KEY")),
            "google_trends": os.getenv("GOOGLE_TRENDS_ENABLED", "true") == "true",
        },
    }


@app.post("/ingest/manual")
async def ingest_manual(items: list[ManualIngestItem], _: bool = Depends(require_secret)):
    saved = []
    for item in items:
        norm = normalize_product_name(item.product_name)
        margin = item.estimated_margin
        if margin is None and item.cost and item.retail_price and item.retail_price > 0:
            margin = round(((item.retail_price - item.cost) / item.retail_price) * 100, 1)
        row = {
            "source": item.source, "niche": item.niche,
            "product_name": item.product_name, "normalized_product_name": norm,
            "category": item.category or item.niche, "cost": item.cost,
            "retail_price": item.retail_price, "estimated_margin": margin,
            "rating": item.rating, "review_count": item.review_count,
            "views": item.views, "raw_data": {"notes": item.notes},
            "dedupe_key": create_product_dedupe_key(item.source, item.product_name),
        }
        try:
            upsert("product_market_data", row)
            saved.append(item.product_name)
        except Exception as e:
            log.warning(f"Failed to save {item.product_name}: {e}")
    scores = score_all_products()
    return {"status": "ok", "items_saved": len(saved), "items_scored": len(scores), "saved": saved}


@app.post("/ingest/google-trends")
async def ingest_google_trends(req: IngestRequest, background_tasks: BackgroundTasks, _: bool = Depends(require_secret)):
    kw_pairs = [(kw, req.niche or "unknown") for kw in req.keywords] if req.keywords else None
    background_tasks.add_task(run_google_trends_ingestion, kw_pairs)
    return {"status": "triggered", "message": "Google Trends ingestion started in background.", "keywords": req.keywords or "default keyword list"}


@app.post("/ingest/meta")
async def ingest_meta(req: IngestRequest, background_tasks: BackgroundTasks, _: bool = Depends(require_secret)):
    if not os.getenv("META_ACCESS_TOKEN"):
        return JSONResponse(status_code=202, content={"status": "not_configured", "message": "META_ACCESS_TOKEN not set.", "docs": "https://developers.facebook.com/docs/marketing-api/reference/ads-archive"})
    background_tasks.add_task(run_meta_ingestion_job, req.keywords, req.niche)
    return {"status": "triggered", "message": "Meta ingestion started in background."}


@app.post("/ingest/tiktok")
async def ingest_tiktok(req: IngestRequest, background_tasks: BackgroundTasks, _: bool = Depends(require_secret)):
    if not os.getenv("TIKTOK_ACCESS_TOKEN"):
        return JSONResponse(status_code=202, content={"status": "not_configured", "message": "TIKTOK_ACCESS_TOKEN not set.", "docs": "https://developers.tiktok.com/products/research-api"})
    background_tasks.add_task(run_tiktok_ingestion_job, req.keywords, req.niche)
    return {"status": "triggered", "message": "TikTok ingestion started in background."}


@app.post("/ingest/amazon")
async def ingest_amazon(req: IngestRequest, background_tasks: BackgroundTasks, _: bool = Depends(require_secret)):
    if not os.getenv("AWS_ACCESS_KEY"):
        return JSONResponse(status_code=202, content={"status": "not_configured", "message": "Amazon PA-API not configured.", "docs": "https://webservices.amazon.com/paapi5/documentation"})
    background_tasks.add_task(run_amazon_ingestion_job, req.keywords, req.niche)
    return {"status": "triggered", "message": "Amazon ingestion started in background."}


@app.post("/score/products")
async def trigger_scoring(_: bool = Depends(require_secret)):
    results = score_all_products()
    return {"status": "ok", "products_scored": len(results), "top_5": sorted(results, key=lambda r: r.get("final_score", 0), reverse=True)[:5]}


@app.get("/market/overview")
async def market_overview(limit: int = 10, niche: Optional[str] = None):
    score_filters = {"niche": niche} if niche else {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "top_scores": select("product_scores", filters=score_filters, order="-final_score", limit=limit),
        "top_trends": select("trends", order="-trend_score", limit=limit),
        "top_ads": select("competitor_ads", order="-engagement_score", limit=limit),
        "top_hooks": select("hooks", order="-engagement_score", limit=limit),
        "counts": {
            "product_scores": count("product_scores"),
            "trends": count("trends"),
            "competitor_ads": count("competitor_ads"),
            "hooks": count("hooks"),
            "product_market_data": count("product_market_data"),
        },
    }
