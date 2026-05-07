""" OneTikShop Backend API - Optimized """
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional
import os, json, httpx, re

app = FastAPI(title="OneTikShop API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://wjltejertvgwewlwrvpu.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

class ClaudeRequest(BaseModel):
    system: str
    user: str
    api_key: Optional[str] = None
    max_tokens: Optional[int] = 2048   # Default 2048, not 4096
    model: Optional[str] = "claude-sonnet-4-6"  # Can be overridden per agent

class VisualRequest(BaseModel):
    product_id: str
    api_key: Optional[str] = None
    higgsfield_url: str = "https://mcp.higgsfield.ai/mcp"

class ScrapeRequest(BaseModel):
    supplier_url: Optional[str] = None
    product_name: Optional[str] = None

@app.get("/")
async def root():
    return {"app": "OneTikShop", "status": "running", "version": "2.0"}

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "healthy"}

@app.post("/claude")
async def claude_proxy(req: ClaudeRequest):
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    # Clamp max_tokens — never let frontend accidentally send huge values
    max_tokens = min(req.max_tokens or 2048, 4096)
    model = req.model or "claude-sonnet-4-6"

    # Validate model — only allow known Claude models
    allowed_models = {
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "claude-opus-4-6",
    }
    if model not in allowed_models:
        model = "claude-sonnet-4-6"

    async def generate():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01"
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "stream": True,
                        "system": req.system,
                        "messages": [{"role": "user", "content": req.user}]
                    }
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
                            except:
                                pass
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no"
        }
    )

@app.get("/products")
async def list_products():
    async with httpx.AsyncClient() as c:
        r = await c.get(
            f"{SUPABASE_URL}/rest/v1/products?order=created_at.desc",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        )
        return r.json()

@app.get("/analytics/summary")
async def analytics_summary():
    async with httpx.AsyncClient() as c:
        o = await c.get(f"{SUPABASE_URL}/rest/v1/orders",
                        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        p = await c.get(f"{SUPABASE_URL}/rest/v1/products",
                        headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
        orders   = o.json() if isinstance(o.json(), list) else []
        products = p.json() if isinstance(p.json(), list) else []
        return {
            "total_revenue":  round(sum(float(x.get("total_amount") or 0) for x in orders), 2),
            "total_profit":   round(sum(float(x.get("profit") or 0) for x in orders), 2),
            "total_orders":   len(orders),
            "total_products": len(products),
            "live_products":  len([x for x in products if x.get("status") == "live"])
        }

@app.post("/scrape-product-image")
async def scrape_product_image(req: ScrapeRequest):
    headers = {"User-Agent": "Mozilla/5.0"}
    if not req.supplier_url:
        raise HTTPException(status_code=400, detail="No supplier URL provided")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(req.supplier_url, headers=headers)
            if res.status_code == 200:
                patterns = [r'https?://[^\s"\'<>]+(?:product|item|goods|img|image|photo)[^\s"\'<>]*\.(?:jpg|jpeg|png|webp)']
                for pattern in patterns:
                    matches = re.findall(pattern, res.text, re.IGNORECASE)
                    if matches:
                        return {"image_url": matches[0], "source": req.supplier_url}
    except:
        pass
    raise HTTPException(status_code=404, detail="No product image found")

@app.options("/claude")
async def claude_options():
    return Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })
