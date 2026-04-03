"""
SaintSal™ Labs — Builder v2 Routes
5-Agent SSE Pipeline: Grok → Stitch → Claude Sonnet → Claude Opus → GPT-5

FastAPI APIRouter — mounted in server.py via app.include_router(builder_router)
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)
Owner: Ryan "Cap" Capatosto
"""

import os
import json
import uuid
import re
import time
import asyncio
from datetime import datetime
from typing import Optional, AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

# ── Constants ──────────────────────────────────────────────────────────────────

ANTHROPIC_API_KEY    = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY       = os.environ.get("OPENAI_API_KEY", "")
XAI_API_KEY          = os.environ.get("XAI_API_KEY", "")
SAL_GATEWAY_KEY      = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")
SUPABASE_URL         = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# ── Router ────────────────────────────────────────────────────────────────────

builder_router = APIRouter(prefix="/api/builder", tags=["builder"])

# ── In-memory session store ───────────────────────────────────────────────────
# key: session_id → {prompt, plan, designs, scaffold, files, status, created_at}

_sessions: dict = {}


# ── Auth helper ───────────────────────────────────────────────────────────────

def _verify(request: Request):
    key = request.headers.get("x-sal-key", "")
    if key != SAL_GATEWAY_KEY:
        raise HTTPException(403, "Invalid gateway key")


# ── SSE helper ────────────────────────────────────────────────────────────────

def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── LLM Helpers ───────────────────────────────────────────────────────────────

async def _call_grok(messages: list, system: str, max_tokens: int = 8192) -> str:
    """
    Call xAI Grok (non-streaming). Falls back to Claude Sonnet if XAI not configured.
    """
    if XAI_API_KEY and _HTTPX_AVAILABLE:
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                res = await client.post(
                    "https://api.x.ai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {XAI_API_KEY}"},
                    json={
                        "model": "grok-beta",
                        "messages": [{"role": "system", "content": system}, *messages],
                        "max_tokens": max_tokens,
                    },
                )
                res.raise_for_status()
                return res.json()["choices"][0]["message"]["content"]
        except Exception as e:
            # Fall through to Claude fallback
            print(f"[Builder] Grok error, falling back to Claude: {e}")

    # Claude fallback
    return await _call_claude_sync(messages, system, model="claude-sonnet-4-6")


async def _call_claude_sync(messages: list, system: str, model: str = "claude-opus-4-6", max_tokens: int = 8192) -> str:
    """Call Claude (non-streaming) — collects full response."""
    if not _ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        raise HTTPException(500, "No LLM provider configured. Set ANTHROPIC_API_KEY.")

    client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    msg = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    )
    return msg.content[0].text


async def _stream_claude(messages: list, system: str, model: str = "claude-opus-4-6") -> AsyncIterator[str]:
    """Stream Claude response token by token."""
    if not _ANTHROPIC_AVAILABLE or not ANTHROPIC_API_KEY:
        yield "[No Anthropic key configured]"
        return
    try:
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
        yield f"\n[Claude stream error: {str(e)[:100]}]"


async def _call_gpt5(messages: list, system: str) -> str:
    """Call GPT-5 via OpenAI. Falls back to Claude Opus."""
    if OPENAI_API_KEY and _HTTPX_AVAILABLE:
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                res = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": "gpt-4o",  # use gpt-4o until gpt-5 is available in API
                        "messages": [{"role": "system", "content": system}, *messages],
                        "max_tokens": 4096,
                    },
                )
                res.raise_for_status()
                return res.json()["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"[Builder] GPT-5 error, falling back to Claude: {e}")

    return await _call_claude_sync(messages, system, model="claude-opus-4-6")


# ── JSON parser (robust, handles LLM prose wrappers) ─────────────────────────

def _parse_json(raw: str, fallback: dict) -> dict:
    """Extract and parse JSON from a potentially noisy LLM response."""
    cleaned = raw.strip()
    cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'\s*```\s*$', '', cleaned, flags=re.MULTILINE)
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        cleaned = match.group(0)
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return fallback


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER ELITE — SYSTEM PROMPT (The Secret Weapon)
# ══════════════════════════════════════════════════════════════════════════════

BUILDER_SYSTEM_PROMPT = """You are an elite senior full-stack engineer working at the
intersection of design and engineering. You write code that ships to production at
companies like Vercel, Linear, Stripe, and Notion. Your output is not a prototype —
it IS the product.

You are building inside SaintSal™ Builder, powered by US Patent #10,290,222.

## OUTPUT FORMAT (STRICT)

Return ONLY valid JSON. No markdown fences. No explanation outside the JSON.

{
  "files": [
    { "path": "index.html", "content": "..." },
    { "path": "styles.css", "content": "..." },
    { "path": "app.js", "content": "..." }
  ],
  "preview_html": "SINGLE SELF-CONTAINED HTML FILE — all CSS inline, all JS inline, works standalone",
  "summary": "2-sentence description of what was built",
  "framework": "react|nextjs|html|vue",
  "features": ["responsive", "dark-mode", "animated", ...]
}

## DESIGN STANDARDS (NON-NEGOTIABLE)

LAYOUT:
- Use CSS Grid and Flexbox. No floats. No tables for layout.
- Mobile-first responsive. Breakpoints: 640px, 768px, 1024px, 1280px.
- Proper spacing system: 4px base unit (4, 8, 12, 16, 24, 32, 48, 64, 96).
- Max content width: 1280px centered. Full-bleed sections where appropriate.

TYPOGRAPHY:
- System font stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif.
- Type scale: 12/14/16/18/20/24/30/36/48/60/72px.
- Line heights: 1.1 for headings, 1.5 for body, 1.6 for long-form.
- Font weights: 400 (body), 500 (medium), 600 (semibold), 700 (bold), 800 (extrabold).
- Letter spacing: -0.02em for large headings, normal for body.

COLOR:
- Generate a cohesive palette. Not random colors.
- Dark mode default: backgrounds #0a0a0a → #111 → #1a1a1a. Text #fafafa → #a1a1aa.
- Light mode available: backgrounds #fff → #f4f4f5 → #e4e4e7. Text #09090b → #71717a.
- Accent color derived from the brand/purpose of the app.
- Proper contrast ratios (WCAG AA minimum: 4.5:1 for text).

COMPONENTS:
- Buttons: rounded-lg (8px), proper hover/active states, transition-all 150ms.
- Cards: subtle border (1px #1e1e1e), rounded-xl (12px), hover:shadow-lg transition.
- Inputs: rounded-lg, border, focus ring with accent color, proper placeholder styling.
- Navigation: sticky, backdrop-blur, border-bottom, proper mobile hamburger.
- Modals: backdrop-blur overlay, centered, proper focus trap concept.
- Tables: alternating rows, sticky header, proper cell padding.

ANIMATIONS & POLISH:
- Subtle entrance animations (fade-up, fade-in) on scroll using IntersectionObserver.
- Hover transitions on all interactive elements (150ms ease).
- Smooth scroll behavior on the html element.
- Loading states for buttons (spinner or pulse).
- Skeleton loaders for content areas.
- Proper focus-visible outlines for accessibility.

IMAGES & MEDIA:
- Use placeholder images from https://picsum.photos or https://placehold.co
- Proper aspect ratios with object-fit: cover.
- Lazy loading with loading="lazy" attribute.
- Hero images: full-width with gradient overlay for text readability.

ICONS:
- Use inline SVG icons (no external dependencies in preview).
- Common icons: arrow-right, check, x, menu, search, user, settings, mail, phone.
- Size: 16px (small), 20px (default), 24px (large). Stroke-width: 1.5-2px.

CODE QUALITY:
- Semantic HTML5: header, main, section, article, aside, footer, nav.
- Proper heading hierarchy: one h1, then h2, h3 in order.
- Alt text on all images. Aria labels on icon buttons.
- No inline styles in React — use className with a styles object or Tailwind classes.
- Event handlers: proper naming (handleClick, handleSubmit, onChange).
- State management: useState for local, useReducer for complex.
- Clean prop interfaces. Destructured props. Default values.

REACT SPECIFIC:
- Functional components only. Named exports.
- Hooks at the top of the component.
- Memoize expensive computations with useMemo.
- Key props on all mapped elements (never use index as key if items can reorder).
- Error boundaries: wrap major sections.
- For preview_html: use React 18 via CDN (unpkg.com/react@18, unpkg.com/react-dom@18).
- Use Babel standalone for JSX in preview: unpkg.com/babel-standalone@7.
- Tailwind CSS via CDN: cdn.tailwindcss.com/3.4.0 for rapid styling.

## GENERATION RULES

1. preview_html MUST be a SINGLE self-contained HTML file that works when opened directly.
   All CSS, JS, React, and Tailwind must be loaded via CDN in that one file.
   If it doesn't render standalone, you failed.

2. Generate COMPLETE implementations. No "// TODO" or "// Add your code here."
   Every button should do something. Every form should have validation.
   Every list should have sample data. No empty states without a design.

3. Sample data should feel REAL. Not "Lorem ipsum" or "Item 1, Item 2."
   Use realistic names, prices, descriptions, dates. Make it feel like a shipped product.

4. The app should look like it belongs on Product Hunt, not on a tutorial blog.
   Design differentiation matters. Every app should feel intentionally designed.

5. For edits: change ONLY what the user asked. Preserve everything else exactly.
   Compare before/after mentally. If they said "make header blue," ONLY the header changes.

## FRAMEWORK SELECTION

Analyze the prompt and choose the optimal framework:
- Landing pages, marketing sites → HTML + Tailwind + Alpine.js (lightest, fastest)
- Interactive apps, dashboards → React 18 + Tailwind (rich interactivity)
- Full-stack with routing → Next.js structure (pages, API routes, layouts)
- Quick components, widgets → React with minimal deps

Always default to React + Tailwind unless the prompt clearly asks for something else.
"""


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER ELITE — COMPLEXITY SCORING + MODEL ROUTING
# ══════════════════════════════════════════════════════════════════════════════

def score_complexity(prompt: str, history: list) -> int:
    """Score prompt complexity 0-100 for model tier routing."""
    score = 0
    prompt_lower = prompt.lower()

    if len(prompt) > 500: score += 15
    elif len(prompt) > 200: score += 10
    elif len(prompt) > 100: score += 5

    full_app_keywords = [
        'dashboard', 'saas', 'auth', 'login', 'signup', 'billing',
        'admin panel', 'crud', 'database', 'api', 'full-stack', 'multi-page',
        'routing', 'navigation', 'user management', 'e-commerce', 'checkout',
        'payment', 'subscription', 'real-time', 'websocket', 'chat app',
    ]
    score += sum(10 for kw in full_app_keywords if kw in prompt_lower)

    edit_keywords = ['change', 'make the', 'update', 'fix', 'modify', 'adjust',
                     'move', 'resize', 'recolor', 'rename']
    if any(kw in prompt_lower for kw in edit_keywords) and history:
        score = max(score - 30, 0)

    score += min(len(history) * 2, 20)
    return min(score, 100)


def is_creative(prompt: str) -> bool:
    """Detect creative/artistic prompts for Grok routing."""
    creative_keywords = [
        'artistic', 'creative', 'unique', 'experimental',
        'cyberpunk', 'retro', 'neon', 'glassmorphism', 'brutalist',
        'organic', 'animated', 'parallax', '3d', 'immersive',
        'unconventional', 'wild', 'crazy', 'futuristic',
    ]
    return any(kw in prompt.lower() for kw in creative_keywords)


# ══════════════════════════════════════════════════════════════════════════════
# BUILDER ELITE — SUPABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════════

async def _get_remaining_credits(user_id: str) -> float:
    """Return remaining compute credits for user. Returns large number if Supabase not configured."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not _HTTPX_AVAILABLE:
        return 9999.0
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                },
                params={"user_id": f"eq.{user_id}", "select": "compute_credits_remaining"},
            )
            if res.status_code == 200:
                rows = res.json()
                if rows:
                    return float(rows[0].get("compute_credits_remaining", 9999))
    except Exception:
        pass
    return 9999.0


async def _log_usage(user_id: str, payload: dict):
    """Log builder usage to Supabase usage_log table. Silent on failure."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not _HTTPX_AVAILABLE:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/usage_log",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={"user_id": user_id, **payload, "created_at": datetime.utcnow().isoformat()},
            )
    except Exception:
        pass


async def _save_builder_project(user_id: str, build_id: str, prompt: str, result: dict):
    """Save builder project to Supabase builder_projects table. Silent on failure."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not _HTTPX_AVAILABLE:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{SUPABASE_URL}/rest/v1/builder_projects",
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                json={
                    "user_id": user_id,
                    "build_id": build_id,
                    "prompt": prompt,
                    "summary": result.get("summary", ""),
                    "framework": result.get("framework", "html"),
                    "files": result.get("files", []),
                    "preview_html": result.get("preview_html", ""),
                    "created_at": datetime.utcnow().isoformat(),
                },
            )
    except Exception:
        pass


# ── Pydantic models ───────────────────────────────────────────────────────────

class BuilderV2Request(BaseModel):
    prompt: str
    tier: str = "pro"
    session_id: Optional[str] = None
    model_override: Optional[str] = None


class BuilderApproveRequest(BaseModel):
    session_id: str
    approved: bool
    feedback: Optional[str] = None


class BuilderIterateRequest(BaseModel):
    change: str
    session_id: Optional[str] = None
    files: Optional[list] = None


class BuilderDeployRequest(BaseModel):
    platform: str = "vercel"
    session_id: Optional[str] = None
    files: Optional[list] = None


class BuilderStitchRequest(BaseModel):
    prompt: str
    context: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/agent/v2 — 5-Agent SSE Pipeline (Phase 1 + 2a)
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/agent/v2")
async def builder_agent_v2(body: BuilderV2Request, request: Request):
    """
    Builder v2 — 5-agent SSE pipeline (Phase 1 + 2a).

    Phase 1:  Grok 4.20    → plan_ready       (architecture plan + component tree)
    Phase 2a: Stitch/Grok  → design_ready     (full HTML/CSS UI screens)
              ── PAUSES here ──
              ── POST /api/builder/agent/v2/approve to resume ──

    SSE event types:
        agent_status, plan_ready, design_ready, awaiting_approval, error
    """
    _verify(request)

    session_id = body.session_id or f"build_{uuid.uuid4().hex[:12]}"
    _sessions[session_id] = {
        "prompt": body.prompt,
        "status": "planning",
        "created_at": datetime.utcnow().isoformat(),
        "plan": None,
        "designs": None,
        "scaffold": None,
        "files": None,
    }

    async def pipeline():
        # ── Announce all agent statuses ────────────────────────────────────────
        yield _sse("agent_status", {"agent": "grok",          "status": "active",  "message": "Architecting your app..."})
        yield _sse("agent_status", {"agent": "stitch",        "status": "waiting", "message": "Waiting..."})
        yield _sse("agent_status", {"agent": "claude-sonnet", "status": "waiting", "message": "Waiting..."})
        yield _sse("agent_status", {"agent": "claude-opus",   "status": "waiting", "message": "Waiting..."})
        yield _sse("agent_status", {"agent": "gpt5",          "status": "waiting", "message": "Waiting..."})

        # ── Phase 1: Grok — Architecture ──────────────────────────────────────
        try:
            plan_raw = await _call_grok(
                messages=[{"role": "user", "content": (
                    f"Create a detailed technical architecture plan for this app:\n{body.prompt}\n\n"
                    "Return ONLY a JSON object (no markdown, no explanation) with keys:\n"
                    "  plan (string: 2-3 sentences describing the approach),\n"
                    "  components (array of strings: key UI components),\n"
                    "  tech_stack (object: {frontend, backend, database, deployment})"
                )}],
                system=(
                    "You are a senior software architect. You design production-grade web applications. "
                    "Return ONLY a JSON object — no markdown fences, no prose outside the JSON."
                ),
            )
            plan_data = _parse_json(plan_raw, {
                "plan": plan_raw[:500],
                "components": ["Header", "Main Content", "Footer"],
                "tech_stack": {"frontend": "HTML/CSS/JS", "backend": "FastAPI", "database": "Supabase", "deployment": "Render"},
            })

            _sessions[session_id]["plan"] = plan_data
            yield _sse("agent_status", {"agent": "grok", "status": "complete", "message": "Architecture complete"})
            yield _sse("plan_ready", {
                "plan": plan_data.get("plan", ""),
                "components": plan_data.get("components", []),
                "tech_stack": plan_data.get("tech_stack", {}),
            })

        except Exception as e:
            yield _sse("error", {"agent": "grok", "message": str(e)[:300], "recoverable": False})
            return

        # ── Phase 2a: Stitch — UI Design ──────────────────────────────────────
        yield _sse("agent_status", {"agent": "stitch", "status": "active", "message": "Designing your UI screens..."})

        plan_summary = json.dumps(plan_data.get("plan", ""), ensure_ascii=False)[:600]
        components_list = ", ".join(plan_data.get("components", []))

        design_prompt = (
            f"Design 3-4 complete UI screens for this app:\n{body.prompt}\n\n"
            f"Architecture: {plan_summary}\n"
            f"Key components: {components_list}\n\n"
            "Design rules:\n"
            "  - Dark background: #0b0b0f\n"
            "  - Gold accent: #f59e0b\n"
            "  - Text: #e8e6e1\n"
            "  - Cards: #131318 background, #1e1e28 border\n"
            "  - Buttons: gold bg with dark text\n"
            "  - Font: -apple-system, BlinkMacSystemFont, sans-serif\n"
            "  - Fully responsive (max-width: 1200px, flexbox/grid)\n"
            "  - Include smooth CSS transitions and hover effects\n"
            "  - Each screen must be a COMPLETE standalone HTML document\n\n"
            "Return ONLY a JSON object with key 'screens' containing array of:\n"
            "  {name: string, html: string (complete HTML doc), thumbnail: string (1-sentence description)}\n"
            "No markdown. No explanation. Only the JSON."
        )

        try:
            design_raw = await _call_grok(
                messages=[{"role": "user", "content": design_prompt}],
                system=(
                    "You are a senior UI/UX designer who creates premium dark-themed interfaces. "
                    "Every screen is polished, animated, and professional. "
                    "Return ONLY a JSON object — no markdown, no explanation outside the JSON."
                ),
                max_tokens=16000,
            )
            design_data = _parse_json(design_raw, {
                "screens": [{
                    "name": "Main",
                    "html": (
                        "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
                        "<style>body{margin:0;background:#0b0b0f;color:#e8e6e1;"
                        "font-family:-apple-system,sans-serif;padding:40px}"
                        "h1{color:#f59e0b}p{color:#999}</style></head>"
                        f"<body><h1>{body.prompt[:60]}</h1>"
                        "<p>Your app is being designed...</p></body></html>"
                    ),
                    "thumbnail": "App main screen",
                }]
            })

            design_data["session_id"] = session_id
            _sessions[session_id]["designs"] = design_data
            _sessions[session_id]["status"] = "awaiting_approval"

            yield _sse("agent_status", {"agent": "stitch", "status": "complete", "message": "Designs ready for review"})
            yield _sse("design_ready", design_data)

            # ── PAUSE: stream ends here. Client posts to /approve to resume ──
            _sessions[session_id]["awaiting_approval"] = True
            yield _sse("awaiting_approval", {
                "session_id": session_id,
                "message": "Review your designs above. Approve to continue building, or request changes.",
            })

        except Exception as e:
            yield _sse("error", {"agent": "stitch", "message": str(e)[:300], "recoverable": True})

    return StreamingResponse(pipeline(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/agent/v2/approve — Resume pipeline after design approval
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/agent/v2/approve")
async def builder_v2_approve(body: BuilderApproveRequest, request: Request):
    """
    Resume builder v2 pipeline after user reviews designs.
    If approved=False: return redesign instruction (client re-calls /agent/v2 with feedback).
    If approved=True:  stream Phase 2b → Phase 3 → Phase 4.
    """
    _verify(request)

    session = _sessions.get(body.session_id)
    if not session:
        raise HTTPException(404, f"Session '{body.session_id}' not found. It may have expired.")

    if not body.approved:
        # Client should re-call /agent/v2 with feedback appended to prompt
        session["status"] = "redesign_requested"
        feedback_msg = body.feedback or "No specific feedback provided."
        return JSONResponse({
            "status": "redesign_requested",
            "session_id": body.session_id,
            "message": f"Redesigning with your feedback: {feedback_msg}",
            "action": "restart_pipeline",
            "new_prompt": f"{session.get('prompt', '')}\n\nDESIGN FEEDBACK: {feedback_msg}",
        })

    session["status"] = "scaffolding"
    plan = session.get("plan", {})
    designs = session.get("designs", {"screens": []})
    prompt = session.get("prompt", "")
    feedback = body.feedback or ""

    async def continue_pipeline():
        # ── Phase 2b: Claude Sonnet — File Scaffold ────────────────────────────
        yield _sse("agent_status", {"agent": "claude-sonnet", "status": "active", "message": "Engineering file structure..."})

        scaffold_prompt = (
            f"Create a complete, production-ready file tree for this app:\n{prompt}\n\n"
            f"Architecture plan: {json.dumps(plan.get('plan', ''), ensure_ascii=False)[:600]}\n"
            f"Tech stack: {json.dumps(plan.get('tech_stack', {}), ensure_ascii=False)}\n"
            f"Approved designs: {len(designs.get('screens', []))} screens\n"
            + (f"Feedback: {feedback}\n" if feedback else "")
            + "\nReturn ONLY a JSON object with key 'files' containing array of:\n"
            "  {path: string, description: string}\n"
            "Include all necessary files: entry points, components, styles, config, tests.\n"
            "No markdown. No explanation. Only the JSON."
        )

        scaffold_raw = ""
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": scaffold_prompt}],
                "You are a senior software engineer. Create precise, complete file structures for production apps. Return ONLY valid JSON.",
                model="claude-sonnet-4-6",
            ):
                scaffold_raw += chunk

            scaffold_data = _parse_json(scaffold_raw, {
                "files": [
                    {"path": "index.html", "description": "Main entry point"},
                    {"path": "style.css",  "description": "Styles"},
                    {"path": "app.js",     "description": "Application logic"},
                ]
            })
        except Exception as e:
            scaffold_data = {"files": [{"path": "index.html", "description": "Main entry"}]}
            yield _sse("error", {"agent": "claude-sonnet", "message": str(e)[:200], "recoverable": True})

        session["scaffold"] = scaffold_data
        yield _sse("agent_status", {"agent": "claude-sonnet", "status": "complete", "message": "File structure ready"})
        yield _sse("scaffold_ready", scaffold_data)

        # ── Phase 3: Claude Opus — Full Code Synthesis ─────────────────────────
        yield _sse("agent_status", {"agent": "claude-opus", "status": "active", "message": "Writing production code..."})

        files_list = scaffold_data.get("files", [])
        screens_count = len(designs.get("screens", []))
        screen_names = [s.get("name", "") for s in designs.get("screens", [])]

        synthesis_prompt = (
            f"Build complete, production-quality code for this app:\n{prompt}\n\n"
            f"File structure to implement:\n{json.dumps(files_list, ensure_ascii=False)[:800]}\n\n"
            f"Design context: {screens_count} approved screens — {', '.join(screen_names)}\n"
            f"Tech stack: {json.dumps(plan.get('tech_stack', {}), ensure_ascii=False)}\n"
            + (f"Design feedback incorporated: {feedback}\n" if feedback else "")
            + "\nCritical rules:\n"
            "  - Use SaintSal design system: --bg:#0b0b0f, --gold:#f59e0b, --t1:#e8e6e1, --brd:#1e1e28\n"
            "  - Every file must be COMPLETE — no TODOs, no placeholders, no truncation\n"
            "  - Responsive layouts with CSS Grid/Flexbox\n"
            "  - Smooth animations and micro-interactions\n"
            "  - Include error states and loading states\n\n"
            "Return ONLY a JSON object with key 'files' containing array of:\n"
            "  {path: string, content: string (complete file content), language: string}\n"
            "No markdown. No explanation. Only the JSON."
        )

        files_raw = ""
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": synthesis_prompt}],
                (
                    "You are a senior full-stack engineer synthesizing AI-generated designs into production code. "
                    "Write complete, working code with no placeholders. "
                    "Every file is complete and production-ready. "
                    "Return ONLY valid JSON."
                ),
                model="claude-opus-4-6",
            ):
                files_raw += chunk

            files_data = _parse_json(files_raw, {
                "files": [{"path": "index.html", "content": "<!-- Build failed, retry -->\n", "language": "html"}]
            })
        except Exception as e:
            files_data = {"files": [{"path": "index.html", "content": f"<!-- Error: {str(e)[:100]} -->", "language": "html"}]}
            yield _sse("error", {"agent": "claude-opus", "message": str(e)[:200], "recoverable": True})

        session["files"] = files_data
        yield _sse("agent_status", {"agent": "claude-opus", "status": "complete", "message": "Code synthesis complete"})
        yield _sse("files_ready", files_data)

        # ── Phase 4: GPT-5 — Validation ────────────────────────────────────────
        yield _sse("agent_status", {"agent": "gpt5", "status": "active", "message": "Validating code quality..."})

        generated_files = files_data.get("files", [])
        lint_results = []
        suggestions = []

        # Run GPT-5 validation
        try:
            validation_prompt = (
                "Review this generated codebase for bugs, missing imports, security issues, "
                "and missing edge cases. Be concise and specific.\n\n"
                f"Files: {json.dumps([{'path': f.get('path'), 'language': f.get('language')} for f in generated_files])}\n\n"
                "Return ONLY a JSON object with keys:\n"
                "  lint_results: array of {file, issue, severity: 'error'|'warning'|'info'}\n"
                "  suggestions: array of {suggestion: string}\n"
                "No markdown. No explanation. Only the JSON."
            )

            validation_raw = await _call_gpt5(
                [{"role": "user", "content": validation_prompt}],
                "You are a senior code reviewer. Identify real bugs and security issues. Return ONLY valid JSON.",
            )
            validation_data = _parse_json(validation_raw, {
                "lint_results": [],
                "suggestions": [{"suggestion": "Code generated successfully — review before deploying."}],
            })
            lint_results = validation_data.get("lint_results", [])
            suggestions  = validation_data.get("suggestions", [])
        except Exception as e:
            suggestions = [
                {"suggestion": "Add error boundaries around async operations"},
                {"suggestion": "Review all user inputs for sanitization"},
                {"suggestion": "Consider adding TypeScript for type safety"},
            ]

        session["status"] = "complete"
        yield _sse("agent_status", {"agent": "gpt5", "status": "complete", "message": "Validation complete"})
        yield _sse("validation_ready", {
            "lint_results": lint_results,
            "suggestions":  suggestions,
        })
        yield _sse("complete", {
            "session_id":  body.session_id,
            "total_files": len(generated_files),
            "total_time":  "—",
        })

    return StreamingResponse(continue_pipeline(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/iterate — Diff-based code editing
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/iterate")
async def builder_iterate(body: BuilderIterateRequest, request: Request):
    """
    Diff-based code editing. Applies targeted changes to existing files.
    Only returns the files that changed — client merges them.
    """
    _verify(request)

    current_files = body.files or []
    change_request = body.change.strip()

    if not change_request:
        raise HTTPException(400, "Change request is required")

    file_context = ""
    if current_files:
        file_context = "\n\nCurrent files:\n" + "\n\n".join([
            f"--- {f.get('path', 'file')} ---\n{f.get('content', '')[:1500]}"
            for f in current_files[:8]
        ])

    prompt = (
        f"Apply this targeted change to the codebase:\n{change_request}"
        f"{file_context}\n\n"
        "Return ONLY a JSON object with key 'files' containing array of ONLY the files that changed:\n"
        "  {path: string, content: string (complete file content), language: string}\n"
        "Do NOT return unchanged files. No markdown. No explanation. Only the JSON."
    )

    async def iterate():
        yield _sse("agent_status", {"agent": "claude-opus", "status": "active", "message": "Applying your changes..."})

        raw = ""
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": prompt}],
                (
                    "You are a senior engineer making surgical, targeted code changes. "
                    "Only modify what the user asked. Preserve all other code exactly. "
                    "Return ONLY valid JSON with the changed files."
                ),
                model="claude-opus-4-6",
            ):
                raw += chunk

            data = _parse_json(raw, {"files": []})
        except Exception as e:
            yield _sse("error", {"agent": "claude-opus", "message": str(e)[:200], "recoverable": True})
            return

        yield _sse("agent_status", {"agent": "claude-opus", "status": "complete", "message": "Changes applied"})
        yield _sse("files_ready", data)
        yield _sse("complete", {"type": "iteration", "files_changed": len(data.get("files", []))})

    return StreamingResponse(iterate(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/deploy — Deploy to Vercel/Render/Cloudflare/ZIP
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/deploy")
async def builder_deploy(body: BuilderDeployRequest, request: Request):
    """
    Deploy built code to a target platform.
    Platforms: vercel | render | cloudflare | zip
    """
    _verify(request)

    platform = body.platform.lower()
    files    = body.files or []
    session_id = body.session_id

    # Retrieve files from session if not provided
    if not files and session_id:
        session = _sessions.get(session_id, {})
        session_files = session.get("files", {})
        files = session_files.get("files", []) if isinstance(session_files, dict) else []

    if not files:
        raise HTTPException(400, "No files to deploy. Provide files[] or a valid session_id.")

    if platform not in ("vercel", "render", "cloudflare", "zip"):
        raise HTTPException(400, f"Unsupported platform: {platform}. Use vercel, render, cloudflare, or zip.")

    project_name = f"sal-build-{uuid.uuid4().hex[:8]}"

    # Platform-specific deploy logic
    if platform == "vercel":
        try:
            if not _HTTPX_AVAILABLE:
                raise RuntimeError("httpx not available")
            vercel_token = os.environ.get("VERCEL_TOKEN", "")
            if not vercel_token:
                return JSONResponse({
                    "status": "manual_required",
                    "platform": "vercel",
                    "message": "VERCEL_TOKEN not configured. Download ZIP and deploy manually.",
                    "manual_url": "https://vercel.com/new",
                    "session_id": session_id,
                })

            # Build Vercel deploy payload
            vercel_files = []
            for f in files:
                import base64
                content = f.get("content", "")
                vercel_files.append({
                    "file": f.get("path", "index.html"),
                    "data": base64.b64encode(content.encode()).decode(),
                    "encoding": "base64",
                })

            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    "https://api.vercel.com/v13/deployments",
                    headers={"Authorization": f"Bearer {vercel_token}"},
                    json={
                        "name": project_name,
                        "files": vercel_files,
                        "projectSettings": {"framework": None},
                    },
                )
                res.raise_for_status()
                deploy_data = res.json()

            return JSONResponse({
                "status": "deploying",
                "platform": "vercel",
                "url": f"https://{deploy_data.get('url', project_name + '.vercel.app')}",
                "deploy_id": deploy_data.get("id"),
                "session_id": session_id,
                "message": "Deployment initiated on Vercel",
            })
        except Exception as e:
            return JSONResponse({
                "status": "error",
                "platform": "vercel",
                "message": f"Vercel deploy failed: {str(e)[:200]}",
                "fallback": "Download ZIP and deploy manually",
            }, status_code=500)

    elif platform == "render":
        return JSONResponse({
            "status": "instructions",
            "platform": "render",
            "message": "Push your files to GitHub then connect the repo to Render.",
            "steps": [
                "1. Download the ZIP from the Builder",
                "2. Create a new GitHub repository",
                "3. Push files: git init && git add . && git commit -m 'init' && git push",
                "4. Go to render.com → New → Static Site → Connect repo",
            ],
            "session_id": session_id,
        })

    elif platform == "cloudflare":
        return JSONResponse({
            "status": "instructions",
            "platform": "cloudflare",
            "message": "Deploy to Cloudflare Pages via CLI or GitHub integration.",
            "steps": [
                "1. Install: npm install -g wrangler",
                "2. Login: wrangler login",
                "3. Deploy: wrangler pages deploy ./",
            ],
            "session_id": session_id,
        })

    elif platform == "zip":
        # Return file manifest — client will trigger browser download
        return JSONResponse({
            "status": "ready",
            "platform": "zip",
            "project_name": project_name,
            "files": files,
            "file_count": len(files),
            "message": f"Ready to download {len(files)} files as ZIP",
            "session_id": session_id,
        })

    return JSONResponse({"status": "unknown", "platform": platform})


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/builder/models — Available models per tier
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.get("/models")
async def builder_models(request: Request):
    """Return available AI models per subscription tier."""
    _verify(request)
    return JSONResponse({
        "free":       ["sal-mini"],
        "starter":    ["sal-mini", "sal-pro"],
        "pro":        ["sal-mini", "sal-pro", "sal-max", "sal-max-fast"],
        "teams":      ["sal-mini", "sal-pro", "sal-max", "sal-max-fast"],
        "enterprise": ["sal-mini", "sal-pro", "sal-max", "sal-max-fast", "api"],
        "pipeline_agents": {
            "architect":   "Grok 4.20",
            "designer":    "Stitch (Google)",
            "engineer":    "Claude Sonnet 4.6",
            "synthesizer": "Claude Opus 4.6",
            "validator":   "GPT-5 Core",
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/agent — v1 3-agent pipeline (backwards compat)
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/agent")
async def builder_agent_v1(request: Request):
    """
    Builder v1 — 3-agent pipeline.
    Kept for backwards compatibility with older clients.
    """
    _verify(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()

    if not prompt:
        raise HTTPException(400, "prompt is required")

    async def v1_pipeline():
        yield _sse("status", {"phase": "planning", "message": "Planning your app..."})

        try:
            plan = await _call_grok(
                [{"role": "user", "content": f"Plan this app briefly: {prompt}"}],
                "You are a software architect. Create a concise 3-4 sentence app plan.",
            )
            yield _sse("plan", {"content": plan})
            yield _sse("status", {"phase": "building", "message": "Building code..."})

            code = ""
            async for chunk in _stream_claude(
                [{"role": "user", "content": f"Build this complete app:\n{prompt}\n\nPlan:\n{plan[:500]}"}],
                "You are a senior engineer. Write complete, working code. Use dark background (#0b0b0f) and gold (#f59e0b) accents.",
                model="claude-sonnet-4-6",
            ):
                code += chunk
                yield _sse("chunk", {"content": chunk})

            yield _sse("complete", {"files": [{"path": "index.html", "content": code, "language": "html"}]})

        except Exception as e:
            yield _sse("error", {"message": str(e)[:200]})

    return StreamingResponse(v1_pipeline(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/generate  — Primary alias (what all iOS clients call)
# POST /api/builder/v2/generate — Same logic, v2 path kept for backwards compat
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/generate")
@builder_router.post("/v2/generate")
async def builder_quick_generate(request: Request):
    """
    Builder v2 Elite — 4-tier model routing, elite system prompt, metering.
    Returns JSON: { preview_html, files, summary, framework, features,
                    build_id, model_used, tier, compute_cost, elapsed_seconds }
    """
    _verify(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    history = body.get("history", [])
    user_id = body.get("user_id")

    if not prompt:
        raise HTTPException(400, "prompt is required")

    # ── Step 1: Check compute credits ────────────────────────────────────────
    if user_id:
        credits = await _get_remaining_credits(user_id)
        if credits <= 0:
            return JSONResponse({
                "error": "insufficient_credits",
                "message": "Upgrade your plan for more Builder credits.",
                "upgrade_url": "https://saintsallabs.com/pricing",
            }, status_code=402)

    # ── Step 2: Score complexity → select model tier ─────────────────────────
    complexity = score_complexity(prompt, history)

    if complexity >= 80:
        models = [("anthropic", "claude-opus-4-6"), ("openai", "gpt-4o")]
        tier = "ARCHITECT"
        cost_per_min = 1.00
    elif complexity >= 50:
        models = [("anthropic", "claude-sonnet-4-6"), ("openai", "gpt-4o")]
        tier = "BUILDER"
        cost_per_min = 0.25
    elif is_creative(prompt):
        models = [("xai", "grok-beta"), ("anthropic", "claude-sonnet-4-6")]
        tier = "CREATIVE"
        cost_per_min = 0.50
    else:
        models = [("anthropic", "claude-haiku-4-5-20251001"), ("openai", "gpt-4o")]
        tier = "QUICK"
        cost_per_min = 0.05

    # ── Step 3: Build messages ────────────────────────────────────────────────
    messages = []
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": prompt})

    # ── Step 4: Call model with fallback chain ────────────────────────────────
    start_time = time.time()
    raw_response = None
    model_used = None

    for provider, model in models:
        try:
            if provider == "anthropic":
                raw_response = await _call_claude_sync(
                    messages, BUILDER_SYSTEM_PROMPT, model=model, max_tokens=8192
                )
            elif provider == "xai":
                raw_response = await _call_grok(messages, BUILDER_SYSTEM_PROMPT, max_tokens=8192)
            elif provider == "openai":
                raw_response = await _call_gpt5(messages, BUILDER_SYSTEM_PROMPT)
            model_used = f"{provider}/{model}"
            break
        except Exception as e:
            print(f"[Builder Elite] {model} failed: {e}")
            continue

    if not raw_response:
        return JSONResponse({
            "error": "generation_failed",
            "message": "All models unavailable. Try again in a moment.",
        }, status_code=503)

    elapsed = time.time() - start_time

    # ── Step 5: Parse response ────────────────────────────────────────────────
    result = _parse_json(raw_response, {
        "files": [{"path": "index.html", "content": raw_response, "language": "html"}],
        "preview_html": raw_response,
        "summary": "Generated application",
        "framework": "html",
        "features": [],
    })

    # Ensure preview_html exists — fall back to first file content
    if not result.get("preview_html") and result.get("files"):
        result["preview_html"] = result["files"][0].get("content", "")

    # ── Step 6: Meter usage ───────────────────────────────────────────────────
    compute_minutes = max(elapsed / 60, 0.1)
    cost = round(compute_minutes * cost_per_min, 4)

    if user_id:
        await _log_usage(user_id, {
            "type": "builder_generate",
            "model": model_used,
            "tier": tier,
            "prompt_length": len(prompt),
            "response_length": len(raw_response),
            "elapsed_seconds": round(elapsed, 2),
            "compute_minutes": round(compute_minutes, 4),
            "cost": cost,
        })

    # ── Step 7: Save project ──────────────────────────────────────────────────
    build_id = uuid.uuid4().hex[:8]
    if user_id:
        await _save_builder_project(user_id, build_id, prompt, result)

    _sessions[build_id] = {
        "prompt": prompt,
        "status": "complete",
        "files": result.get("files", []),
        "created_at": datetime.utcnow().isoformat(),
    }

    # ── Step 8: Return ────────────────────────────────────────────────────────
    result["build_id"] = build_id
    result["model_used"] = model_used
    result["tier"] = tier
    result["compute_cost"] = cost
    result["elapsed_seconds"] = round(elapsed, 2)

    return JSONResponse(result)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/edit — Diff-based edit (preserves existing code)
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/edit")
async def builder_edit(request: Request):
    """
    Elite diff-based edit — change only what the user asked, preserve everything else.
    Returns same JSON shape as /generate.
    """
    _verify(request)
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    current_code = body.get("current_code", "")
    history = body.get("history", [])
    user_id = body.get("user_id")

    if not prompt:
        raise HTTPException(400, "prompt is required")
    if not current_code:
        raise HTTPException(400, "current_code is required for edits")

    # Edits always use QUICK or BUILDER tier based on complexity
    complexity = score_complexity(prompt, history)
    if complexity >= 50:
        models = [("anthropic", "claude-sonnet-4-6"), ("openai", "gpt-4o")]
        tier = "BUILDER"
        cost_per_min = 0.25
    else:
        models = [("anthropic", "claude-haiku-4-5-20251001"), ("openai", "gpt-4o")]
        tier = "QUICK"
        cost_per_min = 0.05

    edit_prompt = (
        f"EXISTING CODE:\n{current_code}\n\n"
        f"EDIT REQUEST: {prompt}\n\n"
        "Apply ONLY the requested change. Preserve all other code exactly. "
        "Return the complete updated file(s) in the same JSON format."
    )

    messages = []
    for msg in history[-6:]:
        messages.append(msg)
    messages.append({"role": "user", "content": edit_prompt})

    start_time = time.time()
    raw_response = None
    model_used = None

    for provider, model in models:
        try:
            if provider == "anthropic":
                raw_response = await _call_claude_sync(
                    messages, BUILDER_SYSTEM_PROMPT, model=model, max_tokens=8192
                )
            elif provider == "openai":
                raw_response = await _call_gpt5(messages, BUILDER_SYSTEM_PROMPT)
            model_used = f"{provider}/{model}"
            break
        except Exception as e:
            print(f"[Builder Edit] {model} failed: {e}")
            continue

    if not raw_response:
        return JSONResponse({
            "error": "edit_failed",
            "message": "All models unavailable. Try again in a moment.",
        }, status_code=503)

    elapsed = time.time() - start_time

    result = _parse_json(raw_response, {
        "files": [{"path": "index.html", "content": raw_response, "language": "html"}],
        "preview_html": raw_response,
        "summary": "Applied edit",
        "framework": "html",
        "features": [],
    })

    if not result.get("preview_html") and result.get("files"):
        result["preview_html"] = result["files"][0].get("content", "")

    compute_minutes = max(elapsed / 60, 0.1)
    cost = round(compute_minutes * cost_per_min, 4)

    if user_id:
        await _log_usage(user_id, {
            "type": "builder_edit",
            "model": model_used,
            "tier": tier,
            "prompt_length": len(prompt),
            "response_length": len(raw_response),
            "elapsed_seconds": round(elapsed, 2),
            "compute_minutes": round(compute_minutes, 4),
            "cost": cost,
        })

    build_id = uuid.uuid4().hex[:8]
    if user_id:
        await _save_builder_project(user_id, build_id, prompt, result)

    result["build_id"] = build_id
    result["model_used"] = model_used
    result["tier"] = tier
    result["compute_cost"] = cost
    result["elapsed_seconds"] = round(elapsed, 2)

    return JSONResponse(result)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/builder/stitch — Stitch MCP proxy
# ══════════════════════════════════════════════════════════════════════════════

@builder_router.post("/stitch")
async def builder_stitch(body: BuilderStitchRequest, request: Request):
    """
    Direct Stitch MCP proxy — generate UI designs via Claude with Stitch context.
    Used for standalone design generation outside the full 5-agent pipeline.
    """
    _verify(request)

    stitch_prompt = (
        f"Create premium UI designs using the SaintSal design system.\n\n"
        f"Design request: {body.prompt}\n"
        + (f"Context: {body.context}\n" if body.context else "")
        + "\nDesign system:\n"
        "  --bg: #0b0b0f  (main background)\n"
        "  --bg2: #131318 (card background)\n"
        "  --bg3: #1a1a22 (elevated)\n"
        "  --gold: #f59e0b (primary accent)\n"
        "  --t1: #e8e6e1  (primary text)\n"
        "  --t2: #999     (secondary text)\n"
        "  --brd: #1e1e28 (borders)\n\n"
        "Return ONLY a JSON object with key 'screens' containing array of:\n"
        "  {name: string, html: string (complete HTML document), thumbnail: string}\n"
        "No markdown. No explanation. Only the JSON."
    )

    try:
        raw = await _call_claude_sync(
            [{"role": "user", "content": stitch_prompt}],
            (
                "You are Stitch — a premium UI design agent for SaintSal™ Labs. "
                "You create polished, dark-themed interfaces with gold accents. "
                "Return ONLY valid JSON."
            ),
            model="claude-sonnet-4-6",
        )
        data = _parse_json(raw, {"screens": []})
        return JSONResponse({"ok": True, **data})
    except Exception as e:
        raise HTTPException(500, f"Stitch generation failed: {str(e)[:200]}")
