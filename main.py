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


# ─────────────────────────────────────────────
# VISUAL GENERATION VIA CLAUDE + HIGGSFIELD MCP
# ─────────────────────────────────────────────

class VisualRequest(BaseModel):
    product_id: str
    api_key: Optional[str] = None
    higgsfield_url: str = "https://mcp.higgsfield.ai/mcp"

@app.post("/generate-visuals")
async def generate_visuals(req: VisualRequest):
    """
    Uses Claude API with Higgsfield MCP to generate product images and videos.
    Claude reads the product details, finds supplier images, and generates visuals.
    Results are saved to Supabase and returned as URLs.
    """
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    # Get product agent outputs from Supabase
    async with httpx.AsyncClient() as client:
        outs_res = await client.get(
            f"{SUPABASE_URL}/rest/v1/agent_outputs?product_id=eq.{req.product_id}&status=eq.done",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        )
    
    outputs = outs_res.json() if isinstance(outs_res.json(), list) else []
    out_map = {o["agent_name"]: o["output"] for o in outputs if o.get("output")}
    
    analyst = out_map.get("analyst", "")[:2000]
    sourcer = out_map.get("sourcer", "")[:2000]
    designer = out_map.get("designer", "")[:1000]

    if not analyst:
        raise HTTPException(status_code=400, detail="No analyst output found. Run the pipeline first.")

    # Build the prompt for Claude with Higgsfield MCP
    visual_prompt = f"""You are generating professional product images for a TikTok Shop store.

PRODUCT DATA:
{analyst}

SOURCER DATA (contains supplier URLs and product images):
{sourcer}

BRAND DATA:
{designer}

YOUR TASK - do all of these in order:

1. Extract the exact product name, description, and all color variants from the data above

2. Find the best supplier product image URL from the sourcer data. Look for any image URLs mentioned (aliexpress, cjdropshipping, alibaba image URLs)

3. Generate these 4 images using Higgsfield:

   IMAGE 1 - Hero Shot:
   - Use nano_banana_2 model
   - If you found a supplier image URL, use it as reference (image role)
   - Prompt: "Professional ecommerce product photography, [exact product], [hero color variant], pure white seamless studio background, softbox lighting from 45 degree angle, product centered, ultra sharp detail, commercial quality, photorealistic, no text no logos"
   - Aspect ratio: 1:1
   - Resolution: 2k

   IMAGE 2 - Lifestyle Shot:
   - Use nano_banana_2 model  
   - Same reference image if available
   - Prompt: "Lifestyle product photography, [exact product] in [hero color] placed in luxury home setting, warm moody ambient bar lighting, beautiful bokeh background, premium aspirational aesthetic, no people, photorealistic"
   - Aspect ratio: 4:3
   - Resolution: 2k

   IMAGE 3 - UGC Shot:
   - Use soul_2 model (best for realistic human content)
   - Prompt: "Authentic UGC-style photo, young woman's hands holding [exact product], natural kitchen window light, casual home setting, genuine excited expression partially visible, iPhone photography feel, TikTok aesthetic, photorealistic"
   - Aspect ratio: 9:16
   - Resolution: 2k

   IMAGE 4 - Comparison Shot:
   - Use nano_banana_2 model
   - Prompt: "Split screen comparison photo, left side shows cheap generic [product type] looking bad, right side shows premium [exact product] in [hero color] looking amazing, dramatic quality difference, studio lighting, photorealistic"
   - Aspect ratio: 1:1
   - Resolution: 2k

4. After all images are generated, animate the Hero Shot into a 5-second product video:
   - Use seedance_2_0 model
   - Use the hero shot job result as the start_image reference
   - Prompt: "Product slowly floating and gently rotating, cinematic studio lighting, subtle elegant motion, premium commercial feel"
   - Aspect ratio: 9:16
   - Duration: 5 seconds

5. Return a summary of all generated assets with their job IDs and any result URLs

Generate all images now. Do not skip any steps."""

    # Call Claude API with Higgsfield MCP
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
                        "system": "You are a visual production agent. Use the Higgsfield MCP tools to generate product images and videos. Always complete all requested generations before responding.",
                        "messages": [{"role": "user", "content": visual_prompt}],
                        "mcp_servers": [
                            {
                                "type": "url",
                                "url": req.higgsfield_url,
                                "name": "higgsfield"
                            }
                        ]
                    }
                )
                
                if response.status_code != 200:
                    error = response.text
                    yield f"data: {json.dumps({'error': f'Claude API error: {error[:200]}'})}\n\n"


                    return

                result = response.json()
                
                # Extract text from response
                full_text = ""
                for block in result.get("content", []):
                    if block.get("type") == "text":
                        full_text += block.get("text", "")

                # Parse out any image URLs or job IDs from the response
                import re
                urls = re.findall(r'https?://[^\s'"<>]+\.(?:png|jpg|jpeg|webp)', full_text)
                job_ids = re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', full_text)

                # Save any found assets to Supabase
                saved_assets = []
                asset_types = ['hero_shot', 'lifestyle_shot', 'ugc_shot', 'comparison_shot', 'product_video']
                
                for i, url in enumerate(urls[:5]):
                    asset_type = asset_types[i] if i < len(asset_types) else f'asset_{i}'
                    async with httpx.AsyncClient() as db_client:
                        asset_res = await db_client.post(
                            f"{SUPABASE_URL}/rest/v1/assets",
                            headers={
                                "apikey": SUPABASE_KEY,
                                "Authorization": f"Bearer {SUPABASE_KEY}",
                                "Content-Type": "application/json",
                                "Prefer": "return=representation"
                            },
                            json={
                                "product_id": req.product_id,
                                "asset_type": asset_type,
                                "file_url": url,
                                "status": "ready",
                                "model_used": "higgsfield",
                                "created_at": datetime.now().isoformat()
                            }
                        )
                        if asset_res.status_code in [200, 201]:
                            saved_assets.append({"type": asset_type, "url": url})

                yield f"data: {json.dumps({'status': 'complete', 'text': full_text, 'assets': saved_assets, 'urls': urls, 'job_ids': job_ids})}

"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}

"

    return StreamingResponse(
        stream_visual_generation(),
        media_type="text/event-stream",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
    )


@app.options("/generate-visuals")
async def generate_visuals_options():
    return Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })

