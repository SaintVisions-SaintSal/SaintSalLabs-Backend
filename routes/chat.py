"""
SaintSal™ Labs — Chat & Intelligence Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)

Routes:
  POST /api/mcp/chat          — SSE streaming chat, 8 intelligence verticals
  GET  /api/verticals/trending — Trending content per vertical (Tavily/Exa)
  POST /api/mcp/crm           — GHL CRM actions
"""

import os
import json
from datetime import datetime
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx

router = APIRouter()

# ── Credentials ───────────────────────────────────────────────────────────────

ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
XAI_KEY        = os.environ.get("XAI_API_KEY", "")
TAVILY_KEY     = os.environ.get("TAVILY_API_KEY", "")
EXA_KEY        = os.environ.get("EXA_API_KEY", "")
GHL_TOKEN      = os.environ.get("GHL_PRIVATE_TOKEN", "")
GHL_LOCATION   = os.environ.get("GHL_LOCATION_ID", "oRA8vL3OSiCPjpwmEC0V")
SAL_GATEWAY    = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")

# ── Vertical System Prompts ───────────────────────────────────────────────────

VERTICAL_SYSTEM_PROMPTS = {
    "sports": """You are SAL, a sports intelligence engine for SaintSal™ Labs.
You have live internet access via Tavily web search. ALWAYS use search results provided to you.
NEVER say you lack access to live data — you have it in the context above.
Report exact scores, standings, and injury reports using the search results.
Layer in betting lines, fantasy implications, and game analysis when relevant.
Be direct, fast, and precise. Sports fans want facts, not hedging.""",

    "search": """You are SAL, a deep research intelligence engine for SaintSal™ Labs.
Use the web search context provided to synthesize comprehensive, accurate answers.
Cite sources by domain name inline (e.g. reuters.com). Always prefer primary sources.
Structure complex answers with headers and bullet points. Never make up facts.""",

    "finance": """You are SAL, a finance and capital markets intelligence engine for SaintSal™ Labs.
Leverage web search context for current market data. Provide DCF/LBO framing when relevant.
Cover portfolio strategy, market movers, macro commentary, and earnings analysis.
Always include: this is intelligence analysis, not licensed financial advice.""",

    "realestate": """You are SAL, a real estate intelligence engine for SaintSal™ Labs.
Use web search results for current market data. Cover cap rates, rent estimates, comps.
Analyze distressed opportunities, 1031 exchanges, market trends, and investment thesis.
Always include: consult a licensed broker before transacting.""",

    "medical": """You are SAL, a healthcare intelligence engine for SaintSal™ Labs.
Zero hallucination tolerance. Only state what is supported by the search context or established medical knowledge.
Cover ICD-10/CPT codes, drug interactions, clinical trial summaries, and differential diagnoses.
ALWAYS end responses with: "This is informational only. Consult a licensed physician for medical decisions."
Never recommend specific dosages without the caveat above.""",

    "legal": """You are SAL, a legal intelligence engine for SaintSal™ Labs.
Use search context for current case law and legislation. Cover contract analysis, IP strategy, entity formation.
Cite relevant statutes and cases when possible.
ALWAYS end responses with: "This is informational only. Consult a licensed attorney before taking legal action."
Never tell a user to take action without the caveat above.""",

    "technology": """You are SAL, a technology intelligence engine for SaintSal™ Labs.
Write working, production-quality code — not pseudocode. Use modern patterns and current versions.
Review architecture decisions critically. Flag anti-patterns.
Cover AI/ML, infrastructure, security, APIs, and system design.
When writing code, always include error handling.""",

    "govdefense": """You are SAL, a government and defense intelligence engine for SaintSal™ Labs.
Cover FAR/DFARS compliance, source selection, political strategy, and defense procurement.
Handle HUMINT/SIGINT/CISA topics with appropriate operational care.
Provide compliance analysis, proposal strategy, and regulatory guidance.
Always note classification boundaries — never handle material above FOUO.""",
}

# ── Model Routing ─────────────────────────────────────────────────────────────

# Maps vertical → (claude_model, use_grok_primary, fallback_allowed)
VERTICAL_MODEL_MAP = {
    "sports":     ("claude-opus-4-6",   True,  True),   # Grok primary, Claude fallback
    "search":     ("claude-opus-4-6",   False, True),
    "finance":    ("claude-opus-4-6",   False, True),
    "realestate": ("claude-sonnet-4-5", False, True),
    "medical":    ("claude-opus-4-6",   False, False),   # Opus ONLY — no fallback to Grok
    "legal":      ("claude-opus-4-6",   False, False),
    "technology": ("claude-sonnet-4-5", False, True),
    "govdefense": ("claude-opus-4-6",   False, False),
}

# Verticals that always search before answering
SEARCH_VERTICALS = {"sports", "search", "finance", "realestate", "medical", "legal", "govdefense"}

# ── Auth Guard ────────────────────────────────────────────────────────────────

def _verify_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY:
        raise HTTPException(status_code=403, detail="Invalid gateway key")

# ── SSE Helpers ───────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


def _sse_chunk(content: str) -> str:
    return f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"


def _sse_done(extra: dict = None) -> str:
    payload = {"type": "done"}
    if extra:
        payload.update(extra)
    return f"data: {json.dumps(payload)}\n\n"


def _sse_error(message: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': message})}\n\n"

# ── External API Helpers ──────────────────────────────────────────────────────

async def _tavily_search(query: str, max_results: int = 6) -> list:
    """Perform a Tavily web search. Returns list of result dicts."""
    if not TAVILY_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_KEY,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                },
            )
            res.raise_for_status()
            return res.json().get("results", [])
    except Exception:
        return []


async def _exa_search(query: str, num_results: int = 5) -> list:
    """Perform an Exa neural search. Returns list of result dicts."""
    if not EXA_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_KEY},
                json={"query": query, "numResults": num_results, "contents": {"text": True}},
            )
            res.raise_for_status()
            return res.json().get("results", [])
    except Exception:
        return []


def _build_search_context(results: list, max_per_result: int = 600) -> str:
    """Convert raw search results into a clean context string for the LLM."""
    lines = []
    for i, r in enumerate(results[:5], 1):
        url = r.get("url", r.get("link", ""))
        title = r.get("title", "")
        content = r.get("content", r.get("text", ""))[:max_per_result]
        published = r.get("published_date", "")
        date_str = f" ({published})" if published else ""
        lines.append(f"[{i}] {title}{date_str}\nSource: {url}\n{content}")
    return "\n\n".join(lines)


async def _stream_claude(
    messages: list,
    system: str,
    model: str = "claude-opus-4-6",
) -> AsyncIterator[str]:
    """Async generator: yields text chunks from Claude streaming API."""
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_KEY)
        async with client.messages.stream(
            model=model,
            max_tokens=8192,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        raise RuntimeError(f"Claude stream error: {str(e)[:200]}")


async def _call_grok(messages: list, system: str) -> str:
    """Non-streaming Grok call. Returns full response string."""
    if not XAI_KEY:
        raise RuntimeError("XAI_API_KEY not configured")
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            "https://api.x.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {XAI_KEY}"},
            json={
                "model": "grok-beta",
                "messages": [{"role": "system", "content": system}, *messages],
                "max_tokens": 8192,
                "stream": False,
            },
        )
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"]

# ── Request Models ────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    vertical: str = "search"
    model: Optional[str] = None
    conversation_id: Optional[str] = None
    user_id: Optional[str] = None
    conversation_history: Optional[list] = None   # [{role, content}, ...]
    team_ids: Optional[list] = None
    news_prefs: Optional[list] = None


class CRMRequest(BaseModel):
    action: str = "list_contacts"
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    tags: Optional[list] = None
    user_id: Optional[str] = None

# ══════════════════════════════════════════════════════════════════════════════
# POST /api/mcp/chat
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/api/mcp/chat")
async def mcp_chat(body: ChatRequest, request: Request):
    """
    SSE streaming chat — 8 intelligence verticals.

    Flow:
      1. Verify gateway key
      2. Resolve system prompt + model config for vertical
      3. If search vertical: run Tavily (fallback Exa) and inject context
      4. Stream primary model (Grok for sports, Claude for all others)
      5. On failure: fallback to secondary model or return error event
    """
    _verify_key(request)

    vertical = body.vertical.lower().strip()
    if vertical not in VERTICAL_SYSTEM_PROMPTS:
        vertical = "search"

    system_prompt = VERTICAL_SYSTEM_PROMPTS[vertical]
    claude_model, grok_primary, fallback_allowed = VERTICAL_MODEL_MAP.get(
        vertical, ("claude-opus-4-6", False, True)
    )

    # Override model if caller requested one explicitly
    if body.model:
        model_override = body.model.lower()
        if "opus" in model_override:
            claude_model = "claude-opus-4-6"
        elif "sonnet" in model_override:
            claude_model = "claude-sonnet-4-5"

    # Build message history for multi-turn context
    history = body.conversation_history or []
    messages = [
        {"role": m["role"], "content": m["content"]}
        for m in history[-20:]
        if m.get("role") in ("user", "assistant") and m.get("content")
    ]
    messages.append({"role": "user", "content": body.message})

    # ── Web search pre-fetch (sports always searches, others when key available) ──
    search_context = ""
    if vertical in SEARCH_VERTICALS and (TAVILY_KEY or EXA_KEY):
        results = []
        if TAVILY_KEY:
            results = await _tavily_search(body.message, max_results=6)
        if not results and EXA_KEY:
            results = await _exa_search(body.message, num_results=5)

        if results:
            search_context = _build_search_context(results)
            system_prompt = (
                system_prompt
                + f"\n\n=== LIVE WEB SEARCH RESULTS (use these to answer) ===\n{search_context}"
            )

    # ── SSE Generator ─────────────────────────────────────────────────────────
    async def generate():
        # Sports vertical: try Grok first, fall back to Claude
        if grok_primary and XAI_KEY:
            try:
                grok_response = await _call_grok(messages, system_prompt)
                # Emit word-by-word to simulate streaming (Grok is non-streaming here)
                words = grok_response.split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == len(words) - 1 else word + " "
                    yield _sse_chunk(chunk)
                yield _sse_done({"model_used": "grok", "vertical": vertical})
                return
            except Exception:
                pass  # Fall through to Claude

        # Primary: Claude streaming
        try:
            async for chunk in _stream_claude(messages, system_prompt, claude_model):
                yield _sse_chunk(chunk)
            yield _sse_done({"model_used": claude_model, "vertical": vertical})
            return
        except Exception as claude_err:
            pass  # Fall through to Grok fallback

        # Fallback: Grok (only if vertical allows it)
        if fallback_allowed and XAI_KEY:
            try:
                grok_response = await _call_grok(messages, system_prompt)
                words = grok_response.split(" ")
                for i, word in enumerate(words):
                    chunk = word if i == len(words) - 1 else word + " "
                    yield _sse_chunk(chunk)
                yield _sse_done({"model_used": "grok-fallback", "vertical": vertical})
                return
            except Exception as grok_err:
                yield _sse_error(
                    f"All models failed for {vertical}. "
                    f"Last error: {str(grok_err)[:120]}"
                )
                return

        # No fallback permitted (medical/legal/govdefense) or no fallback key
        yield _sse_error(
            f"Primary model unavailable for {vertical} vertical. "
            "This vertical requires Claude Opus for accuracy. Please try again shortly."
        )

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/verticals/trending
# ══════════════════════════════════════════════════════════════════════════════

TRENDING_QUERIES = {
    "sports":     "live sports scores today NBA NFL MLB NHL breaking news",
    "search":     "breaking news top stories world today",
    "finance":    "stock market movers today S&P 500 earnings",
    "realestate": "real estate market trends housing prices 2025",
    "medical":    "medical research breakthroughs clinical trials health news",
    "legal":      "supreme court rulings legal news legislation 2025",
    "technology": "AI news tech startups programming 2025",
    "govdefense": "government policy defense contracts procurement news",
}


@router.get("/api/verticals/trending")
async def verticals_trending(
    vertical: str = "search",
    user_id: Optional[str] = None,
    request: Request = None,
):
    """
    Trending content per vertical.
    Fetches from Tavily (fallback: Exa). Returns normalized article list.
    """
    _verify_key(request)

    vertical = vertical.lower().strip()
    query = TRENDING_QUERIES.get(vertical, "latest news today")

    articles = []
    try:
        if TAVILY_KEY:
            raw = await _tavily_search(query, max_results=8)
        elif EXA_KEY:
            raw = await _exa_search(query, num_results=8)
        else:
            raw = []

        for r in raw:
            url = r.get("url", r.get("link", ""))
            source = ""
            if url:
                try:
                    source = url.split("//")[-1].split("/")[0].replace("www.", "")
                except Exception:
                    source = url

            articles.append({
                "title":        r.get("title", "Untitled"),
                "source":       source,
                "url":          url,
                "content":      r.get("content", r.get("text", ""))[:250],
                "published_at": r.get("published_date", ""),
                "score":        r.get("score", 0),
            })

    except Exception:
        pass  # Return empty list gracefully

    return JSONResponse({
        "vertical":     vertical,
        "articles":     articles,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/mcp/crm
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/api/mcp/crm")
async def mcp_crm(body: CRMRequest, request: Request):
    """
    GHL CRM actions.

    Actions:
      list_contacts — Returns up to 20 contacts for the GHL location
      add_contact   — Creates a new contact (firstName, lastName, email, phone, tags)
      get_pipeline  — Returns all pipelines for the GHL location
    """
    _verify_key(request)

    if not GHL_TOKEN:
        raise HTTPException(status_code=503, detail="GHL integration not configured")

    headers = {
        "Authorization": f"Bearer {GHL_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:

            if body.action == "list_contacts":
                res = await client.get(
                    "https://rest.gohighlevel.com/v1/contacts/",
                    headers=headers,
                    params={"locationId": GHL_LOCATION, "limit": 20},
                )
                res.raise_for_status()
                return JSONResponse({
                    "ok": True,
                    "contacts": res.json().get("contacts", []),
                })

            elif body.action == "add_contact":
                contact_data = {
                    "locationId": GHL_LOCATION,
                    "firstName":  body.firstName or "",
                    "lastName":   body.lastName or "",
                    "email":      body.email or "",
                    "phone":      body.phone or "",
                    "tags":       body.tags or [],
                }
                res = await client.post(
                    "https://rest.gohighlevel.com/v1/contacts/",
                    headers=headers,
                    json=contact_data,
                )
                res.raise_for_status()
                return JSONResponse({
                    "ok":      True,
                    "contact": res.json(),
                })

            elif body.action == "get_pipeline":
                res = await client.get(
                    "https://rest.gohighlevel.com/v1/pipelines/",
                    headers=headers,
                    params={"locationId": GHL_LOCATION},
                )
                res.raise_for_status()
                return JSONResponse({
                    "ok":       True,
                    "pipelines": res.json().get("pipelines", []),
                })

            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown CRM action: '{body.action}'. "
                           "Valid actions: list_contacts, add_contact, get_pipeline",
                )

    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"GHL API error {e.response.status_code}: {e.response.text[:200]}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CRM request failed: {str(e)[:200]}")
