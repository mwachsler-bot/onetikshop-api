"""
OneTikShop — Backend API
FastAPI server that runs all agents, manages products, and handles automation
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import anthropic
import requests
import os
import json
from datetime import datetime

app = FastAPI(title="OneTikShop API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://wjltejertvgwewlwrvpu.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
HIGGSFIELD_KEY = os.environ.get("HIGGSFIELD_API_KEY", "")
HIGGSFIELD_SECRET = os.environ.get("HIGGSFIELD_SECRET", "")

def db():
    from supabase import create_client
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def claude():
    return anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class NewProductRequest(BaseModel):
    niche: Optional[str] = None
    platform: str = "both"
    auto_run: bool = True

class AgentRunRequest(BaseModel):
    product_id: str
    agent_name: str
    context: Optional[dict] = {}

class SettingsUpdate(BaseModel):
    key: str
    value: str

class OrderCreate(BaseModel):
    product_id: str
    platform: str
    order_number: str
    customer_name: str
    customer_email: str
    items: list
    total_amount: float

# ─────────────────────────────────────────────
# AGENT DEFINITIONS
# ─────────────────────────────────────────────

AGENT_SYSTEMS = {
    "scout": "You are an expert TikTok Shop product research agent. Find trending, profitable one-product dropship opportunities. Be specific, data-driven, give concrete numbers and reasoning.",
    "analyst": "You are a TikTok Shop product analyst. You make decisive product selections based on data. Pick ONE winner and commit fully with complete justification.",
    "sourcer": "You are a dropshipping sourcing expert. Find best suppliers and build complete SKU matrices with real URLs, prices, and shipping times.",
    "copywriter": "You are a TikTok Shop conversion copywriter. Write punchy, TikTok-native listings that convert browsers to buyers. Every word earns its place.",
    "photographer": "You are an AI photography director. Write precise image prompts that produce studio-quality results in DALL-E 3, Midjourney, and Ideogram every time.",
    "designer": "You are a brand designer specializing in TikTok-native e-commerce. Create premium, scroll-stopping visual identities with precise Canva execution instructions.",
    "scriptwriter": "You are a viral TikTok content strategist. Write scripts that feel authentic and drive product sales. You understand hook psychology.",
    "video_director": "You are an AI video production director. You know Runway, HeyGen, ElevenLabs, and CapCut inside out. Write briefs so specific anyone can execute them.",
    "tiktok_shop_builder": "You are a TikTok Shop setup expert. Build complete, high-converting stores. Every section is ready to copy and paste.",
    "shopify_builder": "You are a Shopify conversion rate optimization expert. Build complete high-converting stores from scratch. Every word ready to paste.",
    "shipping_manager": "You are a dropshipping fulfillment expert. Set up complete automated shipping systems and write all customer communications.",
    "email_automation": "You are a Klaviyo email marketing expert for e-commerce. Build complete automated flows that convert and retain customers.",
    "ad_creative": "You are a performance marketing creative director. Write TikTok and Facebook ads that stop scrolls and convert to purchases.",
    "ad_research": "You are a competitive intelligence and paid media research expert. Find what's working before brands spend money testing it.",
    "growth_manager": "You are a TikTok Shop growth manager who has launched dozens of successful one-product stores. Tactical, specific, results-focused.",
    "performance_optimizer": "You are a data-driven e-commerce performance analyst. Every recommendation is specific and actionable. Never vague.",
}

def get_agent_prompt(agent_name: str, context: dict) -> str:
    niche = context.get("niche", "")
    scout = context.get("scout_output", "")[:3000]
    analyst = context.get("analyst_output", "")[:3000]
    sourcer = context.get("sourcer_output", "")[:2000]
    copywriter = context.get("copywriter_output", "")[:2000]
    designer = context.get("designer_output", "")[:1500]
    scriptwriter = context.get("scriptwriter_output", "")[:2000]

    prompts = {
        "scout": f"""Research the 10 best one-product TikTok Shop opportunities RIGHT NOW.
{"Focus niche: " + niche if niche else "No niche preference — find what is actually trending and profitable."}

Requirements: one product, 4+ variants, $15-$40 retail, 3x+ margin, strong TikTok visual potential.

Score each 1-10: trend velocity, visual wow factor, variant potential, margin health, competition gap.
Output: ranked table of 10 + top 3 with cost/retail/margin/variants/content type.
End with complete → HANDOFF TO ANALYST AGENT block.""",

        "analyst": f"""Pick ONE winning product. Build the Master Product Brief.
SCOUT DATA: {scout}

Weighted scoring: virality 30%, margin 25%, variants 20%, filmability 15%, return risk 10%.
Declare ONE winner. Build variant strategy with PREMIUM color names (e.g. "Sage Mist" not "green").
Write positioning brief: exact buyer, emotional trigger, one-line viral hook, differentiation.

END WITH: ═══ MASTER PRODUCT BRIEF ═══
Include: product name, all variants with premium names, hero variant, buyer profile (3 sentences),
viral hook, retail price, cost, margin, key features (max 6), positioning angle.""",

        "sourcer": f"""Find best supplier + build complete SKU matrix.
MASTER BRIEF: {analyst}

1. Evaluate 5 suppliers (Alibaba, CJDropshipping, Zendrop, AutoDS)
2. Recommend #1 with URL and justification
3. SKU table: SKU|Variant|Color|Size|Cost|Retail|Margin%
4. Bundle pricing (2-pack, 3-pack)
5. Sample order plan (which variants, cost, what to check)""",

        "copywriter": f"""Write complete TikTok Shop listing.
DATA: {sourcer}

1. SEO title (80 chars, keyword first)
2. 5 bullets (benefit + proof + sensory detail)
3. Description (150-200 words, TikTok voice, punchy, FOMO)
4. Premium variant display names for every color/size
5. 10 backend SEO keyword tags
6. 3 A/B test title alternatives""",

        "designer": f"""Build complete visual brand identity.
PRODUCT: {copywriter}

1. Brand identity: 3 store name options, colors (3 hex codes), Google fonts, aesthetic direction
2. Canva briefs: logo, TikTok banner, benefit infographic, variant showcase, unboxing thumbnail
3. Ad creative copy: text overlays for 3 static ad images
4. Complete brand spec sheet with all hex codes, fonts, sizing""",

        "scriptwriter": f"""Write 5 complete TikTok video scripts.
BRAND: {designer}
PRODUCT: {copywriter}

Scripts: Problem Hook, Aesthetic Showcase, 7-Day Test, Unboxing Reveal, Comparison.
Each: run time, hook rating (1-10), scene-by-scene [VISUAL DIRECTIONS], voiceover, ON-SCREEN TEXT, audio vibe.
Also: 10 hook variants, 5 CTA options, 3 caption templates with hashtags, posting order.""",

        "video_director": f"""Create step-by-step production briefs for all 5 videos.
SCRIPTS: {scriptwriter}

For each: Runway/Kling prompt, HeyGen settings + script, ElevenLabs voice settings,
numbered CapCut edit steps, export specs (1080x1920, 30fps, MP4). Production priority order.""",

        "tiktok_shop_builder": f"""Build COMPLETE TikTok Shop setup guide.
PRODUCT: {analyst}
COPY: {copywriter}

Build: shop profile + bio, optimized listing (title/bullets/description/tags), variant setup table,
pricing strategy, 15 SEO keywords, all policies (copy-ready), step-by-step launch checklist.""",

        "shopify_builder": f"""Build complete high-converting Shopify store.
BRAND: {designer}
COPY: {copywriter}

Build: theme setup (Dawn), homepage (all sections written), product page, about page,
all policy pages, top 5 conversion apps, Shopify SEO setup, numbered step-by-step setup order.""",

        "shipping_manager": f"""Set up complete shipping + fulfillment system.
PRODUCT: {analyst}

Build: CJDropshipping Shopify connection steps, shipping zones/rates, all 6 customer notification
emails (confirmed/processing/shipped/out-for-delivery/delivered/delay), returns workflow,
tracking page setup, daily 10-minute operations checklist.""",

        "email_automation": f"""Build complete Klaviyo email system.
PRODUCT: {analyst}

Build 5 flows: Welcome (3 emails), Abandoned Cart (3), Post-Purchase (5), Win-Back (3), VIP (2).
Each email: subject + A/B variant, preview text, full body, CTA, timing, Klaviyo trigger settings.
Include Klaviyo setup instructions (Shopify connection, flow creation).""",

        "ad_creative": f"""Create complete paid advertising creative suite.
PRODUCT: {analyst}
COPY: {copywriter}

Build: 5 TikTok video ad scripts (different angles), Spark Ads setup instructions,
Facebook/Instagram ads (single image + carousel + 15-sec video), 3 retargeting versions,
ad copy swipe file (20 hooks, 15 CTAs, 10 headline formulas, 5 offer framings).""",

        "ad_research": f"""Run complete ad market research.
PRODUCT: {context.get('product_name', 'the product')}
NICHE: {niche or 'e-commerce'}
ANALYST DATA: {analyst[:1000]}

Research: top 5 competitor ad analysis, exact audience targeting (TikTok + Meta interest lists),
winning ad patterns this week, keyword + hashtag research, 4-week testing roadmap,
$50/day budget allocation split.""",

        "growth_manager": f"""Execute complete TikTok Shop launch playbook.
PRODUCT: {analyst}
COPY: {copywriter}

Build: 7-day posting schedule (day/time/video/caption/hashtags), 5 hashtag sets,
20 comment reply templates, 5 performance triggers with exact actions,
Week 2 Spark Ad brief, weekly analytics prompt template.""",

        "performance_optimizer": f"""You are the ongoing Performance Optimizer for this product.
PRODUCT: {analyst[:500]}

When user pastes analytics: health score (1-10), ad-by-ad SCALE/HOLD/KILL decisions,
exact budget reallocation, creative to test next, Monday-Sunday action list.
Also provide the weekly analytics template.""",
    }

    return prompts.get(agent_name, f"Run the {agent_name} agent for this product. Context: {json.dumps(context)[:1000]}")

# ─────────────────────────────────────────────
# CORE ROUTES
# ─────────────────────────────────────────────

@app.get("/")
async def root():
    return {"app": "OneTikShop", "version": "1.0.0", "status": "running", "timestamp": datetime.now().isoformat()}

@app.get("/health")
async def health():
    return {"status": "healthy"}

# ─────────────────────────────────────────────
# PRODUCTS
# ─────────────────────────────────────────────

@app.get("/products")
async def list_products():
    result = db().table("products").select("*").order("created_at", desc=True).execute()
    return result.data

@app.post("/products")
async def create_product(req: NewProductRequest, background_tasks: BackgroundTasks):
    product = db().table("products").insert({
        "niche": req.niche,
        "platform": req.platform,
        "status": "researching",
        "pipeline_step": "scout"
    }).execute()
    product_id = product.data[0]["id"]
    if req.auto_run:
        background_tasks.add_task(run_full_pipeline, product_id, req.niche or "")
    return {"product_id": product_id, "status": "pipeline_started"}

@app.get("/products/{product_id}")
async def get_product(product_id: str):
    product = db().table("products").select("*").eq("id", product_id).single().execute()
    outputs = db().table("agent_outputs").select("*").eq("product_id", product_id).execute()
    assets = db().table("assets").select("*").eq("product_id", product_id).execute()
    stores = db().table("stores").select("*").eq("product_id", product_id).execute()
    return {
        "product": product.data,
        "outputs": {o["agent_name"]: o for o in outputs.data},
        "assets": assets.data,
        "stores": stores.data
    }

@app.delete("/products/{product_id}")
async def delete_product(product_id: str):
    db().table("products").delete().eq("id", product_id).execute()
    return {"status": "deleted"}

# ─────────────────────────────────────────────
# AGENT RUNNER
# ─────────────────────────────────────────────

@app.post("/agents/run")
async def run_agent_endpoint(req: AgentRunRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(execute_agent, req.product_id, req.agent_name, req.context or {})
    return {"status": "started", "agent": req.agent_name}

@app.get("/agents/{product_id}/outputs")
async def get_agent_outputs(product_id: str):
    result = db().table("agent_outputs").select("*").eq("product_id", product_id).execute()
    return result.data

async def execute_agent(product_id: str, agent_name: str, context: dict = {}):
    client = db()
    ai = claude()

    # Create output record
    rec = client.table("agent_outputs").insert({
        "product_id": product_id,
        "agent_name": agent_name,
        "status": "running",
        "started_at": datetime.now().isoformat()
    }).execute()
    output_id = rec.data[0]["id"]

    try:
        # Load previous outputs if no context passed
        if not context.get(f"scout_output"):
            prev = client.table("agent_outputs").select(
                "agent_name,output").eq("product_id", product_id).eq("status", "done").execute()
            for o in prev.data:
                if o["output"]:
                    context[f"{o['agent_name']}_output"] = o["output"][:3000]

        system = AGENT_SYSTEMS.get(agent_name, "You are an expert e-commerce AI agent.")
        prompt = get_agent_prompt(agent_name, context)

        response = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": prompt}]
        )
        output_text = response.content[0].text

        # Save
        client.table("agent_outputs").update({
            "output": output_text,
            "status": "done",
            "completed_at": datetime.now().isoformat(),
            "tokens_used": response.usage.output_tokens
        }).eq("id", output_id).execute()

        # Advance pipeline step
        step_order = ["scout","analyst","sourcer","copywriter","designer",
                      "scriptwriter","video_director","tiktok_shop_builder",
                      "shopify_builder","shipping_manager","email_automation",
                      "ad_creative","ad_research","growth_manager"]
        if agent_name in step_order:
            idx = step_order.index(agent_name)
            next_step = step_order[idx+1] if idx+1 < len(step_order) else "complete"
            client.table("products").update({"pipeline_step": next_step}).eq("id", product_id).execute()

        return output_text

    except Exception as e:
        client.table("agent_outputs").update({
            "status": "failed",
            "output": f"Error: {str(e)}",
            "completed_at": datetime.now().isoformat()
        }).eq("id", output_id).execute()
        raise

# ─────────────────────────────────────────────
# FULL PIPELINE
# ─────────────────────────────────────────────

async def run_full_pipeline(product_id: str, niche: str = ""):
    client = db()

    run = client.table("pipeline_runs").insert({
        "product_id": product_id,
        "run_type": "full",
        "status": "running",
        "current_step": "scout"
    }).execute()
    run_id = run.data[0]["id"]

    agents = ["scout","analyst","sourcer","copywriter","designer",
              "scriptwriter","tiktok_shop_builder","shopify_builder",
              "email_automation","ad_creative","ad_research","growth_manager"]

    completed = []
    context = {"niche": niche}

    for agent_name in agents:
        try:
            client.table("pipeline_runs").update({"current_step": agent_name}).eq("id", run_id).execute()
            output = await execute_agent(product_id, agent_name, context)
            if output:
                context[f"{agent_name}_output"] = output[:3000]
            completed.append(agent_name)
            client.table("pipeline_runs").update({"steps_completed": completed}).eq("id", run_id).execute()
        except Exception as e:
            failed = client.table("pipeline_runs").select("steps_failed").eq("id", run_id).single().execute()
            steps_failed = failed.data.get("steps_failed") or []
            steps_failed.append(agent_name)
            client.table("pipeline_runs").update({
                "steps_failed": steps_failed,
                "error_message": str(e)
            }).eq("id", run_id).execute()

    client.table("pipeline_runs").update({
        "status": "completed",
        "completed_at": datetime.now().isoformat()
    }).eq("id", run_id).execute()

    client.table("products").update({"status": "live", "pipeline_step": "complete"}).eq("id", product_id).execute()

# ─────────────────────────────────────────────
# SETTINGS
# ─────────────────────────────────────────────

@app.get("/settings")
async def get_settings():
    result = db().table("settings").select("*").execute()
    return {s["key"]: s["value"] for s in result.data}

@app.post("/settings")
async def update_setting(req: SettingsUpdate):
    db().table("settings").upsert({"key": req.key, "value": req.value}).execute()
    return {"status": "updated"}

# ─────────────────────────────────────────────
# ORDERS
# ─────────────────────────────────────────────

@app.get("/orders")
async def get_orders(product_id: Optional[str] = None):
    query = db().table("orders").select("*").order("ordered_at", desc=True)
    if product_id:
        query = query.eq("product_id", product_id)
    return query.execute().data

@app.post("/orders")
async def create_order(req: OrderCreate):
    order = db().table("orders").insert({
        "product_id": req.product_id,
        "platform": req.platform,
        "order_number": req.order_number,
        "customer_name": req.customer_name,
        "customer_email": req.customer_email,
        "items": req.items,
        "total_amount": req.total_amount,
        "status": "received"
    }).execute()
    return order.data[0]

# ─────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────

@app.get("/analytics/summary")
async def analytics_summary():
    orders = db().table("orders").select("*").execute().data
    products = db().table("products").select("id,name,status,niche").execute().data
    pipeline_runs = db().table("pipeline_runs").select("*").execute().data

    total_revenue = sum(float(o.get("total_amount") or 0) for o in orders)
    total_profit = sum(float(o.get("profit") or 0) for o in orders)

    return {
        "total_revenue": round(total_revenue, 2),
        "total_profit": round(total_profit, 2),
        "total_orders": len(orders),
        "total_products": len(products),
        "live_products": len([p for p in products if p["status"] == "live"]),
        "pipeline_runs": len(pipeline_runs),
        "products": products
    }

@app.get("/pipeline/{product_id}/status")
async def pipeline_status(product_id: str):
    runs = db().table("pipeline_runs").select("*").eq(
        "product_id", product_id).order("started_at", desc=True).limit(1).execute()
    product = db().table("products").select("pipeline_step,status").eq("id", product_id).single().execute()
    return {
        "current_step": product.data.get("pipeline_step"),
        "product_status": product.data.get("status"),
        "latest_run": runs.data[0] if runs.data else None
    }


# ─────────────────────────────────────────────
# CLAUDE PROXY ENDPOINT (fixes CORS from Netlify)
# ─────────────────────────────────────────────

from fastapi.responses import StreamingResponse
import httpx

class ClaudeRequest(BaseModel):
    system: str
    user: str
    stream: bool = True
    api_key: Optional[str] = None

@app.post("/claude")
async def claude_proxy(req: ClaudeRequest):
    """Proxy Claude API calls from the frontend to avoid CORS issues."""
    key = req.api_key or ANTHROPIC_KEY
    if not key:
        raise HTTPException(status_code=400, detail="Anthropic API key required")

    async def generate():
        async with httpx.AsyncClient(timeout=120) as client:
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

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Access-Control-Allow-Origin": "*"})


@app.options("/claude")
async def claude_options():
    from fastapi.responses import Response
    return Response(headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type"
    })
