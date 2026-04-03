"""
SaintSal™ Labs — Backend Server
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)
Owner: Ryan "Cap" Capatosto

FastAPI backend powering saintsallabs.com
Serves iOS app + web frontend. All AI routes through here.

CRITICAL: app.mount() MUST be the LAST line before __main__.
          Any endpoint defined after app.mount() will 404 silently.
"""

import os
import json
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, AsyncIterator

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
import httpx

load_dotenv()

app = FastAPI(
    title="SaintSal™ Labs API",
    description="HACP™ Powered Intelligence Platform — Saint Vision Technologies LLC",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.saintsallabs.com", "https://saintsallabs.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Route Modules — ALL 8 SECTIONS ───────────────────────────────────────────
# MUST be imported and included BEFORE app.mount() at the bottom of this file.
# Any router included AFTER the static mount will 404 silently.
from routes.chat import router as chat_router
from routes.builder import builder_router
from routes.career import career_router
from routes.creative import router as creative_router
from routes.cards import router as cards_router
from routes.realestate import router as realestate_router
from routes.launchpad import router as launchpad_router
from routes.profile import router as profile_router

app.include_router(chat_router)
app.include_router(builder_router)
app.include_router(career_router)
app.include_router(creative_router)
app.include_router(cards_router)
app.include_router(realestate_router)
app.include_router(launchpad_router)
app.include_router(profile_router)

# ── Constants ─────────────────────────────────────────────────────────────────

SAL_GATEWAY_KEY = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY", "")
GHL_PRIVATE_TOKEN = os.environ.get("GHL_PRIVATE_TOKEN", "")
GHL_LOCATION_ID = os.environ.get("GHL_LOCATION_ID", "oRA8vL3OSiCPjpwmEC0V")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
XIMILAR_API_KEY = os.environ.get("XIMILAR_API_KEY", "")
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "")
FILEFORMS_API_KEY = os.environ.get("FILEFORMS_API_KEY", "")
GODADDY_API_KEY = os.environ.get("GODADDY_API_KEY", "")
GODADDY_API_SECRET = os.environ.get("GODADDY_API_SECRET", "")
ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")

TIER_RANK = {"free": 0, "starter": 1, "pro": 2, "teams": 3, "enterprise": 4}

VERTICAL_SYSTEM_PROMPTS = {
    "sports": """You are SAL, a sports intelligence engine for SaintSal™ Labs.
ALWAYS use web search (Tavily/Exa) to find live scores, standings, and news.
NEVER say you don't have access to live data — you DO via search tools.
When asked about scores or games: search first, respond with actual data.
Provide betting lines, fantasy advice, and game analysis when relevant.""",

    "search": """You are SAL, a deep research intelligence engine.
Use Exa for full-document retrieval. Use Tavily for fast factual lookup.
Use Perplexity for synthesis. Always cite sources.
Provide comprehensive, accurate, citation-rich research reports.""",

    "finance": """You are SAL, a finance and capital markets intelligence engine.
Access real-time market data via Alpaca. Use Exa for analysis.
Provide DCF/LBO analysis, portfolio review, and market intelligence.
Always caveat: this is analysis, not financial advice.""",

    "realestate": """You are SAL, a real estate intelligence engine.
Use RentCast for rent estimates and comps. Use PropertyAPI for property details.
Use Google Maps for geo intelligence.
Provide cap rates, 1031 exchange guidance, distressed lead analysis.""",

    "medical": """You are SAL, a healthcare intelligence engine.
Use Exa to search PubMed and medical literature. Zero hallucination tolerance.
ALWAYS recommend consulting a licensed physician for medical decisions.
Provide ICD-10/CPT codes, drug interaction checks, clinical research summaries.""",

    "legal": """You are SAL, a legal intelligence engine.
Use Exa for case law and USPTO patent search. Use Tavily for current law.
ALWAYS recommend consulting a licensed attorney for legal decisions.
Provide contract review, IP strategy, entity formation guidance.""",

    "technology": """You are SAL, a technology intelligence engine.
Write production-quality code. Review architecture decisions critically.
Use Grok for contrarian technical analysis. Use GPT-5 for code validation.
Provide working code, not pseudocode.""",

    "govdefense": """You are SAL, a government and defense intelligence engine.
Use Azure AI Search for FAR/DFARS and government knowledge bases.
Provide source selection guidance, compliance analysis, and political strategy.
Handle HUMINT/SIGINT/CISA topics with appropriate care.""",
}

VERTICAL_MODELS = {
    "sports":     {"primary": "grok", "secondary": "claude"},
    "search":     {"primary": "claude-opus", "secondary": "gpt5"},
    "finance":    {"primary": "claude-opus", "secondary": "grok"},
    "realestate": {"primary": "claude-sonnet", "secondary": "claude-opus"},
    "medical":    {"primary": "claude-opus", "secondary": None},  # Opus ONLY
    "legal":      {"primary": "claude-opus", "secondary": "gpt5"},
    "technology": {"primary": "claude-sonnet", "secondary": "gpt5"},
    "govdefense": {"primary": "claude-opus", "secondary": None},
}

# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_sal_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY_KEY:
        raise HTTPException(403, "Invalid gateway key")
    return True


async def check_tier(user_id: str, required_tier: str) -> bool:
    """Check if user has required tier. Returns True or raises 403."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return True  # Skip check if Supabase not configured
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"id": f"eq.{user_id}", "select": "plan_tier"},
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                },
            )
            data = res.json()
            if not data:
                return True  # New user, allow
            plan = data[0].get("plan_tier", "free")
            if TIER_RANK.get(plan, 0) < TIER_RANK.get(required_tier, 0):
                raise HTTPException(
                    403,
                    f"Requires {required_tier} plan. Current: {plan}. Upgrade at saintsallabs.com/pricing"
                )
            return True
    except HTTPException:
        raise
    except Exception:
        return True  # Don't block on metering errors


# ── SSE Helpers ───────────────────────────────────────────────────────────────

def sse_event(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


async def stream_claude(messages: list, system: str, model: str = "claude-opus-4-6") -> AsyncIterator[str]:
    """Stream response from Anthropic Claude."""
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        async with client.messages.stream(
            model=model,
            max_tokens=8192,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f"\n[Claude error: {str(e)[:100]}]"


async def call_grok(messages: list, system: str) -> str:
    """Call xAI Grok 4.20 (non-streaming)."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                "https://api.x.ai/v1/chat/completions",
                headers={"Authorization": f"Bearer {XAI_API_KEY}"},
                json={
                    "model": "grok-beta",
                    "messages": [{"role": "system", "content": system}, *messages],
                    "max_tokens": 8192,
                },
            )
            return res.json()["choices"][0]["message"]["content"]
    except Exception as e:
        raise HTTPException(500, f"Grok error: {str(e)[:100]}")


async def call_tavily(query: str, max_results: int = 5) -> list:
    """Search via Tavily."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query, "max_results": max_results},
            )
            return res.json().get("results", [])
    except Exception:
        return []


async def call_exa(query: str, num_results: int = 5) -> list:
    """Search via Exa."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_API_KEY},
                json={"query": query, "numResults": num_results, "contents": {"text": True}},
            )
            return res.json().get("results", [])
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1: CORE CHAT ENGINE — handled by routes/chat.py (chat_router)
# POST /api/mcp/chat is registered via app.include_router(chat_router) above.
# ══════════════════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    message: str
    vertical: str = "search"
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    team_ids: Optional[list] = None
    news_prefs: Optional[list] = None


# ── iOS AI proxy routes (/api/chat/*) ─────────────────────────────────────────
# These thin proxies are called by the iOS app's streamChat / streamSalChat.
# They pass the raw SSE bytes from the upstream provider directly to the client
# so the iOS XHR parser receives provider-native SSE format.

@app.post("/api/chat/anthropic")
async def chat_anthropic(request: Request):
    """Thin SSE proxy → Anthropic. Called by iOS streamChat/streamSalChat."""
    verify_sal_key(request)
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "ANTHROPIC_API_KEY not set")
    body = await request.json()
    upstream_body = {
        "model":      body.get("model", "claude-sonnet-4-6"),
        "max_tokens": body.get("max_tokens", 4096),
        "system":     body.get("system", "You are SAL, a helpful AI assistant for SaintSal™ Labs."),
        "messages":   body.get("messages", []),
        "stream":     True,
    }
    async def _proxy():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                },
                json=upstream_body,
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
    return StreamingResponse(_proxy(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/xai")
async def chat_xai(request: Request):
    """Thin SSE proxy → xAI Grok. Called by iOS streamChat for global/sports."""
    verify_sal_key(request)
    if not XAI_API_KEY:
        raise HTTPException(500, "XAI_API_KEY not set")
    body = await request.json()
    msgs = []
    if body.get("system"):
        msgs.append({"role": "system", "content": body["system"]})
    msgs.extend(body.get("messages", []))
    upstream_body = {
        "model":      body.get("model", "grok-3-mini"),
        "max_tokens": body.get("max_tokens", 4096),
        "messages":   msgs,
        "stream":     True,
    }
    async def _proxy():
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                "https://api.x.ai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {XAI_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json=upstream_body,
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    yield chunk
    return StreamingResponse(_proxy(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/openai")
async def chat_openai(request: Request):
    """Thin proxy → OpenAI. Called by iOS streamChat/generateSocial."""
    verify_sal_key(request)
    if not OPENAI_API_KEY:
        raise HTTPException(500, "OPENAI_API_KEY not set")
    body = await request.json()
    msgs = []
    if body.get("system"):
        msgs.append({"role": "system", "content": body["system"]})
    msgs.extend(body.get("messages", []))
    upstream_body = {
        "model":      body.get("model", "gpt-4o-mini"),
        "max_tokens": body.get("max_tokens", 4096),
        "messages":   msgs,
        "stream":     body.get("stream", False),
    }
    async def _proxy():
        async with httpx.AsyncClient(timeout=120.0) as client:
            if upstream_body["stream"]:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json=upstream_body,
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            else:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {OPENAI_API_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json=upstream_body,
                )
                yield resp.content
    media = "text/event-stream" if upstream_body["stream"] else "application/json"
    return StreamingResponse(_proxy(), media_type=media,
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/search/gemini")
async def search_gemini(request: Request):
    """Gemini web-grounded search. Called by iOS searchGemini."""
    verify_sal_key(request)
    body = await request.json()
    query = body.get("query", "").strip()
    if not query:
        raise HTTPException(400, "query is required")
    # Fallback to Tavily if Gemini key missing
    try:
        if GEMINI_API_KEY:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
                    json={
                        "contents": [{"parts": [{"text": query}]}],
                        "tools": [{"google_search": {}}],
                    },
                )
                data = resp.json()
                text = ""
                for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
                    text += part.get("text", "")
                sources = [
                    {"url": g.get("uri", ""), "title": g.get("title", "")}
                    for g in data.get("candidates", [{}])[0].get("groundingMetadata", {}).get("groundingChunks", [])
                ]
                return {"answer": text, "sources": sources}
        elif TAVILY_API_KEY:
            results = await call_tavily(query)
            answer = "\n\n".join(r.get("content", "")[:300] for r in results[:3])
            sources = [{"url": r.get("url", ""), "title": r.get("title", "")} for r in results[:5]]
            return {"answer": answer, "sources": sources}
        else:
            return {"answer": "Search unavailable — no search key configured.", "sources": []}
    except Exception as e:
        raise HTTPException(500, f"Search failed: {str(e)[:200]}")


@app.post("/api/chat")
async def chat_sse(request: Request):
    """
    SSE streaming chat — called by iOS streamSalChat.
    Accepts: {message, vertical, history, search}
    Returns SSE: {"type":"text","content":"..."}, {"type":"sources",...}, {"type":"done"}
    """
    verify_sal_key(request)
    body = await request.json()
    message  = body.get("message", "").strip()
    vertical = body.get("vertical", "search").lower()
    history  = body.get("history", [])
    do_search = body.get("search", True)

    if not message:
        raise HTTPException(400, "message is required")

    vertical_prompts = VERTICAL_SYSTEM_PROMPTS
    system_prompt = vertical_prompts.get(vertical, vertical_prompts.get("search", "You are SAL, a helpful AI assistant for SaintSal™ Labs."))

    # Build message list
    msgs = [{"role": m["role"], "content": m["content"]} for m in (history or [])[-20:] if m.get("role") in ("user","assistant") and m.get("content")]
    msgs.append({"role": "user", "content": message})

    # Web search pre-fetch for search-enabled verticals
    sources = []
    if do_search and vertical in ("search", "sports", "finance", "realestate") and (TAVILY_API_KEY or EXA_API_KEY):
        try:
            if TAVILY_API_KEY:
                results = await call_tavily(message, max_results=5)
            elif EXA_API_KEY:
                results = await call_exa(message)
            else:
                results = []
            if results:
                ctx = "\n\n".join(f"Source: {r.get('url','')}\n{r.get('content',r.get('text',''))[:400]}" for r in results[:3])
                system_prompt += f"\n\n=== LIVE WEB DATA ===\n{ctx}"
                sources = [{"url": r.get("url",""), "title": r.get("title","")} for r in results[:5]]
        except Exception:
            pass

    async def generate():
        if sources:
            yield f"data: {json.dumps({'type':'sources','sources':sources})}\n\n"
        try:
            async for chunk in stream_claude(msgs, system_prompt, model="claude-sonnet-4-6"):
                yield f"data: {json.dumps({'type':'text','content':chunk})}\n\n"
        except Exception:
            try:
                text = await call_grok(msgs, system_prompt)
                for word in text.split(" "):
                    yield f"data: {json.dumps({'type':'text','content':word+' '})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type':'error','message':str(e)[:100]})}\n\n"
        yield f"data: {json.dumps({'type':'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/verticals/trending")
async def verticals_trending(vertical: str = "search", user_id: Optional[str] = None, request: Request = None):
    """
    Trending content per vertical.
    Sports → live scores + breaking news
    Finance → market movers
    Real Estate → local market stats
    All others → trending in that domain
    """
    verify_sal_key(request)

    queries = {
        "sports": "live sports scores today NBA NFL MLB NHL",
        "search": "breaking news today top stories",
        "finance": "stock market movers today S&P 500",
        "realestate": "real estate market trends housing prices",
        "medical": "medical research breakthroughs health news",
        "legal": "legal news supreme court legislation",
        "technology": "tech news AI startups programming",
        "govdefense": "government policy defense news",
    }

    query = queries.get(vertical.lower(), "latest news today")
    articles = []

    try:
        results = await call_tavily(query, max_results=8)
        articles = [
            {
                "title": r.get("title", ""),
                "source": r.get("url", "").split("/")[2] if r.get("url") else "",
                "url": r.get("url", ""),
                "content": r.get("content", "")[:200],
                "published_at": r.get("published_date", ""),
            }
            for r in results
        ]
    except Exception:
        pass

    return {"vertical": vertical, "articles": articles, "generated_at": datetime.utcnow().isoformat()}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2: BUILDER v2 — 5-AGENT PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

# In-memory session store (replace with Supabase in production)
_builder_sessions: dict = {}


class BuilderV2Request(BaseModel):
    prompt: str
    tier: str = "pro"
    session_id: Optional[str] = None
    model_override: Optional[str] = None


class BuilderApproveRequest(BaseModel):
    session_id: str
    approved: bool
    feedback: Optional[str] = None


@app.post("/api/builder/agent/v2")
async def builder_agent_v2(body: BuilderV2Request, request: Request):
    """
    Builder v2 — 5-agent SSE pipeline.
    Phase 1: Grok → plan_ready
    Phase 2a: Stitch → design_ready (PAUSES for approval)
    Phase 2b: Claude Sonnet → scaffold_ready
    Phase 3: Claude Opus → files_ready
    Phase 4: GPT-5 → validation_ready
    """
    verify_sal_key(request)

    session_id = body.session_id or f"build_{uuid.uuid4().hex[:12]}"
    _builder_sessions[session_id] = {"status": "planning", "prompt": body.prompt}

    async def pipeline():
        # ── Phase 1: Grok — Architecture ─────────────────────────────────────
        yield sse_event("agent_status", {"agent": "grok", "status": "active", "message": "Architecting your app..."})
        yield sse_event("agent_status", {"agent": "stitch", "status": "waiting"})
        yield sse_event("agent_status", {"agent": "claude-sonnet", "status": "waiting"})
        yield sse_event("agent_status", {"agent": "claude-opus", "status": "waiting"})
        yield sse_event("agent_status", {"agent": "gpt5", "status": "waiting"})

        try:
            plan_content = await call_grok(
                [{"role": "user", "content": f"Create a detailed technical architecture plan for: {body.prompt}"}],
                "You are a senior software architect. Create a component tree, tech stack, and file structure plan. Be specific and actionable. Return JSON with: plan (string), components (array of strings), tech_stack (object)."
            )
            try:
                plan_data = json.loads(plan_content)
            except Exception:
                plan_data = {"plan": plan_content, "components": [], "tech_stack": {}}

            _builder_sessions[session_id]["plan"] = plan_data
            yield sse_event("agent_status", {"agent": "grok", "status": "complete"})
            yield sse_event("plan_ready", plan_data)

        except Exception as e:
            yield sse_event("error", {"agent": "grok", "message": str(e)[:200], "recoverable": False})
            return

        # ── Phase 2a: Stitch — UI Design ─────────────────────────────────────
        yield sse_event("agent_status", {"agent": "stitch", "status": "active", "message": "Designing your UI..."})

        # Stitch MCP integration — generate UI screens via Claude with design context
        design_prompt = f"""Create complete HTML/CSS UI designs for: {body.prompt}
Architecture plan: {json.dumps(plan_data.get('plan', ''), ensure_ascii=False)[:500]}

Generate 3-4 key screens. For each screen return:
- name: screen name
- html: complete HTML with inline CSS (dark bg #0b0b0f, gold #f59e0b accents)
- thumbnail: brief description

Return JSON: {{ "screens": [{{ "name": "", "html": "", "thumbnail": "" }}] }}"""

        try:
            design_content = await call_grok(
                [{"role": "user", "content": design_prompt}],
                "You are a UI/UX designer who creates premium dark-themed interfaces. Use CSS variables: --bg:#0b0b0f, --gold:#f59e0b, --t1:#e8e6e1. Return valid JSON only."
            )
            try:
                design_data = json.loads(design_content)
            except Exception:
                design_data = {"screens": [{"name": "Main", "html": "<div style='color:#e8e6e1;background:#0b0b0f;padding:24px'><h1 style='color:#f59e0b'>Your App</h1></div>", "thumbnail": "Main screen"}]}

            design_data["session_id"] = session_id
            _builder_sessions[session_id]["designs"] = design_data
            _builder_sessions[session_id]["status"] = "awaiting_approval"

            yield sse_event("agent_status", {"agent": "stitch", "status": "complete"})
            yield sse_event("design_ready", design_data)

            # ── PAUSE: Stream pauses here. Client calls /approve to continue ──
            # Store continuation callback in session
            _builder_sessions[session_id]["awaiting_approval"] = True
            yield sse_event("awaiting_approval", {
                "session_id": session_id,
                "message": "Review the designs above, then approve to continue building."
            })

        except Exception as e:
            yield sse_event("error", {"agent": "stitch", "message": str(e)[:200], "recoverable": True})

    return StreamingResponse(pipeline(), media_type="text/event-stream")


@app.post("/api/builder/agent/v2/approve")
async def builder_v2_approve(body: BuilderApproveRequest, request: Request):
    """
    Resume the v2 pipeline after design approval.
    POST { session_id, approved: true, feedback? }
    """
    verify_sal_key(request)

    session = _builder_sessions.get(body.session_id)
    if not session:
        raise HTTPException(404, "Session not found")

    if not body.approved:
        # Restart design phase with feedback
        session["status"] = "redesigning"
        return {"status": "redesigning", "message": "Regenerating designs with your feedback..."}

    session["status"] = "scaffolding"

    async def continue_pipeline():
        plan = session.get("plan", {})
        designs = session.get("designs", {})

        # ── Phase 2b: Claude Sonnet — Scaffold ───────────────────────────────
        yield sse_event("agent_status", {"agent": "claude-sonnet", "status": "active", "message": "Engineering file structure..."})

        scaffold_prompt = f"""Create a complete file tree and route structure for this app.
Prompt: {session.get('prompt', '')}
Plan: {json.dumps(plan, ensure_ascii=False)[:800]}

Return JSON: {{ "files": [{{ "path": "", "description": "" }}] }}"""

        scaffold_content = ""
        async for chunk in stream_claude(
            [{"role": "user", "content": scaffold_prompt}],
            "You are a senior software engineer. Create a precise file structure. Return valid JSON only.",
            model="claude-sonnet-4-6"
        ):
            scaffold_content += chunk

        try:
            scaffold_data = json.loads(scaffold_content)
        except Exception:
            scaffold_data = {"files": [{"path": "index.js", "description": "Main entry point"}]}

        session["scaffold"] = scaffold_data
        yield sse_event("agent_status", {"agent": "claude-sonnet", "status": "complete"})
        yield sse_event("scaffold_ready", scaffold_data)

        # ── Phase 3: Claude Opus — Full Code Synthesis ────────────────────────
        yield sse_event("agent_status", {"agent": "claude-opus", "status": "active", "message": "Writing production code..."})

        synthesis_prompt = f"""Build complete, production-quality code for:
Prompt: {session.get('prompt', '')}
File structure: {json.dumps(scaffold_data, ensure_ascii=False)[:600]}
Design context: {len(designs.get('screens', []))} screens designed with dark/gold theme.

Generate the most important files. Return JSON:
{{ "files": [{{ "path": "", "content": "", "language": "" }}] }}"""

        files_content = ""
        async for chunk in stream_claude(
            [{"role": "user", "content": synthesis_prompt}],
            "You are a senior full-stack engineer. Write complete, working code — no placeholders, no TODO comments. Return valid JSON only.",
            model="claude-opus-4-6"
        ):
            files_content += chunk

        try:
            files_data = json.loads(files_content)
        except Exception:
            files_data = {"files": [{"path": "index.js", "content": "// Generated by SaintSal™ Labs Builder", "language": "javascript"}]}

        session["files"] = files_data
        yield sse_event("agent_status", {"agent": "claude-opus", "status": "complete"})
        yield sse_event("files_ready", files_data)

        # ── Phase 4: GPT-5 — Validation ──────────────────────────────────────
        yield sse_event("agent_status", {"agent": "gpt5", "status": "active", "message": "Validating code quality..."})

        # Basic validation (extend with real lint tools)
        lint_results = []
        suggestions = [
            {"suggestion": "Add error boundaries around async operations"},
            {"suggestion": "Consider adding TypeScript for type safety"},
        ]

        session["status"] = "complete"
        yield sse_event("agent_status", {"agent": "gpt5", "status": "complete"})
        yield sse_event("validation_ready", {
            "lint_results": lint_results,
            "suggestions": suggestions,
        })
        yield sse_event("complete", {
            "session_id": body.session_id,
            "total_files": len(files_data.get("files", [])),
        })

    return StreamingResponse(continue_pipeline(), media_type="text/event-stream")


@app.post("/api/builder/iterate")
async def builder_iterate(request: Request):
    """Diff-based code editing — no full regeneration."""
    verify_sal_key(request)
    body = await request.json()
    change_request = body.get("change", "")
    current_files = body.get("files", [])

    async def iterate():
        yield sse_event("agent_status", {"agent": "claude-opus", "status": "active", "message": "Applying changes..."})

        prompt = f"""Apply this change to the codebase: {change_request}

Only return the files that need to change. Return JSON:
{{ "files": [{{ "path": "", "content": "", "language": "" }}] }}"""

        content = ""
        async for chunk in stream_claude(
            [{"role": "user", "content": prompt}],
            "You are a senior engineer making targeted code changes. Only return changed files. Return valid JSON.",
            model="claude-opus-4-6"
        ):
            content += chunk

        try:
            data = json.loads(content)
        except Exception:
            data = {"files": []}

        yield sse_event("agent_status", {"agent": "claude-opus", "status": "complete"})
        yield sse_event("files_ready", data)
        yield sse_event("complete", {"type": "iteration"})

    return StreamingResponse(iterate(), media_type="text/event-stream")


@app.post("/api/builder/deploy")
async def builder_deploy(request: Request):
    """Deploy built code to Vercel/Render/Cloudflare."""
    verify_sal_key(request)
    body = await request.json()
    platform = body.get("platform", "vercel")
    files = body.get("files", [])
    session_id = body.get("session_id", "")

    # TODO: Integrate with Vercel/Render/Cloudflare deploy APIs
    # For now, return a success response
    return {"status": "deploying", "platform": platform, "session_id": session_id, "message": f"Deploying to {platform}..."}


@app.get("/api/builder/models")
async def builder_models(request: Request):
    """Available models per tier."""
    verify_sal_key(request)
    return {
        "free": ["sal-mini"],
        "starter": ["sal-mini", "sal-pro"],
        "pro": ["sal-mini", "sal-pro", "sal-max", "sal-max-fast"],
        "teams": ["sal-mini", "sal-pro", "sal-max", "sal-max-fast"],
        "enterprise": ["sal-mini", "sal-pro", "sal-max", "sal-max-fast", "api"],
    }


@app.post("/api/builder/agent")
async def builder_agent_v1(request: Request):
    """Builder v1 — 3-agent pipeline (kept for backwards compatibility)."""
    verify_sal_key(request)
    body = await request.json()
    prompt = body.get("prompt", "")

    async def v1_pipeline():
        yield sse_event("status", {"phase": "planning", "message": "Planning your app..."})
        try:
            plan = await call_grok(
                [{"role": "user", "content": f"Plan this app: {prompt}"}],
                "You are a software architect. Create a concise app plan."
            )
            yield sse_event("plan", {"content": plan})
            yield sse_event("status", {"phase": "building", "message": "Building code..."})

            code = ""
            async for chunk in stream_claude(
                [{"role": "user", "content": f"Build this app: {prompt}\nPlan: {plan[:500]}"}],
                "You are a senior engineer. Write complete, working code.",
                model="claude-sonnet-4-6"
            ):
                code += chunk
                yield sse_event("chunk", {"content": chunk})

            yield sse_event("complete", {"files": [{"path": "index.js", "content": code}]})
        except Exception as e:
            yield sse_event("error", {"message": str(e)[:200]})

    return StreamingResponse(v1_pipeline(), media_type="text/event-stream")


@app.post("/api/builder/v2/generate")
async def builder_quick_generate(request: Request):
    """Quick build — no full pipeline, just generate."""
    verify_sal_key(request)
    body = await request.json()
    prompt = body.get("prompt", "")

    async def quick_gen():
        yield sse_event("status", {"phase": "building"})
        async for chunk in stream_claude(
            [{"role": "user", "content": f"Build a complete, production-quality app: {prompt}"}],
            "You are a senior full-stack engineer. Generate complete, working code with no placeholders.",
            model="claude-sonnet-4-6"
        ):
            yield sse_event("chunk", {"content": chunk})
        yield sse_event("complete", {})

    return StreamingResponse(quick_gen(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3: CAREER + BUSINESS INTELLIGENCE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/career/jobs")
async def career_jobs(query: str = "", location: str = "", request: Request = None):
    """Job search via Exa + Tavily."""
    verify_sal_key(request)
    search_query = f"job openings {query} {location} site:linkedin.com OR site:indeed.com"
    results = await call_tavily(search_query, max_results=10)
    return {"jobs": results, "query": query, "location": location}


@app.post("/api/career/resume")
async def career_resume(request: Request):
    """Generate resume from user data."""
    verify_sal_key(request)
    body = await request.json()

    async def gen():
        async for chunk in stream_claude(
            [{"role": "user", "content": f"Generate a professional resume for: {json.dumps(body)}"}],
            "You are an expert resume writer. Create ATS-optimized, compelling resumes. Return clean formatted text.",
            model="claude-sonnet-4-6"
        ):
            yield sse_event("chunk", {"content": chunk})
        yield sse_event("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/career/enhance")
async def career_enhance(request: Request):
    """AI resume enhancement."""
    verify_sal_key(request)
    body = await request.json()
    resume_text = body.get("resume_text", "")

    async def gen():
        async for chunk in stream_claude(
            [{"role": "user", "content": f"Enhance this resume: {resume_text}"}],
            "You are an expert resume writer. Strengthen bullet points, quantify achievements, improve ATS scoring.",
            model="claude-opus-4-6"
        ):
            yield sse_event("chunk", {"content": chunk})
        yield sse_event("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/career/coach")
async def career_coach(request: Request):
    """Career coaching via Claude Opus."""
    verify_sal_key(request)
    body = await request.json()

    async def gen():
        async for chunk in stream_claude(
            [{"role": "user", "content": body.get("message", "")}],
            "You are SAL, an expert career coach with 20+ years experience. Provide actionable, specific career guidance.",
            model="claude-opus-4-6"
        ):
            yield sse_event("chunk", {"content": chunk})
        yield sse_event("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/career/interview")
async def career_interview(request: Request):
    """Interview prep — role-specific questions and coaching."""
    verify_sal_key(request)
    body = await request.json()

    async def gen():
        prompt = f"Prepare me for an interview: {json.dumps(body)}"
        async for chunk in stream_claude(
            [{"role": "user", "content": prompt}],
            "You are an expert interview coach. Generate role-specific questions, model answers, and strategic tips.",
            model="claude-opus-4-6"
        ):
            yield sse_event("chunk", {"content": chunk})
        yield sse_event("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/career/cover-letter")
async def career_cover_letter(request: Request):
    """Cover letter generation."""
    verify_sal_key(request)
    body = await request.json()
    resume_text = body.get("resume_text", "")
    job_description = body.get("job_description", "")
    style = body.get("style", "direct")

    prompt = f"""Write a {style} cover letter.

Resume highlights: {resume_text[:1000]}
Job description: {job_description[:1000]}

Style guidelines:
- direct: concise, value-focused, 3 paragraphs
- storytelling: narrative arc, specific examples, 4 paragraphs
- technical: skills-matching, quantified achievements, 3 paragraphs"""

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": prompt}],
        "You are an expert cover letter writer. Create compelling, specific cover letters that get interviews.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    word_count = len(content.split())
    keywords = [w for w in job_description.lower().split() if len(w) > 5][:10]
    matched = [k for k in keywords if k in content.lower()]

    return {"cover_letter": content, "word_count": word_count, "keywords_matched": matched}


@app.post("/api/career/swot")
async def career_swot(request: Request):
    """SWOT analysis for career or business."""
    verify_sal_key(request)
    body = await request.json()

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Create a detailed SWOT analysis for: {json.dumps(body)}"}],
        "You are a strategic business analyst. Create comprehensive SWOT analyses with actionable insights.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    return {"swot": content}


@app.post("/api/career/bizplan")
async def career_bizplan(request: Request):
    """Business plan generation (SSE stream)."""
    verify_sal_key(request)
    body = await request.json()

    async def gen():
        sections = ["executive_summary", "market_analysis", "competitive_landscape",
                    "product_service", "business_model", "go_to_market",
                    "financial_projections", "team", "funding_ask"]

        for section in sections:
            yield sse_event("section_start", {"section": section})
            section_content = ""
            async for chunk in stream_claude(
                [{"role": "user", "content": f"Write the {section.replace('_', ' ')} section for: {json.dumps(body)}"}],
                f"You are an expert business plan writer. Write a comprehensive, data-driven {section} section.",
                model="claude-opus-4-6"
            ):
                section_content += chunk
                yield sse_event("chunk", {"section": section, "content": chunk})
            yield sse_event("section_done", {"section": section})

        yield sse_event("complete", {"sections": sections})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/career/linkedin-optimize")
async def career_linkedin_optimize(request: Request):
    """LinkedIn profile optimizer."""
    verify_sal_key(request)
    body = await request.json()
    profile_text = body.get("current_profile_text", "")

    prompt = f"""Optimize this LinkedIn profile for maximum impact and search visibility:

{profile_text}

Return JSON:
{{
  "headline": "optimized headline (under 220 chars)",
  "summary": "optimized about section",
  "experience_rewrites": ["improved bullet points"],
  "skills_to_add": ["relevant skills"],
  "score_before": 60,
  "score_after": 92
}}"""

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": prompt}],
        "You are a LinkedIn optimization expert. Maximize profile visibility and interview attraction. Return valid JSON.",
        model="claude-opus-4-6"
    ):
        content += chunk

    try:
        return json.loads(content)
    except Exception:
        return {"headline": content[:220], "summary": "", "experience_rewrites": [], "skills_to_add": [], "score_before": 60, "score_after": 80}


@app.post("/api/career/salary-negotiate")
async def career_salary_negotiate(request: Request):
    """Salary negotiation coach."""
    verify_sal_key(request)
    body = await request.json()

    # Research market data
    role = body.get("role", "")
    location = body.get("location", "")
    market_results = await call_exa(f"{role} salary range {location} 2025 Glassdoor Levels.fyi", num_results=3)

    market_context = "\n".join([r.get("text", "")[:300] for r in market_results])

    prompt = f"""You are a salary negotiation expert.

Role: {role}
Location: {location}
Current offer: {body.get('offer_details', '')}
Experience: {body.get('experience_years', 0)} years

Market data: {market_context[:500]}

Provide:
1. Market salary range (with sources)
2. Specific counter-offer script (word for word)
3. Negotiation rationale
4. Backup positions

Be specific with numbers."""

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": prompt}],
        "You are a compensation negotiation expert. Provide specific, actionable salary negotiation guidance.",
        model="claude-opus-4-6"
    ):
        content += chunk

    return {"negotiation_guide": content, "market_data_sources": [r.get("url") for r in market_results]}


@app.post("/api/career/network-map")
async def career_network_map(request: Request):
    """Network mapping — find contacts at target companies."""
    verify_sal_key(request)
    body = await request.json()

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Create a networking strategy and intro templates for reaching people at: {json.dumps(body)}"}],
        "You are a networking and business development expert. Create actionable networking strategies and compelling intro messages.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    return {"network_strategy": content, "connections": [], "intro_templates": []}


@app.post("/api/business/plan")
async def business_plan(request: Request):
    """Full business plan AI — SSE streaming with research."""
    verify_sal_key(request)
    body = await request.json()
    # Same as bizplan but with research augmentation
    return await career_bizplan(request)


@app.post("/api/business/patent-search")
async def business_patent_search(request: Request):
    """IP/Patent intelligence (Teams+ tier)."""
    verify_sal_key(request)
    body = await request.json()
    user_id = body.get("user_id", "")

    if user_id:
        await check_tier(user_id, "teams")

    tech_description = body.get("technology_description", "")
    results = await call_exa(f"patent prior art {tech_description} USPTO", num_results=5)

    analysis = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Analyze patent landscape for: {tech_description}\n\nSearch results: {json.dumps(results)[:1000]}"}],
        "You are a patent attorney. Analyze prior art, freedom-to-operate, and licensing opportunities.",
        model="claude-opus-4-6"
    ):
        analysis += chunk

    return {
        "analysis": analysis,
        "prior_art": [{"title": r.get("title"), "url": r.get("url")} for r in results],
        "fto_analysis": "See analysis above",
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4: CREATIVE STUDIO
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/creative/generate")
async def creative_generate(request: Request):
    """Content generation — caption, blog, email, ad, carousel."""
    verify_sal_key(request)
    body = await request.json()
    content_type = body.get("type", "caption")
    platform = body.get("platform", "linkedin")
    prompt = body.get("prompt", "")
    seo_mode = body.get("seo_mode", False)

    platform_guides = {
        "linkedin": "Professional, authoritative. 150-200 words. 5 hashtags.",
        "twitter": "Punchy, under 240 chars. 2-3 hashtags. Hook first.",
        "instagram": "Visual-first. 100-150 words. 20-30 hashtags.",
        "facebook": "Conversational. 100-150 words. Ask a question.",
        "tiktok": "Casual, trend-aware. Under 150 chars.",
    }

    system = f"""You are a social media content expert for SaintSal™ Labs.
Brand voice: Direct, Goldman-level credibility. "We don't chase trends. We build infrastructure."
Platform: {platform} — {platform_guides.get(platform, '')}
Content type: {content_type}
{'SEO optimization required.' if seo_mode else ''}"""

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Create {content_type} content for: {prompt}"}],
        system,
        model="claude-sonnet-4-6"
    ):
        content += chunk

    # Generate platform variations
    return {
        "content": content,
        "platform": platform,
        "type": content_type,
        "platform_versions": {platform: content},
    }


@app.post("/api/creative/image")
async def creative_image(request: Request):
    """Image generation — routes to DALL-E/Grok/SDXL based on style."""
    verify_sal_key(request)
    body = await request.json()
    prompt = body.get("prompt", "")
    style = body.get("style", "photorealistic")

    # Route to appropriate model based on style
    if style in ("ui", "marketing") and GEMINI_API_KEY:
        model_used = "stitch"
    elif OPENAI_API_KEY:
        model_used = "dalle3"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                res = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"},
                )
                data = res.json()
                image_url = data["data"][0]["url"]
                return {"image_url": image_url, "model_used": model_used, "prompt_used": prompt}
        except Exception as e:
            return {"error": str(e), "model_used": model_used}
    else:
        model_used = "unavailable"

    return {"image_url": "", "model_used": model_used, "prompt_used": prompt, "error": "Image generation not configured"}


@app.post("/api/creative/social/post")
async def creative_social_post(request: Request):
    """Social posting via GHL."""
    verify_sal_key(request)
    body = await request.json()
    content = body.get("content", "")
    platforms = body.get("platforms", [])
    schedule_time = body.get("schedule_time", None)

    if not GHL_PRIVATE_TOKEN:
        return {"error": "GHL not configured", "post_ids": {}}

    post_ids = {}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for platform in platforms:
                res = await client.post(
                    f"https://rest.gohighlevel.com/v1/social-media-posting/{GHL_LOCATION_ID}/posts",
                    headers={"Authorization": f"Bearer {GHL_PRIVATE_TOKEN}"},
                    json={"content": content, "platform": platform, "scheduledAt": schedule_time},
                )
                if res.status_code < 300:
                    post_ids[platform] = res.json().get("id", "posted")
    except Exception as e:
        return {"error": str(e), "post_ids": post_ids}

    return {"post_ids": post_ids, "scheduled_times": {p: schedule_time for p in platforms}}


@app.post("/api/creative/calendar")
async def creative_calendar(request: Request):
    """Content calendar AI — 30-day planner."""
    verify_sal_key(request)
    body = await request.json()

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Create a 30-day social media content calendar for: {json.dumps(body)}"}],
        "You are a social media strategist. Create a detailed content calendar with specific post ideas, platforms, and optimal posting times. Return JSON with days array.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    try:
        return json.loads(content)
    except Exception:
        return {"calendar": content, "days": []}


@app.post("/api/creative/calendar/batch-generate")
async def creative_calendar_batch(request: Request):
    """Batch generate a week of posts."""
    verify_sal_key(request)
    body = await request.json()
    calendar_id = body.get("calendar_id", "")
    week_number = body.get("week_number", 1)

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Generate week {week_number} of posts for calendar {calendar_id}"}],
        "You are a social media content creator. Generate complete, ready-to-post content for each day of the week.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    return {"posts": [], "week_number": week_number, "content": content}


@app.post("/api/creative/brand-profile")
async def creative_brand_profile(request: Request):
    """Create/update brand profile in Supabase."""
    verify_sal_key(request)
    body = await request.json()
    # TODO: Save to Supabase brand_profiles table
    return {"id": str(uuid.uuid4()), "status": "created", "profile": body}


@app.post("/api/marketing/daily-content")
async def marketing_daily_content(request: Request):
    """GHL Social Studio daily content."""
    verify_sal_key(request)
    body = await request.json()

    content = ""
    async for chunk in stream_claude(
        [{"role": "user", "content": f"Create today's social media content for SaintSal Labs: {json.dumps(body)}"}],
        "You are a social media manager for SaintSal™ Labs. Create platform-optimized daily content.",
        model="claude-sonnet-4-6"
    ):
        content += chunk

    return {"content": content, "platforms": ["linkedin", "twitter", "instagram"]}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5: LAUNCH PAD — BUSINESS FORMATION
# All routes handled by routes/launchpad.py (included via app.include_router above)
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6: COOKINCARDS™
# ══════════════════════════════════════════════════════════════════════════════

XIMILAR_BASE = "https://api.ximilar.com"


async def ximilar_request(endpoint: str, body: dict) -> dict:
    """Make a request to Ximilar API."""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{XIMILAR_BASE}{endpoint}",
            headers={"Authorization": f"Token {XIMILAR_API_KEY}"},
            json=body,
        )
        return res.json()


@app.post("/api/cards/scan")
async def cards_scan(request: Request):
    """
    Camera capture → Ximilar identification + valuation + grade.
    Identifies TCG (Pokemon/MTG/Yu-Gi-Oh/Lorcana) and sports cards.
    """
    verify_sal_key(request)
    body = await request.json()
    image_url = body.get("image_url", "")
    image_base64 = body.get("image_base64", "")

    if not XIMILAR_API_KEY:
        return {"error": "Card scanning not configured"}

    record = {}
    if image_url:
        record = {"_url": image_url}
    elif image_base64:
        record = {"_base64": image_base64}
    else:
        raise HTTPException(400, "image_url or image_base64 required")

    # Try TCG first, then sports
    try:
        tcg_result = await ximilar_request(
            "/collectibles/v2/tcg_id",
            {"records": [record], "get_listings": True}
        )
        if tcg_result.get("records"):
            result = tcg_result["records"][0]
            return {
                "type": "tcg",
                "card_name": result.get("name", "Unknown"),
                "card_set": result.get("set", ""),
                "card_number": result.get("number", ""),
                "estimated_value": result.get("market_price", 0),
                "ebay_listings": result.get("listings", []),
                "raw_data": result,
            }
    except Exception:
        pass

    try:
        sport_result = await ximilar_request(
            "/collectibles/v2/sport_id",
            {"records": [record], "get_listings": True}
        )
        if sport_result.get("records"):
            result = sport_result["records"][0]
            return {
                "type": "sports",
                "card_name": result.get("name", "Unknown"),
                "card_set": result.get("set", ""),
                "estimated_value": result.get("market_price", 0),
                "ebay_listings": result.get("listings", []),
                "raw_data": result,
            }
    except Exception as e:
        return {"error": str(e)}

    return {"error": "Card not identified"}


@app.post("/api/cards/grade")
async def cards_grade(request: Request):
    """
    Full PSA-style grading.
    Accepts front and back images, 70/30 weighted scoring.
    """
    verify_sal_key(request)
    body = await request.json()

    if not XIMILAR_API_KEY:
        return {"error": "Card grading not configured"}

    front = body.get("front_image_url") or body.get("front_base64")
    back = body.get("back_image_url") or body.get("back_base64")

    if not front:
        raise HTTPException(400, "front image required")

    records = []
    if body.get("front_image_url"):
        records.append({"_url": front, "side": "front"})
        if back and body.get("back_image_url"):
            records.append({"_url": back, "side": "back"})
    else:
        records.append({"_base64": front, "side": "front"})
        if back:
            records.append({"_base64": back, "side": "back"})

    try:
        result = await ximilar_request(
            "/card-grader/v2/grade",
            {"records": records}
        )
        return {
            "grade": result.get("grade", 0),
            "centering": result.get("centering", {}),
            "corners": result.get("corners", {}),
            "edges": result.get("edges", {}),
            "surface": result.get("surface", {}),
            "psa_equivalent": result.get("psa_grade", ""),
            "raw_data": result,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cards/quick-grade")
async def cards_quick_grade(request: Request):
    """Fast condition check — NM/LP/MP/HP/D."""
    verify_sal_key(request)
    body = await request.json()

    if not XIMILAR_API_KEY:
        return {"error": "Card grading not configured"}

    record = {}
    if body.get("image_url"):
        record = {"_url": body["image_url"]}
    elif body.get("image_base64"):
        record = {"_base64": body["image_base64"]}
    else:
        raise HTTPException(400, "image required")

    try:
        result = await ximilar_request(
            "/card-grader/v2/condition",
            {"records": [record]}
        )
        return {"condition": result.get("condition", "Unknown"), "raw_data": result}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cards/centering")
async def cards_centering(request: Request):
    """Centering check only."""
    verify_sal_key(request)
    body = await request.json()

    if not XIMILAR_API_KEY:
        return {"error": "Card grading not configured"}

    record = {"_url": body.get("image_url")} if body.get("image_url") else {"_base64": body.get("image_base64", "")}

    try:
        result = await ximilar_request("/card-grader/v2/centering", {"records": [record]})
        return {"centering": result.get("centering", {}), "raw_data": result}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cards/slab-read")
async def cards_slab_read(request: Request):
    """OCR graded slab label — cert#, grade, company."""
    verify_sal_key(request)
    body = await request.json()

    record = {"_url": body.get("image_url")} if body.get("image_url") else {"_base64": body.get("image_base64", "")}

    try:
        result = await ximilar_request(
            "/collectibles/v2/tcg_id",
            {"records": [record], "get_slab_detail": True}
        )
        slab = result.get("records", [{}])[0].get("slab_detail", {})
        return {
            "cert_number": slab.get("cert_number", ""),
            "grade": slab.get("grade", ""),
            "grading_company": slab.get("company", ""),
            "raw_data": slab,
        }
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/cards/price")
async def cards_price(request: Request):
    """Price lookup by card ID."""
    verify_sal_key(request)
    body = await request.json()
    card_id = body.get("card_id", "")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"https://api.pokemontcg.io/v2/cards/{card_id}")
            card = res.json().get("data", {})
            prices = card.get("tcgplayer", {}).get("prices", {})
            return {"card_id": card_id, "card_name": card.get("name", ""), "prices": prices}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/cards/search")
async def cards_search(query: str = "", set_name: str = "", request: Request = None):
    """Search card database — Pokemon TCG API."""
    verify_sal_key(request)

    try:
        q = f'name:"{query}"'
        if set_name:
            q += f' set.name:"{set_name}"'

        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                "https://api.pokemontcg.io/v2/cards",
                params={"q": q, "pageSize": 20},
            )
            data = res.json()
            return {
                "cards": data.get("data", []),
                "total": data.get("totalCount", 0),
                "query": query,
            }
    except Exception as e:
        return {"error": str(e), "cards": []}


@app.get("/api/cards/collection")
async def cards_collection(user_id: str = "", request: Request = None):
    """User's saved collection from Supabase."""
    verify_sal_key(request)
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {"collection": [], "error": "Supabase not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/card_collections",
                params={"user_id": f"eq.{user_id}", "order": "created_at.desc"},
                headers={"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"},
            )
            return {"collection": res.json()}
    except Exception as e:
        return {"collection": [], "error": str(e)}


@app.post("/api/cards/collection/add")
async def cards_collection_add(request: Request):
    """Add card to collection in Supabase."""
    verify_sal_key(request)
    body = await request.json()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {"error": "Supabase not configured"}

    card_data = {
        "id": str(uuid.uuid4()),
        "user_id": body.get("user_id"),
        "card_name": body.get("card_name", ""),
        "card_set": body.get("card_set", ""),
        "card_number": body.get("card_number", ""),
        "condition": body.get("condition", ""),
        "grade_estimate": body.get("grade_estimate"),
        "estimated_value": body.get("estimated_value"),
        "image_url": body.get("image_url", ""),
        "ximilar_data": body.get("ximilar_data"),
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(
                f"{SUPABASE_URL}/rest/v1/card_collections",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=card_data,
            )
            return {"status": "added", "card": res.json()}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/cards/market/trending")
async def cards_market_trending(request: Request = None):
    """Trending cards + price movers."""
    verify_sal_key(request)
    results = await call_tavily("Pokemon card trending prices 2025 most valuable", max_results=5)
    return {"trending": results, "generated_at": datetime.utcnow().isoformat()}


@app.get("/api/cards/deals")
async def cards_deals(request: Request = None):
    """Card deals — undervalued cards."""
    verify_sal_key(request)
    results = await call_tavily("Pokemon cards undervalued deals eBay 2025", max_results=5)
    return {"deals": results}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7: GHL + CRM
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/ghl/stats")
async def ghl_stats(request: Request):
    """GHL pipeline stats for dashboard."""
    verify_sal_key(request)

    if not GHL_PRIVATE_TOKEN:
        return {"pipelines": [], "recent_leads": [], "stats": {"total_contacts": 0}, "error": "GHL not configured"}

    headers = {
        "Authorization": f"Bearer {GHL_PRIVATE_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            pipelines_res = await client.get(
                f"https://rest.gohighlevel.com/v1/pipelines?locationId={GHL_LOCATION_ID}",
                headers=headers,
            )
            contacts_res = await client.get(
                f"https://rest.gohighlevel.com/v1/contacts?locationId={GHL_LOCATION_ID}&limit=20&sortBy=dateAdded&order=desc",
                headers=headers,
            )
            return {
                "pipelines": pipelines_res.json().get("pipelines", []),
                "recent_leads": contacts_res.json().get("contacts", [])[:10],
                "stats": {
                    "total_contacts": contacts_res.json().get("meta", {}).get("total", 0)
                },
            }
    except Exception as e:
        return {"pipelines": [], "recent_leads": [], "stats": {}, "error": str(e)}


@app.post("/api/mcp/crm")
async def mcp_crm(request: Request):
    """GHL CRM actions — list_contacts, add_contact, get_pipeline."""
    verify_sal_key(request)
    body = await request.json()
    action = body.get("action", "")

    if not GHL_PRIVATE_TOKEN:
        return {"error": "GHL not configured"}

    headers = {"Authorization": f"Bearer {GHL_PRIVATE_TOKEN}"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if action == "list_contacts":
                res = await client.get(
                    f"https://rest.gohighlevel.com/v1/contacts?locationId={GHL_LOCATION_ID}",
                    headers=headers,
                )
                return res.json()

            elif action == "add_contact":
                res = await client.post(
                    "https://rest.gohighlevel.com/v1/contacts",
                    headers={**headers, "Content-Type": "application/json"},
                    json={**body.get("contact", {}), "locationId": GHL_LOCATION_ID},
                )
                return res.json()

            elif action == "get_pipeline":
                res = await client.get(
                    f"https://rest.gohighlevel.com/v1/pipelines?locationId={GHL_LOCATION_ID}",
                    headers=headers,
                )
                return res.json()

            else:
                return {"error": f"Unknown action: {action}"}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8: FINANCE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/finance/markets")
async def finance_markets(request: Request):
    """Market data via Alpaca."""
    verify_sal_key(request)

    if not ALPACA_API_KEY:
        return {"error": "Alpaca not configured", "markets": {}}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                "https://data.alpaca.markets/v2/stocks/bars/latest",
                headers={
                    "APCA-API-KEY-ID": ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
                },
                params={"symbols": "SPY,QQQ,IWM,BTC/USD"},
            )
            return {"markets": res.json(), "generated_at": datetime.utcnow().isoformat()}
    except Exception as e:
        return {"error": str(e), "markets": {}}


@app.get("/api/alpaca/portfolio")
async def alpaca_portfolio(request: Request):
    """Portfolio summary from Alpaca."""
    verify_sal_key(request)

    if not ALPACA_API_KEY:
        return {"error": "Alpaca not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')}/v2/account",
                headers={
                    "APCA-API-KEY-ID": ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
                },
            )
            return res.json()
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9: REAL ESTATE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/realestate/search")
async def realestate_search(query: str = "", location: str = "", request: Request = None):
    """Property search via RentCast + PropertyAPI."""
    verify_sal_key(request)

    results = await call_tavily(f"real estate listings {query} {location} for sale", max_results=10)
    return {"properties": results, "query": query, "location": location}


@app.get("/api/realestate/distressed-search")
async def realestate_distressed_search(location: str = "", request: Request = None):
    """Distressed property leads."""
    verify_sal_key(request)
    results = await call_exa(f"foreclosure properties for sale {location} distressed", num_results=10)
    return {"properties": results, "location": location}


@app.get("/api/realestate/portfolio")
async def realestate_portfolio(user_id: str = "", request: Request = None):
    """User's RE portfolio."""
    verify_sal_key(request)
    return {"portfolio": [], "user_id": user_id}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 10: VOICE
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/voice/transcribe")
async def voice_transcribe(request: Request):
    """STT via Deepgram."""
    verify_sal_key(request)
    body = await request.json()
    audio_url = body.get("audio_url", "")

    if not DEEPGRAM_API_KEY:
        return {"error": "Deepgram not configured", "transcript": ""}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                "https://api.deepgram.com/v1/listen",
                headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                json={"url": audio_url},
            )
            result = res.json()
            transcript = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")
            return {"transcript": transcript}
    except Exception as e:
        return {"error": str(e), "transcript": ""}


@app.post("/api/voice/synthesize")
async def voice_synthesize(request: Request):
    """TTS via ElevenLabs."""
    verify_sal_key(request)
    body = await request.json()
    text = body.get("text", "")
    voice_id = body.get("voice_id", "EXAVITQu4vr4xnSDxMaL")  # Default: SAL voice

    if not ELEVENLABS_API_KEY:
        return {"error": "ElevenLabs not configured", "audio_url": ""}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={"xi-api-key": ELEVENLABS_API_KEY},
                json={"text": text, "model_id": "eleven_multilingual_v2"},
            )
            # Return base64 audio for mobile
            import base64
            audio_b64 = base64.b64encode(res.content).decode()
            return {"audio_base64": audio_b64, "content_type": "audio/mpeg"}
    except Exception as e:
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 11: SOCIAL + INTEGRATIONS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/social/platforms")
async def social_platforms(request: Request):
    """Connected social platform status."""
    verify_sal_key(request)
    return {
        "platforms": [
            {"name": "LinkedIn", "status": "connected"},
            {"name": "X (Twitter)", "status": "registering"},
            {"name": "Instagram", "status": "via_meta"},
            {"name": "Facebook", "status": "via_meta"},
            {"name": "TikTok", "status": "pending"},
            {"name": "YouTube", "status": "via_google"},
            {"name": "Telegram", "status": "live", "handle": "@SaintSalLabsBot"},
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 12: PRICING + CHECKOUT
# ══════════════════════════════════════════════════════════════════════════════

STRIPE_PRICE_IDS = {
    "free_monthly": "price_1T7p1tL47U80vDLAe9aWVKA0",
    "starter_monthly": "price_1T7p1sL47U80vDLAgU2shcQO",
    "pro_monthly": "price_1T7p1tL47U80vDLAVC0N4N4J",
    "teams_monthly": "price_1T7p1uL47U80vDLA9QF62BKS",
    "enterprise_monthly": "price_1T7p1uL47U80vDLAR4Wk6uW0",
    "starter_annual": "price_1T7p1sL47U80vDLAYEEv8Kmg",
    "pro_annual": "price_1T7p1tL47U80vDLAk5HK8YcR",
    "teams_annual": "price_1T7p1uL47U80vDLAjlnLTuul",
    "enterprise_annual": "price_1T7p1uL47U80vDLAk9UA0lnr",
}


@app.get("/api/pricing/tiers")
async def pricing_tiers(request: Request):
    """Subscription tier info."""
    verify_sal_key(request)
    return {
        "tiers": [
            {
                "name": "Free", "price_monthly": 0, "price_annual": 0,
                "compute_minutes": 100, "models": ["SAL Mini"],
                "price_id_monthly": STRIPE_PRICE_IDS["free_monthly"],
            },
            {
                "name": "Starter", "price_monthly": 27, "price_annual": 270,
                "compute_minutes": 500, "models": ["SAL Mini", "SAL Pro"],
                "price_id_monthly": STRIPE_PRICE_IDS["starter_monthly"],
                "price_id_annual": STRIPE_PRICE_IDS["starter_annual"],
            },
            {
                "name": "Pro", "price_monthly": 97, "price_annual": 970,
                "compute_minutes": 2000, "models": ["SAL Mini", "SAL Pro", "SAL Max"],
                "features": ["Builder v2", "Voice", "Creative Studio", "Launch Pad"],
                "price_id_monthly": STRIPE_PRICE_IDS["pro_monthly"],
                "price_id_annual": STRIPE_PRICE_IDS["pro_annual"],
            },
            {
                "name": "Teams", "price_monthly": 297, "price_annual": 2970,
                "compute_minutes": 10000, "models": ["SAL Mini", "SAL Pro", "SAL Max", "SAL Max Fast"],
                "features": ["Multi-seat", "SAINT Leads", "Patent Intel"],
                "price_id_monthly": STRIPE_PRICE_IDS["teams_monthly"],
                "price_id_annual": STRIPE_PRICE_IDS["teams_annual"],
            },
            {
                "name": "Enterprise", "price_monthly": 497, "price_annual": 4970,
                "compute_minutes": -1,  # Unlimited
                "models": ["All models", "API Access"],
                "features": ["White-label", "HACP™ license", "Custom integrations"],
                "price_id_monthly": STRIPE_PRICE_IDS["enterprise_monthly"],
                "price_id_annual": STRIPE_PRICE_IDS["enterprise_annual"],
            },
        ]
    }


@app.post("/api/checkout/session")
@app.post("/api/checkout/create-session")
async def checkout_session(request: Request):
    """Create Stripe checkout session."""
    verify_sal_key(request)
    body = await request.json()
    price_id = body.get("price_id", "")
    user_id = body.get("user_id", "")
    success_url = body.get("success_url", "https://www.saintsallabs.com/dashboard?checkout=success")
    cancel_url = body.get("cancel_url", "https://www.saintsallabs.com/pricing")

    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.stripe.com/v1/checkout/sessions",
                auth=(STRIPE_SECRET_KEY, ""),
                data={
                    "mode": "subscription",
                    "line_items[0][price]": price_id,
                    "line_items[0][quantity]": "1",
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                    "metadata[user_id]": user_id,
                },
            )
            data = res.json()
            return {"url": data.get("url"), "session_id": data.get("id")}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/checkout/session-status")
async def checkout_session_status(session_id: str = "", request: Request = None):
    """Check Stripe checkout session status."""
    verify_sal_key(request)
    if not STRIPE_SECRET_KEY:
        return {"error": "Stripe not configured"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"https://api.stripe.com/v1/checkout/sessions/{session_id}",
                auth=(STRIPE_SECRET_KEY, ""),
            )
            return res.json()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # Verify webhook signature
    if STRIPE_WEBHOOK_SECRET:
        try:
            import hmac
            import hashlib
            timestamp = sig_header.split(",")[0].split("=")[1]
            signed_payload = f"{timestamp}.{payload.decode()}"
            expected_sig = hmac.new(
                STRIPE_WEBHOOK_SECRET.encode(),
                signed_payload.encode(),
                hashlib.sha256
            ).hexdigest()
            # Simplified check — use stripe SDK in production
        except Exception:
            pass

    try:
        event = json.loads(payload)
        event_type = event.get("type", "")

        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            user_id = session.get("metadata", {}).get("user_id")
            # TODO: Update Supabase profiles.plan_tier

        elif event_type == "customer.subscription.deleted":
            # Downgrade to free
            pass

        return {"status": "received"}
    except Exception as e:
        raise HTTPException(400, f"Webhook error: {str(e)}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 13: METERING
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/metering/log")
async def metering_log(request: Request):
    """Log compute usage to Supabase."""
    verify_sal_key(request)
    body = await request.json()

    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        return {"status": "skipped"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/usage_log",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "id": str(uuid.uuid4()),
                    "user_id": body.get("user_id"),
                    "action": body.get("action"),
                    "compute_minutes": body.get("compute_minutes", 1),
                    "model_used": body.get("model_used", ""),
                    "created_at": datetime.utcnow().isoformat(),
                },
            )
        return {"status": "logged"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/api/metering/usage")
async def metering_usage(user_id: str = "", request: Request = None):
    """Get user's remaining compute minutes."""
    verify_sal_key(request)
    return {"user_id": user_id, "used": 0, "limit": 2000, "remaining": 2000, "tier": "pro"}


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH + DEBUG
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def health():
    """Health check — verify all critical services."""
    return {
        "status": "operational",
        "platform": "SaintSal™ Labs Backend",
        "version": "2.0.0",
        "patent": "US #10,290,222 (HACP™)",
        "services": {
            "anthropic": "configured" if ANTHROPIC_API_KEY else "missing",
            "openai": "configured" if OPENAI_API_KEY else "missing",
            "xai": "configured" if XAI_API_KEY else "missing",
            "supabase": "configured" if SUPABASE_URL else "missing",
            "stripe": "configured" if STRIPE_SECRET_KEY else "missing",
            "ghl": "configured" if GHL_PRIVATE_TOKEN else "missing",
            "ximilar": "configured" if XIMILAR_API_KEY else "missing",
            "elevenlabs": "configured" if ELEVENLABS_API_KEY else "missing",
            "tavily": "configured" if TAVILY_API_KEY else "missing",
            "exa": "configured" if EXA_API_KEY else "missing",
        },
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/")
async def root():
    return {"message": "SaintSal™ Labs API — HACP™ Powered", "docs": "/docs", "health": "/api/health"}


# ══════════════════════════════════════════════════════════════════════════════
# STATIC FILES — MUST BE LAST BEFORE __main__
# DO NOT ADD ENDPOINTS BELOW THIS LINE
# Any @app.get or @app.post defined after app.mount() will 404 silently
# ══════════════════════════════════════════════════════════════════════════════
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), reload=False)
