"""
SaintSal™ Labs — Creative Studio + Social Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)
Owner: Ryan "Cap" Capatosto

FastAPI router for all creative, content generation, image generation,
social posting, content calendar, and brand profile endpoints.
"""

import os
import json
import uuid
import asyncio
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

# ── Router ────────────────────────────────────────────────────────────────────

router = APIRouter()

# ── Environment ───────────────────────────────────────────────────────────────

SAL_GATEWAY_KEY    = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
XAI_API_KEY        = os.environ.get("XAI_API_KEY", "")
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN", "")
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
GHL_PRIVATE_TOKEN  = os.environ.get("GHL_PRIVATE_TOKEN", "")
GHL_LOCATION_ID    = os.environ.get("GHL_LOCATION_ID", "oRA8vL3OSiCPjpwmEC0V")
SUPABASE_URL       = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

# ── Constants ─────────────────────────────────────────────────────────────────

BRAND_VOICE = (
    "Direct, Goldman-level credibility. We don't chase trends. We build infrastructure. "
    "SaintSal™ Labs is a patented AI platform (HACP™ US #10,290,222) serving 175+ countries. "
    "Tone: confident, professional, never hype, always substance."
)

CONTENT_PILLARS = {
    0: "Monday — Commercial lending: fast funding $5K–$100M. Focus on speed, trust, scale.",
    1: "Tuesday — AI automation: SaintSal HACP™ technology. Focus on innovation, ROI.",
    2: "Wednesday — Investment fund: 9–12% fixed returns. Focus on stability, credibility.",
    3: "Thursday — Patent technology: HACP #10,290,222. Focus on differentiation, IP.",
    4: "Friday — Success stories: client wins, transformations. Focus on proof, results.",
    5: "Saturday — Community & culture: platform updates, team, vision.",
    6: "Sunday — Thought leadership: industry insight, market intelligence.",
}

PLATFORM_RULES = {
    "linkedin": {
        "guide": "Professional, authoritative tone. 150–200 words. 5 hashtags at end. Use line breaks for readability. Start with a bold hook. No fluff.",
        "char_limit": 3000,
        "hashtag_count": 5,
        "optimal_length": 175,
    },
    "twitter": {
        "guide": "Under 240 chars. 2–3 hashtags woven in. Hook-first — the first 5 words must compel. Punchy, direct, no filler.",
        "char_limit": 280,
        "hashtag_count": 3,
        "optimal_length": 220,
    },
    "instagram": {
        "guide": "Visual-first storytelling. 100–150 words. 20–30 hashtags in a second block after the main copy. Emoji-friendly but not overdone.",
        "char_limit": 2200,
        "hashtag_count": 25,
        "optimal_length": 125,
    },
    "facebook": {
        "guide": "Conversational, warm. 100–150 words. End with a question to drive comments. 3–5 hashtags. No hard sells.",
        "char_limit": 63206,
        "hashtag_count": 4,
        "optimal_length": 125,
    },
    "tiktok": {
        "guide": "Casual, trend-aware. Under 150 chars for caption. 5–7 hashtags. Hook in first word. Keep it punchy.",
        "char_limit": 2200,
        "hashtag_count": 6,
        "optimal_length": 100,
    },
    "youtube": {
        "guide": "SEO title (60 chars max, keywords front-loaded) + full description (300–500 words). Include timestamps structure, keywords, and call to action.",
        "char_limit": 5000,
        "hashtag_count": 10,
        "optimal_length": 400,
    },
}

CONTENT_TYPE_GUIDES = {
    "caption":   "A short, punchy social caption optimized for engagement.",
    "blog post": "A full-length blog article with H2 subheadings, intro, body, and CTA. 800–1200 words.",
    "email":     "A marketing email with subject line, preview text, body copy, and CTA. Conversational, benefit-driven.",
    "ad copy":   "High-conversion ad copy with headline, subheadline, body (30–50 words), and clear CTA.",
    "carousel":  "A 5–7 slide carousel script. Each slide: 1 headline + 1–2 lines of copy. Slide 1 = hook, last slide = CTA.",
    "thread":    "A Twitter/X thread. Tweet 1 = hook/thesis. Tweets 2–8 = one insight each. Final tweet = CTA + summary.",
}

ASPECT_RATIO_SIZES = {
    "square":    "1024x1024",
    "portrait":  "1024x1792",
    "landscape": "1792x1024",
    "wide":      "1792x1024",
}

# ── Auth Helper ───────────────────────────────────────────────────────────────

def verify_sal_key(request: Request) -> bool:
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY_KEY:
        raise HTTPException(403, "Invalid gateway key")
    return True


def sse_event(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"


# ── AI Helpers ────────────────────────────────────────────────────────────────

async def stream_claude(messages: list, system: str, model: str = "claude-sonnet-4-6") -> AsyncIterator[str]:
    """Stream from Anthropic Claude with GPT-5 fallback."""
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
        return
    except Exception as e:
        err = str(e)[:120]

    # Fallback: GPT-5
    if OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream(
                    "POST",
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": "gpt-4o",
                        "stream": True,
                        "max_tokens": 8192,
                        "messages": [{"role": "system", "content": system}, *messages],
                    },
                ) as resp:
                    async for line in resp.aiter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk["choices"][0]["delta"].get("content", "")
                                if delta:
                                    yield delta
                            except Exception:
                                pass
            return
        except Exception:
            pass

    yield f"\n[Generation error — check API keys]"


async def call_claude(messages: list, system: str, model: str = "claude-sonnet-4-6") -> str:
    """Non-streaming Claude call, collects full text."""
    result = ""
    async for chunk in stream_claude(messages, system, model):
        result += chunk
    return result


async def generate_for_platforms(
    prompt: str,
    platforms: list,
    content_type: str,
    brand_voice: str,
    seo_mode: bool,
) -> dict:
    """Generate content for each platform concurrently."""

    async def gen_one(platform: str) -> tuple[str, str]:
        rules = PLATFORM_RULES.get(platform, PLATFORM_RULES["linkedin"])
        type_guide = CONTENT_TYPE_GUIDES.get(content_type, CONTENT_TYPE_GUIDES["caption"])
        system = f"""You are a world-class social media content strategist for SaintSal™ Labs.

BRAND VOICE: {brand_voice}

PLATFORM: {platform.upper()}
PLATFORM RULES: {rules['guide']}

CONTENT TYPE: {content_type.upper()}
{type_guide}

{'SEO MODE: Optimize for search — front-load keywords, include search-friendly phrases, natural density.' if seo_mode else ''}

CRITICAL:
- Deliver ONLY the finished content. No preamble like "Here is your post:".
- Respect platform character limits and style strictly.
- Every word earns its place."""

        content = await call_claude(
            [{"role": "user", "content": f"Write {content_type} content for this topic:\n\n{prompt}"}],
            system,
        )
        return platform, content.strip()

    tasks = [gen_one(p) for p in platforms]
    results = await asyncio.gather(*tasks)
    return dict(results)


# ── ENDPOINT 1: Content Generation ───────────────────────────────────────────

@router.post("/api/creative/generate")
async def creative_generate(request: Request):
    """
    Multi-platform content generation.

    Body:
      prompt       str   — What the content is about
      platforms    list  — ["linkedin", "twitter", "instagram", "facebook", "tiktok", "youtube"]
      type         str   — caption | blog post | email | ad copy | carousel | thread
      brand_voice  str   — professional | casual | technical
      seo_mode     bool  — Enable SEO optimization
      pillar       str   — Optional content pillar override
    """
    verify_sal_key(request)
    body = await request.json()

    prompt        = body.get("prompt", "").strip()
    platforms     = body.get("platforms", ["linkedin"])
    content_type  = body.get("type", "caption")
    voice_preset  = body.get("brand_voice", "professional")
    seo_mode      = body.get("seo_mode", False)
    pillar        = body.get("pillar", "")

    if not prompt:
        raise HTTPException(400, "prompt is required")

    # Build brand voice from preset
    voice_map = {
        "professional": BRAND_VOICE,
        "casual": "Approachable and relatable, but still credible. Conversational, never corporate. Use contractions, real language.",
        "technical": "Precise, data-driven, expert. Reference patent technology, AI infrastructure, specific metrics. For a technical audience.",
    }
    brand_voice = voice_map.get(voice_preset, BRAND_VOICE)
    if pillar:
        brand_voice += f"\n\nCONTENT PILLAR: {pillar}"

    # Add today's pillar context if not overridden
    if not pillar:
        day_of_week = datetime.utcnow().weekday()
        pillar_context = CONTENT_PILLARS.get(day_of_week, "")
        if pillar_context:
            brand_voice += f"\n\nTODAY'S CONTENT PILLAR: {pillar_context}"

    platform_versions = await generate_for_platforms(
        prompt, platforms, content_type, brand_voice, seo_mode
    )

    # Build char count metadata per platform
    char_counts = {}
    for p, content in platform_versions.items():
        limit = PLATFORM_RULES.get(p, {}).get("char_limit", 3000)
        optimal = PLATFORM_RULES.get(p, {}).get("optimal_length", 200)
        count = len(content)
        status = "good" if count <= optimal * 1.2 else ("close" if count <= limit * 0.9 else "over")
        char_counts[p] = {"count": count, "limit": limit, "optimal": optimal, "status": status}

    return {
        "platform_versions": platform_versions,
        "char_counts": char_counts,
        "type": content_type,
        "platforms": platforms,
        "seo_mode": seo_mode,
        "generated_at": datetime.utcnow().isoformat(),
    }


# ── ENDPOINT 2: Image Generation ─────────────────────────────────────────────

@router.post("/api/creative/image")
async def creative_image(request: Request):
    """
    Image generation with model routing.

    Routing logic:
      social / photorealistic → DALL-E 3 (OpenAI)
      ui / marketing          → Stitch (Google) → fallback DALL-E 3
      artistic                → Replicate SDXL → fallback DALL-E 3

    Body:
      prompt        str — Image description
      style         str — photorealistic | artistic | ui_marketing | product
      aspect_ratio  str — square | portrait | landscape | wide
    """
    verify_sal_key(request)
    body = await request.json()

    prompt       = body.get("prompt", "").strip()
    style        = body.get("style", "photorealistic")
    aspect_ratio = body.get("aspect_ratio", "square")

    if not prompt:
        raise HTTPException(400, "prompt is required")

    size = ASPECT_RATIO_SIZES.get(aspect_ratio, "1024x1024")

    # Enhance prompt based on style
    style_enhancements = {
        "photorealistic":  "ultra-realistic, photographic, 8K, professional lighting, sharp focus",
        "artistic":        "digital art, painterly, vibrant, artistic, detailed illustration",
        "ui_marketing":    "clean UI mockup, modern design, minimal, professional marketing visual, white background",
        "product":         "product photography, clean background, professional lighting, commercial quality",
    }
    enhanced_prompt = f"{prompt}. Style: {style_enhancements.get(style, '')}"

    # ── Route: UI/Marketing → Stitch (Gemini Imagen) ─────────────────────────
    if style == "ui_marketing" and GEMINI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={GEMINI_API_KEY}",
                    json={
                        "instances": [{"prompt": enhanced_prompt}],
                        "parameters": {"sampleCount": 1},
                    },
                )
                data = res.json()
                if "predictions" in data and data["predictions"]:
                    b64 = data["predictions"][0].get("bytesBase64Encoded", "")
                    if b64:
                        return {
                            "image_url": f"data:image/png;base64,{b64}",
                            "model_used": "google_imagen3",
                            "prompt_used": enhanced_prompt,
                            "style": style,
                            "aspect_ratio": aspect_ratio,
                        }
        except Exception:
            pass  # Fall through to DALL-E

    # ── Route: Artistic → Replicate SDXL ─────────────────────────────────────
    if style == "artistic" and REPLICATE_API_TOKEN:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                # Start prediction
                create_res = await client.post(
                    "https://api.replicate.com/v1/models/stability-ai/sdxl/predictions",
                    headers={
                        "Authorization": f"Token {REPLICATE_API_TOKEN}",
                        "Prefer": "wait",
                    },
                    json={
                        "input": {
                            "prompt": enhanced_prompt,
                            "width": int(size.split("x")[0]),
                            "height": int(size.split("x")[1]),
                            "num_outputs": 1,
                            "num_inference_steps": 30,
                        }
                    },
                )
                pred = create_res.json()
                pred_id = pred.get("id")

                if pred_id:
                    # Poll for result
                    for _ in range(30):
                        await asyncio.sleep(2)
                        poll = await client.get(
                            f"https://api.replicate.com/v1/predictions/{pred_id}",
                            headers={"Authorization": f"Token {REPLICATE_API_TOKEN}"},
                        )
                        poll_data = poll.json()
                        if poll_data.get("status") == "succeeded":
                            output = poll_data.get("output", [])
                            if output:
                                return {
                                    "image_url": output[0],
                                    "model_used": "replicate_sdxl",
                                    "prompt_used": enhanced_prompt,
                                    "style": style,
                                    "aspect_ratio": aspect_ratio,
                                }
                            break
                        elif poll_data.get("status") in ("failed", "canceled"):
                            break
        except Exception:
            pass  # Fall through to DALL-E

    # ── Default / Fallback: DALL-E 3 ─────────────────────────────────────────
    if OPENAI_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                res = await client.post(
                    "https://api.openai.com/v1/images/generations",
                    headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                    json={
                        "model": "dall-e-3",
                        "prompt": enhanced_prompt,
                        "n": 1,
                        "size": size,
                        "quality": "hd" if style == "photorealistic" else "standard",
                        "style": "natural" if style == "photorealistic" else "vivid",
                    },
                )
                data = res.json()
                if "data" in data and data["data"]:
                    image_url = data["data"][0]["url"]
                    revised_prompt = data["data"][0].get("revised_prompt", enhanced_prompt)
                    return {
                        "image_url": image_url,
                        "model_used": "dalle3",
                        "prompt_used": revised_prompt,
                        "style": style,
                        "aspect_ratio": aspect_ratio,
                    }
                if "error" in data:
                    return {"error": data["error"]["message"], "image_url": "", "model_used": "dalle3"}
        except Exception as e:
            return {"error": str(e)[:200], "image_url": "", "model_used": "dalle3"}

    return {
        "error": "Image generation not configured. Set OPENAI_API_KEY or REPLICATE_API_TOKEN.",
        "image_url": "",
        "model_used": "unavailable",
    }


# ── ENDPOINT 3: Social Post ───────────────────────────────────────────────────

@router.post("/api/creative/social/post")
async def creative_social_post(request: Request):
    """
    Post to social platforms via GHL Social Studio.

    Body:
      content       str  — Post text content
      platforms     list — Platforms to post to
      schedule_time str  — ISO datetime, or null for immediate
      image_url     str  — Optional image attachment URL
    """
    verify_sal_key(request)
    body = await request.json()

    content       = body.get("content", "").strip()
    platforms     = body.get("platforms", [])
    schedule_time = body.get("schedule_time")
    image_url     = body.get("image_url", "")

    if not content:
        raise HTTPException(400, "content is required")
    if not platforms:
        raise HTTPException(400, "at least one platform required")

    if not GHL_PRIVATE_TOKEN:
        return {
            "error": "GHL not configured — set GHL_PRIVATE_TOKEN",
            "post_ids": {},
            "platforms": platforms,
        }

    post_ids = {}
    errors = {}

    async with httpx.AsyncClient(timeout=30) as client:
        for platform in platforms:
            payload: dict = {
                "content": content,
                "platform": platform.lower(),
                "locationId": GHL_LOCATION_ID,
            }
            if schedule_time:
                payload["scheduledAt"] = schedule_time
            if image_url:
                payload["mediaUrl"] = image_url

            try:
                res = await client.post(
                    f"https://rest.gohighlevel.com/v1/social-media-posting/{GHL_LOCATION_ID}/posts",
                    headers={
                        "Authorization": f"Bearer {GHL_PRIVATE_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                data = res.json()
                if res.status_code < 300:
                    post_ids[platform] = data.get("id", "posted")
                else:
                    errors[platform] = data.get("message", f"HTTP {res.status_code}")
            except Exception as e:
                errors[platform] = str(e)[:120]

    return {
        "post_ids": post_ids,
        "errors": errors,
        "scheduled": bool(schedule_time),
        "scheduled_time": schedule_time,
        "platforms_posted": list(post_ids.keys()),
        "platforms_failed": list(errors.keys()),
    }


# ── ENDPOINT 4: Content Calendar ─────────────────────────────────────────────

@router.post("/api/creative/calendar")
async def creative_calendar(request: Request):
    """
    Generate AI content calendar (SSE streaming).

    Body:
      business_description  str  — What the business does
      goals                 str  — Optional marketing goals
      duration              int  — 30 | 60 | 90 days
      platforms             list — Target platforms
      industry              str  — Optional industry context
    """
    verify_sal_key(request)
    body = await request.json()

    business_description = body.get("business_description", "SaintSal™ Labs AI platform")
    goals                = body.get("goals", "")
    duration             = int(body.get("duration", 30))
    platforms            = body.get("platforms", ["linkedin", "twitter", "instagram"])
    industry             = body.get("industry", "AI technology / financial services")

    duration = min(max(duration, 7), 90)

    start_date = datetime.utcnow()

    system = f"""You are a senior social media strategist building an enterprise content calendar.

BUSINESS: {business_description}
INDUSTRY: {industry}
PLATFORMS: {', '.join(platforms)}
DURATION: {duration} days starting {start_date.strftime('%Y-%m-%d')}
{f'GOALS: {goals}' if goals else ''}

CONTENT PILLARS (rotate through these):
{chr(10).join(f'- {v}' for v in CONTENT_PILLARS.values())}

BRAND VOICE: {BRAND_VOICE}

OUTPUT FORMAT — Return ONLY valid JSON with this exact structure:
{{
  "calendar_id": "uuid",
  "business": "...",
  "duration": {duration},
  "platforms": [...],
  "days": [
    {{
      "date": "YYYY-MM-DD",
      "day_of_week": "Monday",
      "pillar": "pillar name",
      "posts": [
        {{
          "platform": "linkedin",
          "topic": "Brief topic description",
          "type": "caption|blog post|carousel|thread|email|ad copy",
          "time": "HH:MM",
          "hashtags": ["tag1", "tag2"],
          "notes": "Key angle or hook"
        }}
      ]
    }}
  ]
}}

Generate all {duration} days. Each day gets 1–3 posts depending on platform mix.
Optimal posting times per platform: LinkedIn 9am/12pm, Twitter 9am/3pm/6pm, Instagram 11am/7pm, Facebook 1pm/7pm, TikTok 7am/9pm."""

    user_msg = f"Create a {duration}-day content calendar for: {business_description}"
    if goals:
        user_msg += f"\n\nMarketing goals: {goals}"

    def generate():
        import asyncio

        async def _stream():
            full_content = ""
            yield sse_event("status", {"message": f"Generating {duration}-day content calendar...", "duration": duration})

            async for chunk in stream_claude(
                [{"role": "user", "content": user_msg}],
                system,
                model="claude-sonnet-4-6",
            ):
                full_content += chunk
                yield sse_event("chunk", {"content": chunk})

            # Parse and validate JSON
            try:
                # Strip markdown fences if present
                clean = full_content.strip()
                if clean.startswith("```"):
                    clean = clean.split("```")[1]
                    if clean.startswith("json"):
                        clean = clean[4:]
                    clean = clean.strip()
                    if clean.endswith("```"):
                        clean = clean[:-3].strip()

                calendar_data = json.loads(clean)
                if "calendar_id" not in calendar_data:
                    calendar_data["calendar_id"] = str(uuid.uuid4())
                yield sse_event("complete", {"calendar": calendar_data})
            except Exception:
                yield sse_event("complete", {
                    "calendar": {
                        "calendar_id": str(uuid.uuid4()),
                        "business": business_description,
                        "duration": duration,
                        "platforms": platforms,
                        "days": [],
                        "raw": full_content,
                    }
                })

        loop = asyncio.new_event_loop()
        try:
            async def run():
                async for event in _stream():
                    yield event

            # Use synchronous wrapper
            gen = run()
            loop.run_until_complete(_collect_and_yield(gen))
        finally:
            loop.close()

    # Use a proper async generator approach
    async def async_generate():
        full_content = ""
        yield sse_event("status", {"message": f"Generating {duration}-day content calendar...", "duration": duration})

        async for chunk in stream_claude(
            [{"role": "user", "content": user_msg}],
            system,
            model="claude-sonnet-4-6",
        ):
            full_content += chunk
            yield sse_event("chunk", {"content": chunk})

        # Parse and validate JSON
        try:
            clean = full_content.strip()
            if clean.startswith("```"):
                parts = clean.split("```")
                if len(parts) >= 2:
                    clean = parts[1]
                    if clean.startswith("json"):
                        clean = clean[4:].strip()

            calendar_data = json.loads(clean)
            if "calendar_id" not in calendar_data:
                calendar_data["calendar_id"] = str(uuid.uuid4())
            yield sse_event("complete", {"calendar": calendar_data})
        except Exception:
            yield sse_event("complete", {
                "calendar": {
                    "calendar_id": str(uuid.uuid4()),
                    "business": business_description,
                    "duration": duration,
                    "platforms": platforms,
                    "days": [],
                    "raw": full_content[:5000],
                }
            })

    return StreamingResponse(async_generate(), media_type="text/event-stream")


# ── ENDPOINT 5: Batch Generate Week ──────────────────────────────────────────

@router.post("/api/creative/calendar/batch-generate")
async def creative_calendar_batch(request: Request):
    """
    Batch generate a full week of ready-to-post content.

    Body:
      calendar_id   str  — Calendar reference ID
      week_number   int  — Which week (1-indexed)
      days          list — [{date, platform, topic, type}] — the week's schedule
      brand_voice   str  — professional | casual | technical
    """
    verify_sal_key(request)
    body = await request.json()

    calendar_id = body.get("calendar_id", str(uuid.uuid4()))
    week_number = int(body.get("week_number", 1))
    days        = body.get("days", [])
    voice_preset = body.get("brand_voice", "professional")

    if not days:
        raise HTTPException(400, "days array required with post schedule")

    voice_map = {
        "professional": BRAND_VOICE,
        "casual": "Approachable, conversational, relatable. Real language, contractions ok.",
        "technical": "Precise, data-driven, expert-level. Specific metrics and technical details.",
    }
    brand_voice = voice_map.get(voice_preset, BRAND_VOICE)

    # Generate all posts for the week concurrently (max 7 days)
    async def gen_post(day_entry: dict) -> dict:
        platform = day_entry.get("platform", "linkedin")
        topic    = day_entry.get("topic", "SaintSal Labs update")
        post_type = day_entry.get("type", "caption")
        date_str = day_entry.get("date", "")

        rules = PLATFORM_RULES.get(platform, PLATFORM_RULES["linkedin"])
        type_guide = CONTENT_TYPE_GUIDES.get(post_type, CONTENT_TYPE_GUIDES["caption"])

        system = f"""You are a social media content strategist for SaintSal™ Labs.
BRAND VOICE: {brand_voice}
PLATFORM: {platform.upper()} — {rules['guide']}
CONTENT TYPE: {post_type} — {type_guide}

Return ONLY the finished post content. No preamble."""

        content = await call_claude(
            [{"role": "user", "content": f"Write a {post_type} for {platform} about: {topic}"}],
            system,
        )

        return {
            "date": date_str,
            "platform": platform,
            "topic": topic,
            "type": post_type,
            "content": content.strip(),
            "char_count": len(content.strip()),
            "char_limit": rules.get("char_limit", 3000),
            "status": "ready",
        }

    tasks = [gen_post(d) for d in days[:7]]  # Max 7 days per batch
    posts = await asyncio.gather(*tasks)

    return {
        "calendar_id": calendar_id,
        "week_number": week_number,
        "posts": list(posts),
        "count": len(posts),
        "generated_at": datetime.utcnow().isoformat(),
    }


# ── ENDPOINT 6: Brand Profile (Create/Save) ───────────────────────────────────

@router.post("/api/creative/brand-profile")
async def creative_brand_profile(request: Request):
    """
    Create or update a brand profile.

    Body:
      brand_name      str
      tagline         str
      description     str
      voice           str  — professional | casual | technical | bold
      industry        str
      target_audience str
      content_pillars list
      color_palette   list — hex codes
      competitors     list
      user_id         str  — Supabase user ID
    """
    verify_sal_key(request)
    body = await request.json()

    user_id    = body.get("user_id", "")
    brand_name = body.get("brand_name", "").strip()

    if not brand_name:
        raise HTTPException(400, "brand_name is required")

    profile_id = body.get("id", str(uuid.uuid4()))
    now = datetime.utcnow().isoformat()

    profile = {
        "id": profile_id,
        "user_id": user_id,
        "brand_name": brand_name,
        "tagline": body.get("tagline", ""),
        "description": body.get("description", ""),
        "voice": body.get("voice", "professional"),
        "industry": body.get("industry", ""),
        "target_audience": body.get("target_audience", ""),
        "content_pillars": body.get("content_pillars", []),
        "color_palette": body.get("color_palette", []),
        "competitors": body.get("competitors", []),
        "created_at": now,
        "updated_at": now,
    }

    # Save to Supabase if configured
    if SUPABASE_URL and SUPABASE_SERVICE_KEY and user_id:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.post(
                    f"{SUPABASE_URL}/rest/v1/brand_profiles",
                    headers={
                        "apikey": SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                        "Content-Type": "application/json",
                        "Prefer": "resolution=merge-duplicates",
                    },
                    json=profile,
                )
                if res.status_code >= 400:
                    # Table may not exist yet — return profile anyway
                    pass
        except Exception:
            pass

    # Generate AI-enhanced brand voice guide
    ai_voice_guide = ""
    if body.get("description"):
        try:
            ai_voice_guide = await call_claude(
                [{"role": "user", "content": f"Write a concise brand voice guide (3–4 bullet points) for: {brand_name}. Description: {body.get('description')}. Voice: {body.get('voice', 'professional')}. Industry: {body.get('industry', 'technology')}."}],
                "You are a brand strategist. Write crisp, actionable brand voice guidelines. Return bullet points only, no preamble.",
            )
        except Exception:
            pass

    return {
        "id": profile_id,
        "status": "created",
        "profile": profile,
        "ai_voice_guide": ai_voice_guide.strip(),
    }


# ── ENDPOINT 7: List Brand Profiles ──────────────────────────────────────────

@router.get("/api/creative/brand-profiles")
async def creative_brand_profiles(request: Request):
    """
    List all brand profiles for a user.
    Query params: user_id
    """
    verify_sal_key(request)
    user_id = request.query_params.get("user_id", "")

    if not user_id:
        return {"profiles": [], "count": 0}

    if SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(
                    f"{SUPABASE_URL}/rest/v1/brand_profiles",
                    params={"user_id": f"eq.{user_id}", "select": "*", "order": "created_at.desc"},
                    headers={
                        "apikey": SUPABASE_SERVICE_KEY,
                        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
                    },
                )
                if res.status_code == 200:
                    profiles = res.json()
                    return {"profiles": profiles, "count": len(profiles)}
        except Exception:
            pass

    return {"profiles": [], "count": 0, "note": "Supabase not configured or table not found"}


# ── ENDPOINT 8: Marketing Daily Content ──────────────────────────────────────

@router.post("/api/marketing/daily-content")
async def marketing_daily_content(request: Request):
    """
    Generate today's daily content package for GHL Social Studio.

    Body:
      topic         str  — Optional topic override
      platforms     list — Target platforms
      post_now      bool — If true, immediately post via GHL
    """
    verify_sal_key(request)
    body = await request.json()

    topic     = body.get("topic", "")
    platforms = body.get("platforms", ["linkedin", "twitter", "instagram"])
    post_now  = body.get("post_now", False)

    day_of_week = datetime.utcnow().weekday()
    pillar = CONTENT_PILLARS.get(day_of_week, "SaintSal™ Labs platform update")

    if not topic:
        topic = pillar

    platform_versions = await generate_for_platforms(
        prompt=topic,
        platforms=platforms,
        content_type="caption",
        brand_voice=BRAND_VOICE,
        seo_mode=False,
    )

    post_results = {}
    if post_now and GHL_PRIVATE_TOKEN:
        async with httpx.AsyncClient(timeout=30) as client:
            for platform, content in platform_versions.items():
                try:
                    res = await client.post(
                        f"https://rest.gohighlevel.com/v1/social-media-posting/{GHL_LOCATION_ID}/posts",
                        headers={
                            "Authorization": f"Bearer {GHL_PRIVATE_TOKEN}",
                            "Content-Type": "application/json",
                        },
                        json={"content": content, "platform": platform, "locationId": GHL_LOCATION_ID},
                    )
                    post_results[platform] = res.json().get("id", "posted") if res.status_code < 300 else f"error_{res.status_code}"
                except Exception as e:
                    post_results[platform] = f"error: {str(e)[:80]}"

    return {
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "day_of_week": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"][day_of_week],
        "pillar": pillar,
        "platform_versions": platform_versions,
        "posted": post_now,
        "post_results": post_results,
        "platforms": platforms,
    }


# ── ENDPOINT 9: Social Platforms Status ──────────────────────────────────────

@router.get("/api/social/platforms")
async def social_platforms(request: Request):
    """Connected social platform status + GHL integration health."""
    verify_sal_key(request)

    ghl_connected = bool(GHL_PRIVATE_TOKEN)

    return {
        "platforms": [
            {
                "id": "linkedin",
                "name": "LinkedIn",
                "status": "connected" if ghl_connected else "not_connected",
                "via": "GHL Social Studio",
                "icon": "in",
                "color": "#0077b5",
            },
            {
                "id": "twitter",
                "name": "X (Twitter)",
                "status": "connected" if ghl_connected else "registering",
                "via": "GHL Social Studio",
                "icon": "X",
                "color": "#000000",
            },
            {
                "id": "instagram",
                "name": "Instagram",
                "status": "connected" if ghl_connected else "via_meta",
                "via": "Meta Business Suite via GHL",
                "icon": "ig",
                "color": "#e1306c",
            },
            {
                "id": "facebook",
                "name": "Facebook",
                "status": "connected" if ghl_connected else "via_meta",
                "via": "Meta Business Suite via GHL",
                "icon": "fb",
                "color": "#1877f2",
            },
            {
                "id": "tiktok",
                "name": "TikTok",
                "status": "pending",
                "via": "GHL Social Studio",
                "icon": "tt",
                "color": "#010101",
            },
            {
                "id": "youtube",
                "name": "YouTube",
                "status": "connected" if ghl_connected else "via_google",
                "via": "Google via GHL",
                "icon": "yt",
                "color": "#ff0000",
            },
            {
                "id": "telegram",
                "name": "Telegram",
                "status": "live",
                "via": "Direct Bot API",
                "handle": "@SaintSalLabsBot",
                "icon": "tg",
                "color": "#0088cc",
            },
        ],
        "ghl_connected": ghl_connected,
        "ghl_location_id": GHL_LOCATION_ID if ghl_connected else None,
        "updated_at": datetime.utcnow().isoformat(),
    }
