"""
OneTikShop Backend API - Clean version with Claude proxy
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional
import os, json, httpx
from datetime import datetime

app = FastAPI(title="OneTikShop API", version="1.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://wjltejertvgwewlwrvpu.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

class ClaudeRequest(BaseModel):
    system: str
    user: str
    api_key: Optional[str] = None

@app.get("/")
async def root():
    return {"app": "OneTikShop", "status": "running"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.options("/claude")
async def claude_options():
    return Response(headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"})

@app.post("/claude")
async def claude_proxy(req: ClaudeRequest):
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                    headers={"Content-Type": "application/json", "x-api-key": key, "anthropic-version": "2023-06-01"},
                    json={"model": "claude-sonnet-4-6", "max_tokens": 4096, "stream": True, "system": req.system, "messages": [{"role": "user", "content": req.user}]}
                ) as response:
                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            try:
                                data = json.loads(line[6:])
                                if data.get("type") == "content_block_delta":
                                    text = data.get("delta", {}).get("text", "")
                                    if text:
                                        yield f"data: {json.dumps({'text': text})}\n\n"
                                elif data.get("type") == "message_stop":
                                    yield f"data: {json.dumps({'done': True})}\n\n"
                            except: pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.get("/products")
async def list_products():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/products?order=created_at.desc",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    return r.json()

@app.get("/orders")
async def list_orders():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/orders?order=ordered_at.desc",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    return r.json()

@app.get("/analytics/summary")
async def analytics_summary():
    async with httpx.AsyncClient() as c:
        o = await c.get(f"{SUPABASE_URL}/rest/v1/orders", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        p = await c.get(f"{SUPABASE_URL}/rest/v1/products", headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    orders = o.json() if isinstance(o.json(), list) else []
    products = p.json() if isinstance(p.json(), list) else []
    return {
        "total_revenue": round(sum(float(x.get("total_amount") or 0) for x in orders), 2),
        "total_profit": round(sum(float(x.get("profit") or 0) for x in orders), 2),
        "total_orders": len(orders),
        "total_products": len(products),
        "live_products": len([x for x in products if x.get("status") == "live"])
    }


# ─────────────────────────────────────────────
# PRODUCT IMAGE SCRAPER
# ─────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    supplier_url: Optional[str] = None
    product_name: Optional[str] = None

class SearchRequest(BaseModel):
    query: str

@app.post("/scrape-product-image")
async def scrape_product_image(req: ScrapeRequest):
    """Scrape real product image from supplier page."""
    import re
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    }

    if not req.supplier_url:
        raise HTTPException(status_code=400, detail="No supplier URL provided")

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(req.supplier_url, headers=headers)
            if res.status_code == 200:
                html = res.text
                # Find image URLs
                patterns = [
                    r'https?://[^\s"\'<>]+(?:product|item|goods|img|image|photo)[^\s"\'<>]*\.(?:jpg|jpeg|png|webp)',
                    r'https?://ae01\.alicdn\.com/kf/[^\s"\'<>]+\.jpg[^\s"\'<>]*',
                    r'https?://cbu01\.alicdn\.com/[^\s"\'<>]+\.jpg[^\s"\'<>]*',
                    r'https?://img\.[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)[^\s"\'<>]*',
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    for match in matches:
                        if len(match) > 20 and not any(x in match.lower() for x in ['logo','icon','avatar','banner','thumb']):
                            # Verify image exists
                            try:
                                img_check = await client.head(match, timeout=5)
                                if img_check.status_code == 200:
                                    ct = img_check.headers.get('content-type','')
                                    if 'image' in ct:
                                        return {"image_url": match, "source": req.supplier_url}
                            except: continue
    except Exception as e:
        pass

    raise HTTPException(status_code=404, detail="No product image found")


@app.post("/search-product-image")
async def search_product_image(req: SearchRequest):
    """Search for product reference image."""
    import re
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    # Try CJDropshipping search
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            cj_res = await client.get(
                "https://app.cjdropshipping.com/api2.0/v1/product/list",
                params={"productName": req.query, "pageSize": 5, "pageNum": 1},
                timeout=10
            )
            if cj_res.status_code == 200:
                data = cj_res.json()
                products = data.get("data", {}).get("list", [])
                for p in products:
                    img = p.get("productImage", "")
                    if img and img.startswith("http"):
                        return {"image_url": img, "source": "CJDropshipping"}
    except: pass

    # Try AliExpress
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            ae_url = f"https://www.aliexpress.com/wholesale?SearchText={req.query.replace(' ','+')}"
            res = await client.get(ae_url, headers=headers)
            if res.status_code == 200:
                matches = re.findall(r'https://ae01\.alicdn\.com/kf/[^\s"\']+\.jpg', res.text)
                if matches:
                    return {"image_url": matches[0], "source": "AliExpress"}
    except: pass

    raise HTTPException(status_code=404, detail="No image found")
