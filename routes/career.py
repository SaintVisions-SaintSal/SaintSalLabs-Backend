"""
SaintSal™ Labs — Career + Business Intelligence Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)

FastAPI router for all career and business intelligence endpoints.
Mount in server.py: app.include_router(career_router, prefix="")
"""

import os
import json
import uuid
import asyncio
from typing import Optional, AsyncIterator

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse
import httpx

career_router = APIRouter()

# ── Constants ─────────────────────────────────────────────────────────────────

SAL_GATEWAY_KEY = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
EXA_API_KEY = os.environ.get("EXA_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_HEADERS = lambda key: {
    "x-api-key": key,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

TIER_RANK = {"free": 0, "starter": 1, "pro": 2, "teams": 3, "enterprise": 4}

BIZPLAN_SECTIONS = [
    "executive_summary",
    "market_analysis",
    "competitive_landscape",
    "product_service",
    "business_model",
    "go_to_market",
    "financial_projections",
    "team",
    "funding_ask",
]

BIZPLAN_SECTION_LABELS = {
    "executive_summary": "Executive Summary",
    "market_analysis": "Market Analysis",
    "competitive_landscape": "Competitive Landscape",
    "product_service": "Product & Service",
    "business_model": "Business Model",
    "go_to_market": "Go-to-Market Strategy",
    "financial_projections": "Financial Projections",
    "team": "Team & Advisors",
    "funding_ask": "Funding Ask",
}

RESUME_SECTIONS = ["summary", "experience", "education", "skills"]

# ── Auth ──────────────────────────────────────────────────────────────────────

def verify_sal_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY_KEY:
        raise HTTPException(403, "Invalid gateway key")
    return True


async def get_user_tier(user_id: str) -> str:
    """Returns tier string for user. Defaults to 'free' on any failure."""
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY or not user_id:
        return "free"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(
                f"{SUPABASE_URL}/rest/v1/profiles",
                params={"id": f"eq.{user_id}", "select": "plan_tier"},
                headers={
                    "apikey": SUPABASE_SERVICE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                },
            )
            if r.status_code == 200:
                data = r.json()
                if data:
                    return data[0].get("plan_tier", "free")
    except Exception:
        pass
    return "free"


# ── Helpers ───────────────────────────────────────────────────────────────────

def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


def _extract_source(url: str) -> str:
    domains = {
        "linkedin.com": "LinkedIn", "indeed.com": "Indeed", "glassdoor.com": "Glassdoor",
        "lever.co": "Lever", "greenhouse.io": "Greenhouse", "workday.com": "Workday",
        "ziprecruiter.com": "ZipRecruiter", "dice.com": "Dice", "monster.com": "Monster",
        "wellfound.com": "Wellfound", "angel.co": "AngelList",
    }
    for domain, name in domains.items():
        if domain in url:
            return name
    return "Job Board"


def _extract_company_from_title(title: str, url: str) -> str:
    """Best-effort company extraction from job listing title/url."""
    for sep in [" at ", " - ", " | ", " @ "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                return parts[-1].strip()[:60]
    # try url domain
    try:
        domain = url.split("/")[2].replace("www.", "").split(".")[0].capitalize()
        return domain
    except Exception:
        return "Company"


async def _claude_complete(prompt: str, system: str = "", max_tokens: int = 1500) -> str:
    """Single-shot Claude completion. Returns text or raises."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY not configured")
    messages = [{"role": "user", "content": prompt}]
    payload = {"model": CLAUDE_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=45) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers=CLAUDE_HEADERS(ANTHROPIC_API_KEY),
            json=payload,
        )
        r.raise_for_status()
        return r.json().get("content", [{}])[0].get("text", "")


async def _exa_search(query: str, num_results: int = 5, domains: list = None) -> list:
    """Exa neural search. Returns list of result dicts."""
    if not EXA_API_KEY:
        return []
    payload = {
        "query": query,
        "numResults": num_results,
        "type": "neural",
        "useAutoprompt": True,
        "contents": {"text": {"maxCharacters": 600}},
    }
    if domains:
        payload["includeDomains"] = domains
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_API_KEY, "Content-Type": "application/json"},
                json=payload,
            )
            if r.status_code == 200:
                return r.json().get("results", [])
    except Exception as e:
        print(f"[Exa] Search error: {e}")
    return []


async def _tavily_search(query: str, max_results: int = 5, depth: str = "basic") -> list:
    """Tavily search. Returns list of result dicts."""
    if not TAVILY_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_API_KEY, "query": query, "search_depth": depth, "max_results": max_results},
            )
            if r.status_code == 200:
                return r.json().get("results", [])
    except Exception as e:
        print(f"[Tavily] Search error: {e}")
    return []


async def _stream_claude_section(
    section_key: str,
    section_label: str,
    prompt: str,
    system: str,
    max_tokens: int = 1200,
) -> AsyncIterator[str]:
    """Stream a single section via Claude SSE-like chunking."""
    yield sse_event({"type": "section_start", "section": section_key, "label": section_label})

    if not ANTHROPIC_API_KEY:
        yield sse_event({"type": "chunk", "section": section_key, "content": "AI not configured."})
        yield sse_event({"type": "section_done", "section": section_key})
        return

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={**CLAUDE_HEADERS(ANTHROPIC_API_KEY), "anthropic-version": "2023-06-01"},
                json={
                    "model": CLAUDE_MODEL,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": True,
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        raw = line[5:].strip()
                        if raw == "[DONE]":
                            break
                        try:
                            evt = json.loads(raw)
                            if evt.get("type") == "content_block_delta":
                                delta = evt.get("delta", {}).get("text", "")
                                if delta:
                                    yield sse_event({"type": "chunk", "section": section_key, "content": delta})
                        except Exception:
                            pass
    except Exception as e:
        print(f"[Career] Section stream error ({section_key}): {e}")
        yield sse_event({"type": "chunk", "section": section_key, "content": f"Error generating {section_label}."})

    yield sse_event({"type": "section_done", "section": section_key})


# ══════════════════════════════════════════════════════════════════════════════
# GET /api/career/jobs — Job Search (Exa + Tavily)
# ══════════════════════════════════════════════════════════════════════════════

@career_router.get("/api/career/jobs")
async def career_jobs(
    query: str,
    location: str = "",
    job_type: str = "",
    remote: bool = False,
    page: int = 1,
    _: bool = Depends(verify_sal_key),
):
    """Search jobs via Exa semantic search + Tavily fallback."""
    search_query = f"{query} job opening"
    if location:
        search_query += f" {location}"
    if job_type:
        search_query += f" {job_type}"
    if remote:
        search_query += " remote"

    job_domains = [
        "linkedin.com", "indeed.com", "glassdoor.com", "lever.co",
        "greenhouse.io", "workday.com", "ziprecruiter.com", "dice.com",
        "wellfound.com", "angel.co", "monster.com",
    ]

    # Try Exa first
    exa_results = await _exa_search(search_query, num_results=12, domains=job_domains)
    if exa_results:
        jobs = []
        for item in exa_results:
            title = item.get("title", "").replace(" - LinkedIn", "").replace(" | Indeed", "").strip()
            snippet = item.get("text", "")
            salary_range = ""
            # crude salary extraction
            import re
            sal_match = re.search(r"\$[\d,]+\s*(?:–|-|to)\s*\$[\d,]+", snippet or "")
            if sal_match:
                salary_range = sal_match.group(0)
            jobs.append({
                "id": str(uuid.uuid4())[:8],
                "title": title,
                "company": _extract_company_from_title(title, item.get("url", "")),
                "location": location or "See listing",
                "salary_range": salary_range,
                "url": item.get("url", ""),
                "description": (snippet[:400] + "...") if len(snippet) > 400 else snippet,
                "published": item.get("publishedDate", ""),
                "source": _extract_source(item.get("url", "")),
                "remote": remote or "remote" in (snippet or "").lower(),
            })
        return {"jobs": jobs, "total": len(jobs), "query": query, "provider": "Exa"}

    # Tavily fallback
    tavily_results = await _tavily_search(
        f"{query} job openings {location}", max_results=8, depth="basic"
    )
    if tavily_results:
        jobs = []
        for res in tavily_results:
            title = res.get("title", "")
            snippet = res.get("content", "")[:400]
            jobs.append({
                "id": str(uuid.uuid4())[:8],
                "title": title,
                "company": _extract_company_from_title(title, res.get("url", "")),
                "location": location or "See listing",
                "salary_range": "",
                "url": res.get("url", ""),
                "description": snippet,
                "published": "",
                "source": _extract_source(res.get("url", "")),
                "remote": remote,
            })
        return {"jobs": jobs, "total": len(jobs), "query": query, "provider": "Tavily"}

    return {"jobs": [], "total": 0, "query": query, "error": "No search provider available"}


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/resume — Resume Generation (SSE stream)
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/resume")
async def career_resume(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate a complete resume by streaming each section sequentially."""
    body = await request.json()
    name = body.get("name", "")
    email = body.get("email", "")
    phone = body.get("phone", "")
    location = body.get("location", "")
    title = body.get("title", "")
    raw_summary = body.get("summary", "")
    experience = body.get("experience", [])  # list of {company, title, dates, bullets}
    education = body.get("education", "")
    skills = body.get("skills", [])  # list or comma string

    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]

    exp_text = "\n".join(
        [f"- {e.get('company','')} | {e.get('title','')} | {e.get('dates','')} | {e.get('bullets','')}"
         for e in (experience if isinstance(experience, list) else [])]
    ) or raw_summary

    system = (
        "You are an executive resume writer at Goldman Sachs / McKinsey caliber. "
        "Write achievement-oriented, metric-rich content. ATS-optimized. "
        "Respond in plain text (no markdown headers). Be concise and powerful."
    )

    async def stream():
        # Section: summary
        prompt = (
            f"Write a powerful 3-4 sentence professional summary for:\n"
            f"Name: {name}, Title: {title}, Location: {location}\n"
            f"Background: {raw_summary or exp_text[:300]}\n"
            f"Make it achievement-oriented, specific, and compelling. Plain text only."
        )
        async for chunk in _stream_claude_section("summary", "Professional Summary", prompt, system, 400):
            yield chunk

        # Section: experience
        if experience or exp_text:
            prompt = (
                f"Rewrite these work experience bullets to be achievement-oriented with metrics:\n{exp_text}\n"
                f"For {name}, a {title}. Format: Company | Title | Dates, then 3-4 strong bullets per role. Plain text."
            )
            async for chunk in _stream_claude_section("experience", "Work Experience", prompt, system, 800):
                yield chunk

        # Section: education
        if education:
            prompt = (
                f"Format this education section professionally:\n{education}\n"
                f"Add relevant coursework or honors if implied. Plain text, clean format."
            )
            async for chunk in _stream_claude_section("education", "Education", prompt, system, 300):
                yield chunk

        # Section: skills
        if skills:
            skills_str = ", ".join(skills)
            prompt = (
                f"Organize these skills into 3-4 categories (Technical, Leadership, Domain Expertise, Tools): {skills_str}\n"
                f"Format as: Category: skill1, skill2, skill3. One line per category. Plain text."
            )
            async for chunk in _stream_claude_section("skills", "Skills", prompt, system, 300):
                yield chunk

        yield sse_event({"type": "done", "name": name, "email": email, "phone": phone, "location": location})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/enhance — AI Resume Enhancement
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/enhance")
async def career_enhance(request: Request, _: bool = Depends(verify_sal_key)):
    """Enhance pasted resume text with AI. Returns JSON with improvements."""
    body = await request.json()
    resume_text = body.get("resume_text", "")
    target_role = body.get("target_role", "")
    if not resume_text:
        return JSONResponse({"error": "resume_text required"}, status_code=400)

    prompt = f"""You are a top-tier executive resume writer (Goldman Sachs, McKinsey level).
Enhance this resume. Make bullets achievement-oriented with metrics.
Target Role (if any): {target_role}

Resume:
{resume_text[:3000]}

Return JSON:
{{
  "enhanced_summary": "powerful 3-sentence professional summary",
  "enhanced_bullets": {{"role_0": ["bullet1","bullet2","bullet3"]}},
  "ats_keywords": ["10 ATS-optimized keywords"],
  "skills_categorized": {{"Technical":[],"Leadership":[],"Domain":[]}},
  "cover_letter_opener": "compelling first paragraph",
  "score_improvement": {{"before": 62, "after": 91, "notes": "..."}}
}}
Return ONLY valid JSON, no markdown."""

    try:
        text = await _claude_complete(prompt, max_tokens=1500)
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        enhanced = json.loads(text)
        return {"status": "success", "enhanced": enhanced}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/coach — Career Coaching (SSE stream)
# ══════════════════════════════════════════════════════════════════════════════

CAREER_COACH_SYSTEM = """You are SAL Career Coach — an elite career strategist with the insight of a
top McKinsey partner, executive recruiter, and career psychologist combined.
You help professionals navigate promotions, salary negotiations, career pivots, and leadership development.
Be direct, tactical, and give specific scripts/frameworks, not generic advice.
When asked about salary: give real numbers by role/level/market.
When asked about promotions: give a 90-day action plan.
When asked to review a career path: give honest assessment + specific next move."""

@career_router.post("/api/career/coach")
async def career_coach(request: Request, _: bool = Depends(verify_sal_key)):
    """Career coaching chat — SSE streaming, multi-turn."""
    body = await request.json()
    message = body.get("message", "")
    messages = body.get("messages", [])  # Full conversation history
    context = body.get("context", {})  # {current_role, target_role, years_exp}

    if not message:
        return JSONResponse({"error": "message required"}, status_code=400)

    if not ANTHROPIC_API_KEY:
        return JSONResponse({"error": "AI not configured"}, status_code=500)

    system = CAREER_COACH_SYSTEM
    if context:
        system += f"\n\nUser context: Current role: {context.get('current_role','unknown')}, Target: {context.get('target_role','unknown')}, Experience: {context.get('years_exp','unknown')} years."

    # Build message list
    if messages:
        chat_messages = [{"role": m["role"], "content": m["content"]} for m in messages[-12:]]
    else:
        chat_messages = [{"role": "user", "content": message}]

    async def stream():
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    "https://api.anthropic.com/v1/messages",
                    headers=CLAUDE_HEADERS(ANTHROPIC_API_KEY),
                    json={
                        "model": CLAUDE_MODEL,
                        "max_tokens": 1200,
                        "system": system,
                        "messages": chat_messages,
                        "stream": True,
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data:"):
                            raw = line[5:].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                evt = json.loads(raw)
                                if evt.get("type") == "content_block_delta":
                                    delta = evt.get("delta", {}).get("text", "")
                                    if delta:
                                        yield sse_event({"type": "chunk", "content": delta})
                            except Exception:
                                pass
        except Exception as e:
            yield sse_event({"type": "error", "content": str(e)})
        yield sse_event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/interview — Interview Prep (SSE)
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/interview")
async def career_interview(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate targeted interview prep. Streams sections, also returns structured JSON."""
    body = await request.json()
    role = body.get("role", "")
    company = body.get("company", "")
    job_description = body.get("job_description", "")
    interview_type = body.get("interview_type", "behavioral")

    if not ANTHROPIC_API_KEY:
        return JSONResponse({"error": "AI not configured"}, status_code=500)

    system = "You are an elite interview coach. Give specific, detailed, tactical advice with exact scripts and examples."

    prompt = f"""Create a complete interview prep package.
Company: {company or "the target company"}
Role: {role or "the target role"}
Interview Type: {interview_type}
Job Description: {job_description[:800] if job_description else "N/A"}

Return JSON:
{{
  "likely_questions": [
    {{"question": "...", "why_they_ask": "...", "model_answer": "detailed STAR answer..."}}
  ],
  "star_examples": ["3 STAR method story starters tailored to the role"],
  "salary_range": {{"low": 0, "mid": 0, "high": 0, "currency": "USD", "note": "market context"}},
  "negotiation_script": "exact word-for-word script when they make an offer",
  "red_flags_to_watch": ["3 specific red flags for this type of role"],
  "day_of_checklist": ["8 specific prep items"],
  "company_questions_to_ask": ["4 smart questions that show strategic thinking"]
}}
Return ONLY valid JSON. Generate at least 6 likely_questions."""

    async def stream():
        yield sse_event({"type": "section_start", "section": "questions", "label": "Generating Interview Package"})
        try:
            text = await _claude_complete(prompt, system=system, max_tokens=2500)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            data = json.loads(text)
            yield sse_event({"type": "result", "data": data})
        except Exception as e:
            yield sse_event({"type": "error", "content": str(e)})
        yield sse_event({"type": "done"})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/cover-letter — Cover Letter Generation
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/cover-letter")
async def career_cover_letter(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate a tailored cover letter. style: direct|storytelling|technical"""
    body = await request.json()
    job_description = body.get("job_description", "")
    resume_text = body.get("resume_text", "")
    style = body.get("style", "direct")  # direct | storytelling | technical
    name = body.get("name", "")
    company = body.get("company", "")
    role = body.get("role", "")

    if not job_description:
        return JSONResponse({"error": "job_description required"}, status_code=400)

    style_instructions = {
        "direct": "Write in a direct, executive style. Lead with value proposition. No fluff. Results-first.",
        "storytelling": "Use a compelling narrative arc. Open with a specific achievement story that mirrors the job requirements.",
        "technical": "Lead with technical depth. Reference specific tech in the JD. Show you understand the exact stack and challenges.",
    }

    system = "You are a professional cover letter writer who gets interviews at FAANG and elite firms."
    prompt = f"""Write a tailored cover letter.
Job Description: {job_description[:1000]}
Applicant Resume Summary: {resume_text[:600] if resume_text else "N/A"}
Applicant Name: {name or "the applicant"}
Company: {company or "the company"}
Role: {role or "the role"}
Style: {style_instructions.get(style, style_instructions['direct'])}

Write the complete cover letter. Include:
- Strong opening hook
- 2-3 paragraphs matching experience to JD requirements (use specific metrics)
- Closing paragraph with clear call to action

Also return keyword matches as a JSON object at the END, delimited like this:
---JSON---
{{"cover_letter": "full letter text", "keywords_matched": ["keyword1","keyword2"], "word_count": 350}}
---END---"""

    try:
        text = await _claude_complete(prompt, system=system, max_tokens=1500)
        # Parse out the JSON block
        if "---JSON---" in text and "---END---" in text:
            letter_part = text.split("---JSON---")[0].strip()
            json_part = text.split("---JSON---")[1].split("---END---")[0].strip()
            try:
                result = json.loads(json_part)
                result["cover_letter"] = letter_part
            except Exception:
                result = {"cover_letter": letter_part, "keywords_matched": [], "word_count": len(letter_part.split())}
        else:
            result = {
                "cover_letter": text,
                "keywords_matched": [],
                "word_count": len(text.split()),
            }
        return {"status": "success", "result": result}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/swot — SWOT Analysis
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/swot")
async def career_swot(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate personal or business SWOT analysis."""
    body = await request.json()
    subject = body.get("subject", "")  # person name or business name
    context = body.get("context", "")  # role/bio/business description
    swot_type = body.get("type", "career")  # career | business

    if not subject and not context:
        return JSONResponse({"error": "subject or context required"}, status_code=400)

    prompt = f"""Perform a detailed {'career' if swot_type == 'career' else 'business'} SWOT analysis.
Subject: {subject}
Context: {context[:800]}

Return JSON:
{{
  "strengths": [{{"point": "...", "detail": "...", "leverage": "how to use this"}}],
  "weaknesses": [{{"point": "...", "detail": "...", "mitigation": "how to address"}}],
  "opportunities": [{{"point": "...", "detail": "...", "action": "concrete next step"}}],
  "threats": [{{"point": "...", "detail": "...", "defense": "how to protect"}}],
  "priority_actions": ["3 highest-impact actions in next 90 days"],
  "summary": "2-sentence strategic assessment"
}}
Include at least 4 items per quadrant. Return ONLY valid JSON."""

    try:
        text = await _claude_complete(prompt, max_tokens=2000)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return {"status": "success", "swot": json.loads(text)}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/bizplan — Business Plan (SSE, sequential sections)
# ══════════════════════════��═══════════════════════════════════════════════════

@career_router.post("/api/career/bizplan")
async def career_bizplan(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate business plan — streams 9 sections sequentially."""
    body = await request.json()
    business_name = body.get("business_name", "")
    description = body.get("description", "")
    target_market = body.get("target_market", "")
    stage = body.get("stage", "pre-revenue")

    if not description:
        return JSONResponse({"error": "description required"}, status_code=400)

    return await _run_bizplan_stream(business_name, description, target_market, stage)


async def _run_bizplan_stream(
    business_name: str, description: str, target_market: str, stage: str
) -> StreamingResponse:
    system = (
        "You are a Tier 1 VC-backed startup advisor and business plan writer. "
        "Write with McKinsey precision — specific, data-backed, actionable. "
        "Use real market data and realistic projections. "
        f"Business: {business_name or 'this business'}. Stage: {stage}."
    )

    section_prompts = {
        "executive_summary": f"Write the Executive Summary for '{business_name}'.\nDescription: {description}\nTarget Market: {target_market}\nStage: {stage}\nInclude: mission, problem, solution, traction/stage, and ask in 250-350 words.",
        "market_analysis": f"Write the Market Analysis section.\nBusiness: {business_name}\nDescription: {description}\nTarget Market: {target_market}\nInclude: TAM/SAM/SOM with estimates, market trends, customer segments, pain points. 400-500 words.",
        "competitive_landscape": f"Write the Competitive Landscape section.\nBusiness: {business_name}\nDescription: {description}\nInclude: 4-5 likely competitors, comparison table (features/price/positioning), our differentiation, moat. 350-400 words.",
        "product_service": f"Write the Product & Service section.\nBusiness: {business_name}\nDescription: {description}\nInclude: core features, tech stack if applicable, roadmap (3 phases), defensibility. 350-400 words.",
        "business_model": f"Write the Business Model section.\nBusiness: {business_name}\nDescription: {description}\nStage: {stage}\nInclude: revenue streams, pricing model, unit economics (LTV/CAC), margins, scalability. 300-400 words.",
        "go_to_market": f"Write the Go-to-Market Strategy.\nBusiness: {business_name}\nDescription: {description}\nTarget Market: {target_market}\nInclude: launch strategy, customer acquisition channels, partnerships, 90-day plan. 400-450 words.",
        "financial_projections": f"Write the Financial Projections section.\nBusiness: {business_name}\nDescription: {description}\nStage: {stage}\nInclude: Year 1-3 revenue projections, key assumptions, burn rate, break-even, milestones. 350-400 words.",
        "team": f"Write the Team & Advisors section.\nBusiness: {business_name}\nDescription: {description}\nInclude: ideal team structure for this type of business, key hires needed, advisory board strategy. 250-300 words.",
        "funding_ask": f"Write the Funding Ask section.\nBusiness: {business_name}\nDescription: {description}\nStage: {stage}\nInclude: amount to raise, use of funds breakdown, target investors, milestones this round enables, expected outcome. 300-350 words.",
    }

    async def stream():
        yield sse_event({"type": "start", "sections": BIZPLAN_SECTIONS, "business": business_name})
        for section_key in BIZPLAN_SECTIONS:
            label = BIZPLAN_SECTION_LABELS[section_key]
            prompt = section_prompts[section_key]
            async for chunk in _stream_claude_section(section_key, label, prompt, system, max_tokens=600):
                yield chunk
            await asyncio.sleep(0.1)
        yield sse_event({"type": "complete", "sections_count": len(BIZPLAN_SECTIONS)})

    return StreamingResponse(stream(), media_type="text/event-stream")


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/linkedin-optimize — LinkedIn Profile Optimizer
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/linkedin-optimize")
async def career_linkedin_optimize(request: Request, _: bool = Depends(verify_sal_key)):
    """Optimize LinkedIn profile. Returns JSON with rewrites and score."""
    body = await request.json()
    profile_text = body.get("profile_text", "")
    target_role = body.get("target_role", "")

    if not profile_text:
        return JSONResponse({"error": "profile_text required"}, status_code=400)

    prompt = f"""You are a LinkedIn optimization expert who has helped 10,000+ professionals get recruited.
Optimize this LinkedIn profile:
{profile_text[:2500]}

Target Role (if any): {target_role}

Return JSON:
{{
  "headline": "optimized LinkedIn headline (120 chars max, keyword-rich)",
  "summary": "optimized About section (1800 chars max, first-person, compelling, keyword-rich)",
  "experience_rewrites": [
    {{"original_role": "...", "company": "...", "rewritten_bullets": ["bullet1","bullet2","bullet3"]}}
  ],
  "skills_to_add": ["10 high-value skills missing from profile"],
  "score_before": 58,
  "score_after": 91,
  "score_notes": "what drove the score improvement",
  "quick_wins": ["3 fastest changes that will get more recruiter views"]
}}
Return ONLY valid JSON."""

    try:
        text = await _claude_complete(prompt, max_tokens=2000)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return {"status": "success", "result": json.loads(text)}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/salary-negotiate — Salary Negotiation Coach
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/salary-negotiate")
async def career_salary_negotiate(request: Request, _: bool = Depends(verify_sal_key)):
    """Salary negotiation coach with real market data from Exa."""
    body = await request.json()
    offer_details = body.get("offer_details", "")
    role = body.get("role", "")
    location = body.get("location", "")
    years_exp = body.get("years_exp", "")
    current_salary = body.get("current_salary", "")

    if not role:
        return JSONResponse({"error": "role required"}, status_code=400)

    # Fetch real salary data
    salary_data = []
    search_query = f"{role} salary {location} {years_exp} years experience 2024 2025"
    exa_results = await _exa_search(search_query, num_results=4, domains=[
        "levels.fyi", "glassdoor.com", "payscale.com", "salary.com", "linkedin.com", "bls.gov"
    ])
    for r in exa_results:
        if r.get("text"):
            salary_data.append(r["text"][:400])

    if not salary_data:
        tavily_results = await _tavily_search(search_query, max_results=4)
        for r in tavily_results:
            if r.get("content"):
                salary_data.append(r["content"][:400])

    market_context = "\n".join(salary_data[:3]) if salary_data else "Market data not available — use industry benchmarks."

    prompt = f"""You are a salary negotiation expert. Create a complete negotiation strategy.

Role: {role}
Location: {location or "US"}
Years Experience: {years_exp or "not specified"}
Current Offer: {offer_details or "not specified"}
Current Salary: {current_salary or "not specified"}

Real Market Data Found:
{market_context[:1500]}

Return JSON:
{{
  "market_range": {{"low": 0, "mid": 0, "high": 0, "currency": "USD", "percentile_25": 0, "percentile_75": 0}},
  "market_sources": ["source1", "source2"],
  "recommended_ask": 0,
  "counter_offer_script": "exact word-for-word script to say when negotiating",
  "email_template": "complete professional email to negotiate in writing",
  "backup_positions": [
    {{"position": "first counter", "amount": 0, "rationale": "..."}},
    {{"position": "minimum acceptable", "amount": 0, "rationale": "..."}}
  ],
  "non_salary_levers": ["signing bonus","equity","remote work","extra PTO","title change"],
  "tactics": ["3 specific negotiation tactics for this situation"],
  "red_lines": ["what to walk away from"]
}}
Use REAL numbers based on the market data. Return ONLY valid JSON."""

    try:
        text = await _claude_complete(prompt, max_tokens=2000)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return {"status": "success", "result": json.loads(text)}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/career/network-map — Network Mapping Strategy
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/career/network-map")
async def career_network_map(request: Request, _: bool = Depends(verify_sal_key)):
    """Generate network mapping strategy. Apollo + Claude."""
    body = await request.json()
    goal = body.get("goal", "")  # e.g., "break into VC" or "get promoted to VP"
    current_role = body.get("current_role", "")
    target_company = body.get("target_company", "")
    target_role = body.get("target_role", "")

    if not goal:
        return JSONResponse({"error": "goal required"}, status_code=400)

    prompt = f"""You are an elite executive networking strategist.
Goal: {goal}
Current Role: {current_role or "not specified"}
Target Company: {target_company or "not specified"}
Target Role: {target_role or "not specified"}

Create a complete network mapping and outreach strategy:

Return JSON:
{{
  "network_map": {{
    "tier_1": [{{"type": "relationship_type", "value": "high", "action": "specific outreach"}}],
    "tier_2": [{{"type": "relationship_type", "value": "medium", "action": "specific outreach"}}],
    "tier_3": [{{"type": "relationship_type", "value": "low", "action": "specific outreach"}}]
  }},
  "key_profiles_to_find": ["type of person to target and where to find them"],
  "linkedin_search_strings": ["exact LinkedIn search query 1", "exact LinkedIn search query 2"],
  "outreach_templates": [
    {{"context": "cold outreach to target company", "subject": "...", "message": "..."}},
    {{"context": "alumni connection", "subject": "...", "message": "..."}},
    {{"context": "mutual connection intro", "subject": "...", "message": "..."}}
  ],
  "30_60_90_plan": {{
    "days_1_30": ["5 specific networking actions"],
    "days_31_60": ["5 specific networking actions"],
    "days_61_90": ["5 specific networking actions"]
  }},
  "platforms": ["LinkedIn","Slack communities","Discord","Twitter/X","Meetups","Conferences"],
  "success_metrics": ["how to track networking ROI"]
}}
Return ONLY valid JSON."""

    try:
        text = await _claude_complete(prompt, max_tokens=2000)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return {"status": "success", "result": json.loads(text)}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/business/plan — Full Business Plan AI (SSE stream by section)
# ══════════════════════════════════════════════════════════════════════════���═══

@career_router.post("/api/business/plan")
async def business_plan(request: Request, _: bool = Depends(verify_sal_key)):
    """Full business plan — SSE stream 9 sections. Same engine as /api/career/bizplan."""
    body = await request.json()
    business_name = body.get("business_name", "")
    description = body.get("description", "")
    target_market = body.get("target_market", "")
    stage = body.get("stage", "pre-revenue")
    user_id = body.get("user_id", "")

    if not description:
        return JSONResponse({"error": "description required"}, status_code=400)

    return await _run_bizplan_stream(business_name, description, target_market, stage)


# ══════════════════════════════════════════════════════════════════════════════
# POST /api/business/patent-search — Patent/IP Intelligence (Teams+)
# ══════════════════════════════════════════════════════════════════════════════

@career_router.post("/api/business/patent-search")
async def business_patent_search(request: Request, _: bool = Depends(verify_sal_key)):
    """Patent and IP intelligence search. Teams+ tier required."""
    body = await request.json()
    query = body.get("query", "")
    invention_description = body.get("invention_description", "")
    user_id = body.get("user_id", "")

    # Tier check
    tier = await get_user_tier(user_id)
    if TIER_RANK.get(tier, 0) < TIER_RANK.get("teams", 3):
        return JSONResponse(
            {"error": "Patent search requires Teams+ subscription", "upgrade_required": True},
            status_code=403,
        )

    if not query and not invention_description:
        return JSONResponse({"error": "query or invention_description required"}, status_code=400)

    search_term = query or invention_description[:200]

    # Search USPTO + Google Patents via Exa
    patent_results = await _exa_search(
        f"patent {search_term} USPTO",
        num_results=8,
        domains=["patents.google.com", "patents.justia.com", "worldwide.espacenet.com", "patentsview.org"],
    )

    # Also search via Tavily
    tavily_results = await _tavily_search(
        f"site:patents.google.com OR site:patents.justia.com {search_term}",
        max_results=5,
    )

    # AI analysis
    context_text = "\n\n".join([r.get("text", "")[:500] for r in patent_results[:5]] +
                                [r.get("content", "")[:400] for r in tavily_results[:3]])

    analysis_prompt = f"""Analyze this patent landscape for IP intelligence.
Search: {search_term}
Invention: {invention_description[:600] if invention_description else "N/A"}

Patent Results Found:
{context_text[:3000]}

Return JSON:
{{
  "patent_landscape": "2-3 sentence overview of the patent landscape",
  "key_patents": [
    {{"title": "...", "patent_number": "...", "assignee": "...", "filed": "...", "relevance": "...", "url": "..."}}
  ],
  "white_spaces": ["areas where no patents exist — opportunities"],
  "risks": ["potential infringement risks"],
  "recommendations": ["IP strategy recommendations"],
  "prior_art_concerns": "assessment of prior art for the described invention",
  "patentability_score": {{"score": 0, "out_of": 10, "rationale": "..."}}
}}
Return ONLY valid JSON."""

    try:
        analysis_text = await _claude_complete(analysis_prompt, max_tokens=2000)
        analysis_text = analysis_text.strip()
        if analysis_text.startswith("```"):
            analysis_text = analysis_text.split("```")[1]
            if analysis_text.startswith("json"):
                analysis_text = analysis_text[4:]

        result = json.loads(analysis_text)

        # Append raw search results
        result["raw_results"] = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("text", "")[:300],
                "source": "Exa",
            }
            for r in patent_results[:6]
        ]

        return {"status": "success", "result": result}
    except Exception as e:
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)
