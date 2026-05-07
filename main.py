""" OneTikShop Backend API - Final Corrected Version """
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from typing import Optional
import os, json, httpx, re
from datetime import datetime

app = FastAPI(title="OneTikShop API", version="1.0.0")

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

class VisualRequest(BaseModel):
    product_id: str
    api_key: Optional[str] = None
    higgsfield_url: str = "https://mcp.higgsfield.ai/mcp"

class ScrapeRequest(BaseModel):
    supplier_url: Optional[str] = None
    product_name: Optional[str] = None

class SearchRequest(BaseModel):
    query: str

@app.get("/")
async def root():
    return {"app": "OneTikShop", "status": "running"}

@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "healthy"}

@app.post("/claude")
async def claude_proxy(req: ClaudeRequest):
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")
    
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
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 4096,
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
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )

@app.get("/products")
async def list_products():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{SUPABASE_URL}/rest/v1/products?order=created_at.desc", 
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

@app.post("/scrape-product-image")
async def scrape_product_image(req: ScrapeRequest):
    headers = {"User-Agent": "Mozilla/5.0"}
    if not req.supplier_url:
        raise HTTPException(status_code=400, detail="No supplier URL provided")
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            res = await client.get(req.supplier_url, headers=headers)
            if res.status_code == 200:
                html = res.text
                patterns = [r'https?://[^\s"\'<>]+(?:product|item|goods|img|image|photo)[^\s"\'<>]*\.(?:jpg|jpeg|png|webp)']
                for pattern in patterns:
                    matches = re.findall(pattern, html, re.IGNORECASE)
                    if matches: return {"image_url": matches[0], "source": req.supplier_url}
    except: pass
    raise HTTPException(status_code=404, detail="No product image found")

@app.post("/generate-visuals")
async def generate_visuals(req: VisualRequest):
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    async with httpx.AsyncClient() as client:
        outs_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/agent_outputs?product_id=eq.{req.product_id}&status=eq.done",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        )
        outputs = outs_res.json() if isinstance(outs_res.json(), list) else []
    
    out_map = {o["agent_name"]: o["output"] for o in outputs if o.get("output")}
    analyst = out_map.get("analyst", "")[:2000]
    sourcer = out_map.get("sourcer", "")[:2000]

    visual_prompt = f"Product: {analyst}. Sources: {sourcer}. Generate Hero, Lifestyle, and UGC shots."

    async def stream_visual_generation():
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                response = await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "Content-Type": "application/json",
                        "x-api-key": key,
                        "anthropic-version": "2023-06-01"
                    },
                    json={
                        "model": "claude-sonnet-4-6",
                        "max_tokens": 4096,
                        "system": "Use Higgsfield MCP to generate product visuals.",
                        "messages": [{"role": "user", "content": visual_prompt}],
                        "mcp_servers": [{"type": "url", "url": req.higgsfield_url, "name": "higgsfield"}]
                    }
                )

                if response.status_code != 200:
                    yield f"data: {json.dumps({'error': 'Claude API error'})}\n\n"
                    return

                result = response.json()
                full_text = "".join([b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"])
                
                urls = re.findall(r'https?://[^\s"\'<>]+(?:\.png|\.jpg|\.jpeg|\.webp)', full_text)
                saved_assets = []
                
                for i, url in enumerate(urls[:5]):
                    async with httpx.AsyncClient() as db_client:
                        await db_client.post(
                            f"{SUPABASE_URL}/rest/v1/assets",
                            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}", "Content-Type": "application/json"},
                            json={"product_id": req.product_id, "file_url": url, "status": "ready"}
                        )
                        saved_assets.append({"url": url})

                yield f"data: {json.dumps({'status': 'complete', 'assets': saved_assets})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(stream_visual_generation(), media_type="text/event-stream")

@app.options("/generate-visuals")
async def generate_visuals_options():
    return Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })
