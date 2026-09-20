"""
SaintSal™ Labs — Profile, Tha Saints CRM Intel Hub, Dashboard, and Metering Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)
Owner: Ryan "Cap" Capatosto

Routes:
  GET  /api/profile/{user_id}               — Full user profile from Supabase
  POST /api/profile/{user_id}               — Update profile fields
  GET  /api/profile/{user_id}/preferences   — Business DNA + news prefs
  POST /api/profile/{user_id}/preferences   — Save preferences

  GET  /api/ghl/stats                       — Pipeline stats for dashboard
  GET  /api/ghl/contacts                    — Contacts list (paginated)
  POST /api/ghl/contacts/search             — Search contacts
  POST /api/ghl/contacts/create             — Create contact
  GET  /api/ghl/pipelines                   — All pipelines with stages + deals
  GET  /api/ghl/pipeline/{pipeline_id}/deals — Deals in a specific pipeline
  POST /api/ghl/tasks                       — Create follow-up task
  GET  /api/ghl/tasks                       — Due tasks for today
  GET  /api/ghl/activity                    — Recent activity feed

  GET  /api/dashboard/stats                 — Aggregate dashboard stats
  GET  /api/metering/usage/{user_id}        — Compute usage for current period
  POST /api/metering/log                    — Log compute usage

NOTE: Register this router in server.py BEFORE the static mount:
    from routes.profile import router as profile_router
    app.include_router(profile_router)
"""

import os
import json
from datetime import datetime, date
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

router = APIRouter()

# ── Credentials ───────────────────────────────────────────────────────────────

GHL_BASE          = "https://rest.gohighlevel.com/v1"
GHL_TOKEN         = os.environ.get("GHL_PRIVATE_TOKEN", "")
GHL_LOC           = os.environ.get("GHL_LOCATION_ID", "oRA8vL3OSiCPjpwmEC0V")
SUPABASE_URL      = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE  = os.environ.get("SUPABASE_SERVICE_KEY", "")
SAL_GATEWAY       = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

TIER_COMPUTE_LIMITS = {
    "free":       100,
    "starter":    500,
    "pro":        2000,
    "teams":      10000,
    "enterprise": 999999,
}

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _verify_key(request: Request) -> None:
    key = request.headers.get("x-sal-key", "")
    if key != SAL_GATEWAY:
        raise HTTPException(403, "Invalid gateway key")


def _ghl_headers() -> dict:
    return {
        "Authorization": f"Bearer {GHL_TOKEN}",
        "Content-Type": "application/json",
    }


def _supabase_headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE,
        "Authorization": f"Bearer {SUPABASE_SERVICE}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

# ── Pydantic models ───────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    full_name:    Optional[str] = None
    email:        Optional[str] = None
    avatar_url:   Optional[str] = None
    plan_tier:    Optional[str] = None
    ghl_location_id: Optional[str] = None


class PreferencesUpdate(BaseModel):
    business_dna:           Optional[Dict[str, Any]] = None
    news_prefs:             Optional[Dict[str, Any]] = None
    notification_settings:  Optional[Dict[str, Any]] = None
    team_ids:               Optional[List[str]] = None


class ContactCreate(BaseModel):
    firstName:  str
    lastName:   str = ""
    email:      str = ""
    phone:      str = ""
    tags:       List[str] = []
    source:     str = "SaintSal Labs"


class ContactSearch(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0


class TaskCreate(BaseModel):
    title:       str
    due_date:    str = ""
    contact_id:  str = ""
    assigned_to: str = ""
    description: str = ""


class MeteringLog(BaseModel):
    user_id:       str
    compute_units: int = 1
    feature:       str = ""
    model:         str = ""
    tokens_used:   int = 0


class BusinessDNAGenerate(BaseModel):
    user_id:        str
    elevator_pitch: str


# ── Supabase helpers ──────────────────────────────────────────────────────────

async def _sb_get(table: str, params: dict) -> list:
    """Generic Supabase REST GET."""
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return []
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(
            f"{SUPABASE_URL}/rest/v1/{table}",
            params=params,
            headers=_supabase_headers(),
        )
        if res.status_code not in (200, 206):
            return []
        return res.json() or []


async def _sb_upsert(table: str, data: dict) -> dict:
    """Generic Supabase REST UPSERT."""
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return {}
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            json=data,
            headers=headers,
        )
        rows = res.json()
        return rows[0] if isinstance(rows, list) and rows else rows or {}


async def _sb_patch(table: str, match: dict, data: dict) -> dict:
    """Generic Supabase REST PATCH."""
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return {}
    params = {k: f"eq.{v}" for k, v in match.items()}
    headers = _supabase_headers()
    headers["Prefer"] = "return=representation"
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.patch(
            f"{SUPABASE_URL}/rest/v1/{table}",
            params=params,
            json=data,
            headers=headers,
        )
        rows = res.json()
        return rows[0] if isinstance(rows, list) and rows else {}


# ── GHL helpers ───────────────────────────────────────────────────────────────

async def _ghl_get(path: str, params: dict = None) -> dict:
    """GET from Tha Saints CRM API with error passthrough."""
    if not GHL_TOKEN:
        return {"error": "GHL_PRIVATE_TOKEN not configured"}
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.get(
            f"{GHL_BASE}{path}",
            params=params or {},
            headers=_ghl_headers(),
        )
        if res.status_code not in (200, 201):
            return {"error": f"GHL {res.status_code}", "body": res.text[:200]}
        return res.json()


async def _ghl_post(path: str, data: dict) -> dict:
    """POST to Tha Saints CRM API."""
    if not GHL_TOKEN:
        return {"error": "GHL_PRIVATE_TOKEN not configured"}
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(
            f"{GHL_BASE}{path}",
            json=data,
            headers=_ghl_headers(),
        )
        if res.status_code not in (200, 201):
            return {"error": f"GHL {res.status_code}", "body": res.text[:200]}
        return res.json()


# ══════════════════════════════════════════════════════════════════════════════
# PROFILE ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/profile/{user_id}")
async def get_profile(user_id: str, request: Request):
    """Return full user profile from Supabase profiles table."""
    _verify_key(request)
    rows = await _sb_get("profiles", {
        "id": f"eq.{user_id}",
        "select": "id,full_name,email,plan_tier,stripe_customer_id,ghl_location_id,avatar_url,created_at,updated_at",
    })
    if not rows:
        raise HTTPException(404, "Profile not found")
    return JSONResponse({"ok": True, "profile": rows[0]})


@router.post("/api/profile/{user_id}")
async def update_profile(user_id: str, request: Request):
    """Partial-update profile fields."""
    _verify_key(request)
    body = await request.json()
    # Whitelist updatable fields
    allowed = {"full_name", "email", "avatar_url", "ghl_location_id"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "No updatable fields provided")
    updates["updated_at"] = datetime.utcnow().isoformat()
    result = await _sb_patch("profiles", {"id": user_id}, updates)
    return JSONResponse({"ok": True, "profile": result})


@router.get("/api/profile/{user_id}/preferences")
async def get_preferences(user_id: str, request: Request):
    """Load Business DNA + notification prefs + news prefs."""
    _verify_key(request)
    rows = await _sb_get("user_preferences", {
        "user_id": f"eq.{user_id}",
        "select": "user_id,business_dna,news_prefs,notification_settings,team_ids",
    })
    prefs = rows[0] if rows else {
        "user_id": user_id,
        "business_dna": {},
        "news_prefs": {},
        "notification_settings": {},
        "team_ids": [],
    }
    return JSONResponse({"ok": True, "preferences": prefs})


@router.post("/api/profile/{user_id}/preferences")
async def save_preferences(user_id: str, body: PreferencesUpdate, request: Request):
    """Upsert user preferences (business DNA, news prefs, notifications)."""
    _verify_key(request)
    data = {"user_id": user_id}
    if body.business_dna is not None:
        data["business_dna"] = json.dumps(body.business_dna)
    if body.news_prefs is not None:
        data["news_prefs"] = json.dumps(body.news_prefs)
    if body.notification_settings is not None:
        data["notification_settings"] = json.dumps(body.notification_settings)
    if body.team_ids is not None:
        data["team_ids"] = json.dumps(body.team_ids)
    result = await _sb_upsert("user_preferences", data)
    return JSONResponse({"ok": True, "preferences": result})


@router.post("/api/profile/{user_id}/preferences/generate-dna")
async def generate_business_dna(user_id: str, body: BusinessDNAGenerate, request: Request):
    """
    Use Claude to auto-generate Business DNA fields from an elevator pitch.
    Returns a complete business_dna object ready to save.
    """
    _verify_key(request)
    if not ANTHROPIC_API_KEY:
        raise HTTPException(503, "ANTHROPIC_API_KEY not configured")

    system_prompt = """You are a business intelligence analyst for SaintSal™ Labs.
Given an elevator pitch or business description, extract and infer structured business DNA fields.
Return ONLY valid JSON — no markdown, no explanation, no extra text.
Return exactly this structure:
{
  "company_name": "...",
  "industry": "...",
  "stage": "pre-revenue|seed|series-a|established",
  "revenue_range": "...",
  "employee_count": "...",
  "target_market": "...",
  "elevator_pitch": "...",
  "key_competitors": ["...", "..."],
  "core_differentiators": ["...", "..."],
  "funding_status": "...",
  "geographic_focus": "..."
}"""

    user_msg = f"Generate business DNA from this description:\n\n{body.elevator_pitch}"

    try:
        import anthropic as anthropic_sdk
        ac = anthropic_sdk.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
        response = await ac.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        dna = json.loads(raw)
        return JSONResponse({"ok": True, "business_dna": dna})
    except json.JSONDecodeError:
        raise HTTPException(500, "Claude returned invalid JSON — try a more detailed description")
    except Exception as e:
        raise HTTPException(500, f"Generation failed: {str(e)[:150]}")


# ══════════════════════════════════════════════════════════════════════════════
# GHL INTEL HUB ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════



















# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD STATS ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/dashboard/stats")
async def dashboard_stats(request: Request, user_id: str = ""):
    """
    Aggregate dashboard stats combining Tha Saints CRM + Supabase usage + profile data.
    Returns everything the Headquarters page needs in one call.
    """
    from routes.saints_crm import resolve_tenant, stats, search, SearchInput
    tenant = await resolve_tenant(request)
    if tenant.principal != "server":
        if user_id and user_id != tenant.principal:
            raise HTTPException(403, "This dashboard belongs to a different account.")
        user_id = tenant.principal
    crm = await stats(tenant)
    total_contacts = crm["stats"]["total_contacts"]
    pipelines = crm["pipelines"]
    pipelines_count = len(pipelines)
    active_deals = crm["stats"]["active_deals"]
    revenue_mtd = crm["stats"]["revenue_mtd"]
    tasks_due_today = crm["stats"]["tasks_due_today"]
    recent_leads = (await search(tenant, SearchInput(limit=5)))["contacts"]
    ghl_ok = True

    # ── Usage + billing ───────────────────────────────────────────────────────
    plan_tier           = "free"
    compute_used        = 0
    compute_limit       = TIER_COMPUTE_LIMITS["free"]
    builder_sessions    = 0
    stripe_customer_id  = None

    if user_id and SUPABASE_URL:
        try:
            profile_rows = await _sb_get("profiles", {
                "id": f"eq.{user_id}",
                "select": "plan_tier,stripe_customer_id,full_name",
            })
            if profile_rows:
                plan_tier          = profile_rows[0].get("plan_tier", "free") or "free"
                stripe_customer_id = profile_rows[0].get("stripe_customer_id")
                compute_limit      = TIER_COMPUTE_LIMITS.get(plan_tier, 100)

            # Current-month usage
            month_start = date.today().replace(day=1).isoformat()
            usage_rows = await _sb_get("usage_log", {
                "user_id": f"eq.{user_id}",
                "created_at": f"gte.{month_start}",
                "select": "compute_units",
            })
            compute_used = sum(r.get("compute_units", 1) for r in usage_rows)

            # Builder sessions
            session_rows = await _sb_get("builder_sessions", {
                "user_id": f"eq.{user_id}",
                "select": "id",
            })
            builder_sessions = len(session_rows)
        except Exception as e:
            print(f"[Dashboard] Supabase error: {e}")

    # ── Platform health (minimal) ─────────────────────────────────────────────
    health = {
        "api":       "operational",
        "ghl":       "operational" if ghl_ok else "unconfigured",
        "supabase":  "operational" if bool(SUPABASE_URL) else "unconfigured",
        "anthropic": "operational" if bool(ANTHROPIC_API_KEY) else "unconfigured",
    }

    return JSONResponse({
        "ok": True,
        "ghl": {
            "total_contacts":  total_contacts,
            "pipelines_count": pipelines_count,
            "active_deals":    active_deals,
            "revenue_mtd":     revenue_mtd,
            "tasks_due_today": tasks_due_today,
        },
        "pipelines":    pipelines,
        "recent_leads": recent_leads,
        "usage": {
            "compute_minutes_used":  compute_used,
            "compute_minutes_limit": compute_limit,
            "tier":                  plan_tier,
            "builder_sessions":      builder_sessions,
            "stripe_customer_id":    stripe_customer_id,
        },
        "health": health,
    })


# ══════════════════════════════════════════════════════════════════════════════
# METERING ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/api/metering/usage/{user_id}")
async def metering_usage_by_user(user_id: str, request: Request):
    """Compute usage for the current billing period (calendar month)."""
    _verify_key(request)

    if not SUPABASE_URL:
        return JSONResponse({"ok": True, "compute_used": 0, "compute_limit": 100, "tier": "free"})

    # Get plan tier
    plan_tier = "free"
    try:
        profile_rows = await _sb_get("profiles", {
            "id": f"eq.{user_id}",
            "select": "plan_tier",
        })
        if profile_rows:
            plan_tier = profile_rows[0].get("plan_tier", "free") or "free"
    except Exception:
        pass

    compute_limit = TIER_COMPUTE_LIMITS.get(plan_tier, 100)

    # Sum usage for current calendar month
    month_start = date.today().replace(day=1).isoformat()
    compute_used = 0
    try:
        usage_rows = await _sb_get("usage_log", {
            "user_id": f"eq.{user_id}",
            "created_at": f"gte.{month_start}",
            "select": "compute_units,feature,created_at",
        })
        compute_used = sum(r.get("compute_units", 1) for r in usage_rows)
    except Exception:
        usage_rows = []

    return JSONResponse({
        "ok": True,
        "user_id":       user_id,
        "tier":          plan_tier,
        "compute_used":  compute_used,
        "compute_limit": compute_limit,
        "remaining":     max(0, compute_limit - compute_used),
        "period_start":  month_start,
        "over_limit":    compute_used >= compute_limit,
        "usage_rows":    usage_rows[-20:],  # Last 20 events for detail view
    })


@router.post("/api/metering/log")
async def metering_log_usage(body: MeteringLog, request: Request):
    """Log compute usage event to Supabase usage_log."""
    _verify_key(request)

    if not SUPABASE_URL:
        return JSONResponse({"ok": True, "skipped": "Supabase not configured"})

    record = {
        "user_id":       body.user_id,
        "compute_units": body.compute_units,
        "feature":       body.feature,
        "model":         body.model,
        "tokens_used":   body.tokens_used,
        "created_at":    datetime.utcnow().isoformat(),
    }

    try:
        await _sb_upsert("usage_log", record)
        return JSONResponse({"ok": True, "logged": record})
    except Exception as e:
        # Never block the calling feature on metering errors
        print(f"[Metering] Log failed (non-fatal): {e}")
        return JSONResponse({"ok": True, "skipped": str(e)[:100]})
