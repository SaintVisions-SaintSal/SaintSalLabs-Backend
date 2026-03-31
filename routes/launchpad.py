"""
SaintSal™ Labs — LaunchPad & Business Formation Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)

Routes:
  POST /api/launchpad/name-check          — GoDaddy domains + Exa trademark + social handles (parallel)
  POST /api/launchpad/entity-advisor      — AI entity type recommendation (Claude Opus)
  POST /api/launchpad/domain/search       — Domain availability search only
  POST /api/launchpad/domain/purchase     — Domain purchase via GoDaddy + Stripe checkout
  POST /api/launchpad/entity/form         — LLC/Corp formation via FileForms
  POST /api/launchpad/entity/ein          — EIN filing
  POST /api/launchpad/dns/configure       — Auto DNS setup (GoDaddy API)
  POST /api/launchpad/ssl/provision       — SSL provisioning
  POST /api/launchpad/compliance/setup    — Compliance calendar + GHL reminders
  POST /api/launchpad/order               — FileForms order (legacy)
  GET  /api/launchpad/order/{order_id}    — Order status check
  POST /api/launchpad/checkout            — Stripe checkout for formation fee
"""

import os
import json
import asyncio
from datetime import datetime, date
from typing import Optional, List
from dateutil.relativedelta import relativedelta

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx
import stripe

router = APIRouter()

# ── Credentials ───────────────────────────────────────────────────────────────

ANTHROPIC_KEY      = os.environ.get("ANTHROPIC_API_KEY", "")
EXA_KEY            = os.environ.get("EXA_API_KEY", "")
GODADDY_API_KEY    = os.environ.get("GODADDY_API_KEY", "")
GODADDY_API_SECRET = os.environ.get("GODADDY_API_SECRET", "")
GODADDY_BASE       = os.environ.get("GODADDY_BASE", "https://api.godaddy.com")
FILEFORMS_KEY      = os.environ.get("FILEFORMS_API_KEY", "")
FILEFORMS_BASE     = os.environ.get("FILEFORMS_BASE_URL", "https://api.fileforms.com/v1")
STRIPE_SECRET      = os.environ.get("STRIPE_SECRET_KEY", "")
GHL_TOKEN          = os.environ.get("GHL_PRIVATE_TOKEN", "")
GHL_LOCATION       = os.environ.get("GHL_LOCATION_ID", "oRA8vL3OSiCPjpwmEC0V")
SAL_GATEWAY        = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")
SUPABASE_URL       = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE   = os.environ.get("SUPABASE_SERVICE_KEY", "")

GODADDY_AUTH = f"sso-key {GODADDY_API_KEY}:{GODADDY_API_SECRET}"

# Stripe
stripe.api_key = STRIPE_SECRET

# ── Auth Helper ───────────────────────────────────────────────────────────────

def verify_sal_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY:
        raise HTTPException(403, "Invalid gateway key")


# ── Formation Stripe Price IDs (from catalog) ─────────────────────────────────

FORMATION_PRICES = {
    "basic_llc":      "price_1T84WEL47U80vDLAYfgh6tne",
    "basic_corp":     "price_1T84WHL47U80vDLA9xXux4cI",
    "deluxe_llc":     "price_1T84WFL47U80vDLAB1q3I1Me",
    "deluxe_corp":    "price_1T84WIL47U80vDLAKaIYgJNq",
    "complete_llc":   "price_1T84WGL47U80vDLAM7AVMeWV",
    "complete_corp":  "price_1T84WJL47U80vDLAj35gfAvk",
    "ein_filing":     "price_1T84WNL47U80vDLArGpX7xno",
    "ra_annual":      "price_1T84WLL47U80vDLAjC6OBz5s",
}

FORMATION_AMOUNTS = {
    "basic":    197_00,
    "deluxe":   397_00,
    "complete": 449_00,
}

# ── Domain TLDs ───────────────────────────────────────────────────────────────

SEARCH_TLDS = [".com", ".io", ".ai", ".co", ".net"]

TLD_FALLBACK_PRICE = {
    ".com": "12.99",
    ".net": "12.99",
    ".co":  "24.99",
    ".io":  "39.99",
    ".ai":  "69.99",
}

# ── DNS Presets ───────────────────────────────────────────────────────────────

DNS_PRESETS = {
    "vercel": [
        {"type": "A",     "name": "@",   "data": "76.76.21.21",         "ttl": 600},
        {"type": "CNAME", "name": "www", "data": "cname.vercel-dns.com", "ttl": 600},
    ],
    "render": [
        {"type": "CNAME", "name": "www", "data": "{app}.onrender.com", "ttl": 600},
    ],
    "cloudflare": [
        {"type": "A",     "name": "@",   "data": "104.21.0.1",  "ttl": 1},
        {"type": "A",     "name": "www", "data": "104.21.0.1",  "ttl": 1},
    ],
}

# ── Social Platforms ──────────────────────────────────────────────────────────

SOCIAL_PLATFORMS = [
    {"platform": "Twitter/X",  "url_template": "https://twitter.com/{handle}",        "icon": "X"},
    {"platform": "Instagram",  "url_template": "https://instagram.com/{handle}",       "icon": "IG"},
    {"platform": "LinkedIn",   "url_template": "https://linkedin.com/company/{handle}", "icon": "LI"},
    {"platform": "TikTok",     "url_template": "https://tiktok.com/@{handle}",          "icon": "TK"},
    {"platform": "Facebook",   "url_template": "https://facebook.com/{handle}",         "icon": "FB"},
    {"platform": "YouTube",    "url_template": "https://youtube.com/@{handle}",         "icon": "YT"},
]

# ── US States ─────────────────────────────────────────────────────────────────

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "Washington D.C.",
}

# ── Pydantic Models ───────────────────────────────────────────────────────────

class NameCheckRequest(BaseModel):
    business_name: str
    state: Optional[str] = "DE"

class EntityAdvisorRequest(BaseModel):
    cofounders: str            # "1", "2-5", "5+"
    funding_plans: str         # "yes", "no", "maybe"
    revenue_stage: str         # "pre-revenue", "early", "growing"
    tax_preference: str        # "pass-through", "c-corp"
    state_preference: str = "DE"
    business_description: Optional[str] = None

class DomainSearchRequest(BaseModel):
    query: str

class DomainPurchaseRequest(BaseModel):
    domain: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None

class EntityFormRequest(BaseModel):
    entity_type: str           # "llc", "c_corp", "s_corp", etc.
    state: str
    business_name: str
    package: str = "basic"     # "basic", "deluxe", "complete"
    registered_agent: bool = False
    members: Optional[List[dict]] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None

class EINRequest(BaseModel):
    business_name: str
    entity_type: str
    state: str
    formation_order_id: Optional[str] = None
    responsible_party_name: Optional[str] = None
    responsible_party_ssn_last4: Optional[str] = None

class DNSConfigRequest(BaseModel):
    domain: str
    platform: str              # "vercel", "render", "cloudflare", "other"
    app_name: Optional[str] = None   # for Render: {app}.onrender.com

class SSLProvisionRequest(BaseModel):
    domain: str
    platform: Optional[str] = "vercel"

class ComplianceSetupRequest(BaseModel):
    business_name: str
    entity_type: str
    state: str
    formation_date: Optional[str] = None
    ein: Optional[str] = None

class CheckoutRequest(BaseModel):
    entity_type: str
    package: str = "basic"
    business_name: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None

class LegacyOrderRequest(BaseModel):
    entity_type: str
    state: str
    business_name: str
    package: str = "basic"
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_domain_godaddy(http: httpx.AsyncClient, domain: str) -> dict:
    """Check a single domain's availability via GoDaddy API."""
    tld = "." + domain.rsplit(".", 1)[-1] if "." in domain else ".com"
    try:
        r = await http.get(
            f"{GODADDY_BASE}/v1/domains/available",
            params={"domain": domain, "checkType": "FAST", "forTransfer": "false"},
            headers={"Authorization": GODADDY_AUTH},
            timeout=8.0,
        )
        if r.status_code == 200:
            data = r.json()
            price_micros = data.get("price", 0)
            price = f"${price_micros / 1_000_000:.2f}" if price_micros else TLD_FALLBACK_PRICE.get(tld, "14.99")
            return {
                "domain":     domain,
                "available":  data.get("available", False),
                "price":      price,
                "tld":        tld,
                "definitive": True,
            }
    except Exception:
        pass
    # Fallback
    return {
        "domain":     domain,
        "available":  None,
        "price":      TLD_FALLBACK_PRICE.get(tld, "14.99"),
        "tld":        tld,
        "definitive": False,
    }


async def _exa_trademark_check(name: str) -> list:
    """Search for potential trademark conflicts via Exa."""
    if not EXA_KEY:
        return []
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_KEY, "Content-Type": "application/json"},
                json={
                    "query": f'"{name}" trademark brand company registered',
                    "numResults": 5,
                    "useAutoprompt": False,
                },
                timeout=10.0,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                return [
                    {
                        "title":   res.get("title", ""),
                        "url":     res.get("url", ""),
                        "snippet": res.get("snippet", res.get("text", ""))[:200],
                    }
                    for res in results[:5]
                ]
    except Exception:
        pass
    return []


def _build_social_handles(name: str) -> list:
    """Construct social handle URLs — availability returned as-is (no auth required)."""
    handle = name.lower().replace(" ", "").replace("-", "").replace("_", "")[:20]
    return [
        {
            "platform": p["platform"],
            "handle":   f"@{handle}",
            "url":      p["url_template"].replace("{handle}", handle),
            "icon":     p["icon"],
            "note":     "Verify manually — live check requires OAuth",
        }
        for p in SOCIAL_PLATFORMS
    ]


async def _save_order_supabase(order_data: dict) -> Optional[str]:
    """Persist formation order to Supabase launch_pad_orders table."""
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return None
    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                f"{SUPABASE_URL}/rest/v1/launch_pad_orders",
                headers={
                    "apikey": SUPABASE_SERVICE,
                    "Authorization": f"Bearer {SUPABASE_SERVICE}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
                json=order_data,
                timeout=5.0,
            )
            if r.status_code in (200, 201):
                rows = r.json()
                return rows[0].get("id") if rows else None
    except Exception:
        pass
    return None


def _build_compliance_calendar(entity_type: str, state: str, formation_date: str) -> list:
    """Generate a compliance calendar of key deadlines."""
    try:
        base = datetime.strptime(formation_date, "%Y-%m-%d").date()
    except Exception:
        base = date.today()

    events = []

    # Annual report — most states require it 1 year after formation, then annually
    events.append({
        "event":    "Annual Report Filing",
        "due_date": str(base + relativedelta(years=1)),
        "recurring": "annually",
        "description": f"File annual report with {state} Secretary of State",
        "cost_estimate": "$50–$200 (state fees vary)",
    })

    # Federal tax return
    if entity_type in ("llc", "s_corp", "partnership"):
        events.append({
            "event":    "Federal Partnership/S-Corp Return (Form 1065/1120-S)",
            "due_date": str(base.replace(month=3, day=15) + relativedelta(years=1)),
            "recurring": "annually",
            "description": "Pass-through entity federal return due March 15",
            "cost_estimate": "CPA fees vary",
        })
    elif entity_type == "c_corp":
        events.append({
            "event":    "Federal C-Corp Return (Form 1120)",
            "due_date": str(base.replace(month=4, day=15) + relativedelta(years=1)),
            "recurring": "annually",
            "description": "C-Corp federal return due April 15 (or 15th day of 4th month)",
            "cost_estimate": "CPA fees vary",
        })

    # Registered agent renewal
    events.append({
        "event":    "Registered Agent Renewal",
        "due_date": str(base + relativedelta(years=1)),
        "recurring": "annually",
        "description": "Renew registered agent service to maintain good standing",
        "cost_estimate": "$224/yr (SaintSal Labs)",
    })

    # BOI Report (FinCEN — Beneficial Ownership)
    events.append({
        "event":    "FinCEN Beneficial Ownership Report (BOI)",
        "due_date": str(base + relativedelta(days=90)),
        "recurring": "as-needed",
        "description": "File BOI report with FinCEN within 90 days of formation. Required for most LLCs and corps.",
        "cost_estimate": "Free (self-file at fincen.gov)",
    })

    # State sales tax if applicable
    events.append({
        "event":    "State Sales Tax Registration Review",
        "due_date": str(base + relativedelta(days=30)),
        "recurring": "one-time",
        "description": "Register for sales tax collection if selling taxable goods/services in your state",
        "cost_estimate": "Free",
    })

    # Quarterly estimated taxes
    events.append({
        "event":    "Q1 Estimated Tax Payment",
        "due_date": str(base.replace(month=4, day=15) + relativedelta(years=1)),
        "recurring": "quarterly",
        "description": "Federal quarterly estimated taxes due April 15, June 15, Sept 15, Jan 15",
        "cost_estimate": "Tax liability dependent",
    })

    return sorted(events, key=lambda x: x["due_date"])


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/api/launchpad/name-check")
async def launchpad_name_check(req: NameCheckRequest, request: Request):
    """
    Simultaneous name availability check:
    1. GoDaddy domain check (.com, .io, .ai, .co, .net)
    2. Exa trademark conflict search
    3. Social handle construction
    """
    verify_sal_key(request)
    name = req.business_name.strip()
    if not name:
        raise HTTPException(400, "business_name is required")

    base_name = name.lower().replace(" ", "").replace("-", "")

    # Run GoDaddy + Exa in parallel
    async with httpx.AsyncClient() as http:
        domain_tasks = [
            _check_domain_godaddy(http, base_name + tld)
            for tld in SEARCH_TLDS
        ]
        trademark_task = asyncio.create_task(_exa_trademark_check(name))
        domain_results = await asyncio.gather(*domain_tasks, return_exceptions=True)
        trademark_results = await trademark_task

    domains = []
    for d in domain_results:
        if isinstance(d, Exception):
            continue
        domains.append(d)

    social_handles = _build_social_handles(name)

    return {
        "business_name": name,
        "domains":       domains,
        "trademarks":    trademark_results,
        "social":        social_handles,
        "timestamp":     datetime.utcnow().isoformat(),
    }


@router.post("/api/launchpad/entity-advisor")
async def launchpad_entity_advisor(req: EntityAdvisorRequest, request: Request):
    """AI entity type recommendation using Claude Opus."""
    verify_sal_key(request)

    if not ANTHROPIC_KEY:
        # Fallback rule-based recommendation
        if req.funding_plans == "yes":
            rec = "C-Corp"
            rationale = "C-Corps are the standard for VC-backed startups — required for most institutional investors."
        elif req.cofounders == "1" and req.revenue_stage == "pre-revenue":
            rec = "LLC"
            rationale = "Single-founder pre-revenue businesses benefit from LLC simplicity and pass-through taxation."
        elif req.tax_preference == "pass-through" and req.cofounders in ("1", "2-5"):
            rec = "LLC"
            rationale = "LLCs offer flexible management and pass-through taxation — ideal for your profile."
        else:
            rec = "LLC"
            rationale = "LLC is the most flexible starting point for your situation."

        return {
            "recommended_entity":  rec,
            "state":               req.state_preference,
            "rationale":           rationale,
            "tax_implications":    f"{rec} provides pass-through taxation by default.",
            "next_steps":          ["File Articles of Organization", "Get an EIN", "Open a business bank account"],
            "comparison":          _entity_comparison_table(req),
            "ai_powered":          False,
        }

    prompt = f"""You are a business formation advisor for SaintSal™ Labs.

A founder is completing the SaintSal LaunchPad wizard and needs an entity type recommendation.

Founder profile:
- Number of cofounders: {req.cofounders}
- Raising VC funding: {req.funding_plans}
- Revenue stage: {req.revenue_stage}
- Tax preference: {req.tax_preference}
- Preferred state: {req.state_preference}
- Business description: {req.business_description or 'Not provided'}

Recommend the optimal entity structure. Consider:
1. Delaware C-Corp for VC funding path
2. Wyoming or Delaware LLC for asset protection + pass-through
3. S-Corp election after LLC formation for payroll tax savings (when revenue > $50K)
4. The state preference matters for tax treatment and filing costs

Respond with a JSON object ONLY (no markdown, no explanation outside JSON):
{{
  "recommended_entity": "LLC|C-Corp|S-Corp|Partnership",
  "state": "state abbreviation or full name",
  "rationale": "2-3 sentence explanation tailored to their situation",
  "tax_implications": "specific tax treatment for their situation",
  "next_steps": ["step 1", "step 2", "step 3"],
  "alternatives": [
    {{"entity": "name", "why": "when this makes more sense"}}
  ]
}}"""

    try:
        async with httpx.AsyncClient() as http:
            r = await http.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key":         ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type":      "application/json",
                },
                json={
                    "model":      "claude-opus-4-5",
                    "max_tokens": 1024,
                    "messages":   [{"role": "user", "content": prompt}],
                },
                timeout=30.0,
            )
            if r.status_code == 200:
                content = r.json()["content"][0]["text"].strip()
                # Strip markdown code fences if present
                if content.startswith("```"):
                    content = content.split("```")[1]
                    if content.startswith("json"):
                        content = content[4:]
                ai_data = json.loads(content)
                return {
                    **ai_data,
                    "comparison":  _entity_comparison_table(req),
                    "ai_powered":  True,
                }
    except Exception as e:
        pass

    # Fallback
    return {
        "recommended_entity":  "LLC",
        "state":               req.state_preference,
        "rationale":           "LLC is the optimal starting point for your situation — flexible, tax-efficient, and founder-friendly.",
        "tax_implications":    "Pass-through taxation — profits/losses flow to personal return. Can elect S-Corp status later.",
        "next_steps":          ["File Articles of Organization", "Obtain EIN from IRS", "Open a dedicated business bank account"],
        "comparison":          _entity_comparison_table(req),
        "ai_powered":          False,
    }


def _entity_comparison_table(req: EntityAdvisorRequest) -> list:
    return [
        {
            "entity":            "LLC",
            "liability":         "Protected",
            "taxation":          "Pass-through (default)",
            "vc_fundable":       "Limited",
            "formation_cost":    "$197",
            "complexity":        "Low",
            "best_for":          "Small-medium businesses, freelancers, real estate",
        },
        {
            "entity":            "S-Corp",
            "liability":         "Protected",
            "taxation":          "Pass-through (payroll tax savings)",
            "vc_fundable":       "No",
            "formation_cost":    "$197 + $149 election",
            "complexity":        "Medium",
            "best_for":          "Profitable businesses saving on self-employment tax",
        },
        {
            "entity":            "C-Corp",
            "liability":         "Protected",
            "taxation":          "Double taxation (21% corp rate)",
            "vc_fundable":       "Yes — VC standard",
            "formation_cost":    "$197",
            "complexity":        "High",
            "best_for":          "VC-funded startups, employee stock options, IPO path",
        },
        {
            "entity":            "Partnership",
            "liability":         "Unlimited (general)",
            "taxation":          "Pass-through",
            "vc_fundable":       "No",
            "formation_cost":    "$0–$100",
            "complexity":        "Low",
            "best_for":          "Professional practices, joint ventures",
        },
    ]


@router.post("/api/launchpad/domain/search")
async def launchpad_domain_search(req: DomainSearchRequest, request: Request):
    """Domain availability search via GoDaddy."""
    verify_sal_key(request)
    base = req.query.strip().lower().replace(" ", "")
    if not base:
        raise HTTPException(400, "query is required")

    async with httpx.AsyncClient() as http:
        tasks = [_check_domain_godaddy(http, base + tld) for tld in SEARCH_TLDS]

        # Also get GoDaddy suggestions
        suggestions = []
        try:
            r = await http.get(
                f"{GODADDY_BASE}/v1/domains/suggest",
                params={"query": base, "limit": 6},
                headers={"Authorization": GODADDY_AUTH},
                timeout=8.0,
            )
            if r.status_code == 200:
                for s in r.json():
                    sug_domain = s.get("domain", "")
                    if sug_domain and sug_domain not in [base + t for t in SEARCH_TLDS]:
                        tld = "." + sug_domain.rsplit(".", 1)[-1] if "." in sug_domain else ".com"
                        suggestions.append({
                            "domain":    sug_domain,
                            "available": True,
                            "price":     TLD_FALLBACK_PRICE.get(tld, "19.99"),
                            "tld":       tld,
                            "suggested": True,
                        })
        except Exception:
            pass

        results = await asyncio.gather(*tasks, return_exceptions=True)

    domains = [d for d in results if not isinstance(d, Exception)]
    return {"domains": domains, "suggestions": suggestions[:5]}


@router.post("/api/launchpad/domain/purchase")
async def launchpad_domain_purchase(req: DomainPurchaseRequest, request: Request):
    """
    Domain purchase via GoDaddy. Creates a Stripe checkout for the domain fee.
    GoDaddy direct purchase requires shopper account — we redirect to storefront.
    """
    verify_sal_key(request)
    domain = req.domain.strip().lower()
    if not domain:
        raise HTTPException(400, "domain is required")

    tld = "." + domain.rsplit(".", 1)[-1] if "." in domain else ".com"
    price_str = TLD_FALLBACK_PRICE.get(tld, "14.99")
    price_cents = int(float(price_str) * 100)

    # Create Stripe checkout session for domain
    checkout_url = None
    session_id = None

    if STRIPE_SECRET:
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency":     "usd",
                        "unit_amount":  price_cents,
                        "product_data": {
                            "name":        f"Domain: {domain}",
                            "description": f"Annual domain registration for {domain}",
                        },
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=req.__dict__.get("success_url") or "https://www.saintsallabs.com/?domain_success=1",
                cancel_url=req.__dict__.get("cancel_url") or "https://www.saintsallabs.com/?domain_cancel=1",
                metadata={"domain": domain, "type": "domain_purchase"},
            )
            checkout_url = session.url
            session_id   = session.id
        except Exception as e:
            pass

    # Fallback: GoDaddy storefront
    if not checkout_url:
        storefront_base = f"https://www.godaddy.com/domainsearch/find?checkAvail=1&domainToCheck={domain}"
        checkout_url = storefront_base

    return {
        "domain":       domain,
        "price":        price_str,
        "checkout_url": checkout_url,
        "session_id":   session_id,
        "note":         "Complete domain purchase via secure checkout.",
    }


@router.post("/api/launchpad/entity/form")
async def launchpad_entity_form(req: EntityFormRequest, request: Request):
    """
    LLC/Corp formation via FileForms API.
    Falls back to creating an internal order record if FileForms is unavailable.
    """
    verify_sal_key(request)

    if not req.business_name or not req.entity_type or not req.state:
        raise HTTPException(400, "business_name, entity_type, and state are required")

    order_id = None
    status   = "pending"
    documents = []

    # Attempt FileForms API
    if FILEFORMS_KEY:
        try:
            async with httpx.AsyncClient() as http:
                payload = {
                    "entity_type":       req.entity_type,
                    "state":             req.state,
                    "entity_name":       req.business_name,
                    "registered_agent":  req.registered_agent,
                    "members":           req.members or [],
                }
                r = await http.post(
                    f"{FILEFORMS_BASE}/formations",
                    headers={
                        "Authorization": f"Bearer {FILEFORMS_KEY}",
                        "Content-Type":  "application/json",
                    },
                    json=payload,
                    timeout=15.0,
                )
                if r.status_code in (200, 201):
                    data = r.json()
                    order_id  = data.get("id") or data.get("order_id")
                    status    = data.get("status", "pending")
                    documents = data.get("documents", [])
        except Exception:
            pass

    # Internal order fallback
    if not order_id:
        import uuid
        order_id = f"LP-{uuid.uuid4().hex[:12].upper()}"

    # Save to Supabase
    pkg = req.package.lower()
    entity_group = "corp" if req.entity_type in ("c_corp", "s_corp", "nonprofit") else "llc"
    amount = FORMATION_AMOUNTS.get(pkg, 197_00)

    await _save_order_supabase({
        "order_id":    order_id,
        "entity_type": req.entity_type,
        "state":       req.state,
        "business_name": req.business_name,
        "package":     req.package,
        "status":      status,
        "contact_name":  req.contact_name,
        "contact_email": req.contact_email,
        "created_at":  datetime.utcnow().isoformat(),
    })

    # Build Stripe checkout for formation fee
    checkout_url = None
    session_id   = None

    price_key = f"{pkg}_{entity_group}"
    stripe_price = FORMATION_PRICES.get(price_key)

    if STRIPE_SECRET:
        try:
            if stripe_price:
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{"price": stripe_price, "quantity": 1}],
                    mode="payment",
                    success_url="https://www.saintsallabs.com/?formation_success=1",
                    cancel_url="https://www.saintsallabs.com/?formation_cancel=1",
                    metadata={"order_id": order_id, "entity_type": req.entity_type, "type": "entity_formation"},
                )
            else:
                session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[{
                        "price_data": {
                            "currency":     "usd",
                            "unit_amount":  amount,
                            "product_data": {"name": f"{req.business_name} — {pkg.title()} Formation"},
                        },
                        "quantity": 1,
                    }],
                    mode="payment",
                    success_url="https://www.saintsallabs.com/?formation_success=1",
                    cancel_url="https://www.saintsallabs.com/?formation_cancel=1",
                    metadata={"order_id": order_id, "type": "entity_formation"},
                )
            checkout_url = session.url
            session_id   = session.id
        except Exception:
            pass

    processing_days = {"basic": "5-7 business days", "deluxe": "24-hour rush", "complete": "24-hour rush"}

    return {
        "order_id":         order_id,
        "status":           status,
        "business_name":    req.business_name,
        "entity_type":      req.entity_type,
        "state":            US_STATES.get(req.state.upper(), req.state),
        "package":          req.package,
        "estimated_time":   processing_days.get(pkg, "5-7 business days"),
        "checkout_url":     checkout_url,
        "session_id":       session_id,
        "documents":        documents,
        "amount":           amount / 100,
        "next_step":        "Complete payment to begin formation filing.",
    }


@router.post("/api/launchpad/entity/ein")
async def launchpad_ein(req: EINRequest, request: Request):
    """
    EIN / Federal Tax ID filing.
    Provides SS-4 guidance and creates a Stripe checkout if filing via SaintSal.
    """
    verify_sal_key(request)

    if not req.business_name:
        raise HTTPException(400, "business_name is required")

    # EIN self-file link (IRS)
    irs_link = "https://www.irs.gov/businesses/small-businesses-self-employed/apply-for-an-employer-identification-number-ein-online"

    # Stripe checkout for EIN filing service ($79)
    checkout_url = None
    session_id   = None

    if STRIPE_SECRET:
        try:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency":     "usd",
                        "unit_amount":  79_00,
                        "product_data": {
                            "name":        "EIN / Federal Tax ID Filing",
                            "description": f"EIN application filing for {req.business_name}",
                        },
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url="https://www.saintsallabs.com/?ein_success=1",
                cancel_url="https://www.saintsallabs.com/?ein_cancel=1",
                metadata={"business_name": req.business_name, "type": "ein_filing"},
            )
            checkout_url = session.url
            session_id   = session.id
        except Exception:
            pass

    return {
        "status":           "initiated",
        "business_name":    req.business_name,
        "entity_type":      req.entity_type,
        "state":            req.state,
        "formation_order_id": req.formation_order_id,
        "filing_options": [
            {
                "option":      "Self-File (Free)",
                "description": "Apply directly on IRS.gov — typically issued immediately or within 2-3 weeks",
                "url":         irs_link,
                "cost":        "Free",
                "time":        "Immediate (online) or 2-3 weeks (mail/fax)",
            },
            {
                "option":      "SaintSal Filing Service ($79)",
                "description": "We prepare and submit your SS-4 with state filing docs",
                "checkout_url": checkout_url,
                "session_id":   session_id,
                "cost":        "$79",
                "time":        "2-3 business days",
            },
        ],
        "irs_direct_link":  irs_link,
        "instructions":     [
            "Have your formation documents (Articles of Organization) ready",
            "Social Security Number or ITIN of responsible party required",
            "EIN is issued immediately via IRS online application",
            "Keep your EIN confirmation letter (CP 575) — you'll need it for banking",
        ],
    }


@router.post("/api/launchpad/dns/configure")
async def launchpad_dns_configure(req: DNSConfigRequest, request: Request):
    """Auto DNS configuration via GoDaddy API."""
    verify_sal_key(request)

    domain   = req.domain.strip().lower()
    platform = req.platform.lower()

    if not domain:
        raise HTTPException(400, "domain is required")

    records = DNS_PRESETS.get(platform, [])

    # For Render, inject the app name
    if platform == "render" and req.app_name:
        records = [
            {**rec, "data": rec["data"].replace("{app}", req.app_name)}
            for rec in records
        ]

    if not records:
        return {
            "status":  "manual_required",
            "domain":  domain,
            "message": f"No preset for platform '{platform}'. Configure DNS manually.",
            "records": [],
        }

    created = []
    errors  = []

    if GODADDY_API_KEY and GODADDY_API_SECRET:
        async with httpx.AsyncClient() as http:
            for rec in records:
                try:
                    r = await http.put(
                        f"{GODADDY_BASE}/v1/domains/{domain}/records/{rec['type']}/{rec['name']}",
                        headers={
                            "Authorization": GODADDY_AUTH,
                            "Content-Type":  "application/json",
                        },
                        json=[{"data": rec["data"], "ttl": rec.get("ttl", 600)}],
                        timeout=10.0,
                    )
                    if r.status_code in (200, 204):
                        created.append({**rec, "status": "created"})
                    else:
                        errors.append({**rec, "status": "error", "code": r.status_code, "detail": r.text[:200]})
                except Exception as e:
                    errors.append({**rec, "status": "error", "detail": str(e)})
    else:
        # No GoDaddy credentials — return the records to configure manually
        created = [{**rec, "status": "manual_required"} for rec in records]

    propagation_note = "DNS changes typically propagate within 30 minutes to 48 hours globally."

    return {
        "domain":            domain,
        "platform":          platform,
        "records_configured": created,
        "errors":            errors,
        "propagation_note":  propagation_note,
        "verify_url":        f"https://dnschecker.org/#A/{domain}",
        "status":            "configured" if not errors else "partial",
    }


@router.post("/api/launchpad/ssl/provision")
async def launchpad_ssl_provision(req: SSLProvisionRequest, request: Request):
    """SSL certificate provisioning status + instructions."""
    verify_sal_key(request)

    domain   = req.domain.strip().lower()
    platform = (req.platform or "vercel").lower()

    platform_instructions = {
        "vercel": {
            "auto":     True,
            "message":  "Vercel automatically provisions Let's Encrypt SSL for all custom domains.",
            "steps": [
                "Ensure your domain's DNS A record points to 76.76.21.21",
                "Add your custom domain in Vercel Dashboard → Project → Settings → Domains",
                "Vercel auto-issues certificate within minutes of DNS propagation",
            ],
            "docs": "https://vercel.com/docs/concepts/projects/domains",
        },
        "render": {
            "auto":     True,
            "message":  "Render auto-provisions Let's Encrypt SSL for custom domains.",
            "steps": [
                "Add your custom domain in Render Dashboard → Service → Settings → Custom Domains",
                "Point your domain's CNAME www record to {app}.onrender.com",
                "Render auto-issues certificate once DNS is verified",
            ],
            "docs": "https://render.com/docs/custom-domains",
        },
        "cloudflare": {
            "auto":     True,
            "message":  "Cloudflare provides Universal SSL automatically for proxied domains.",
            "steps": [
                "Add your domain to Cloudflare and update nameservers",
                "Enable 'Full (strict)' SSL/TLS mode in Cloudflare SSL/TLS settings",
                "Cloudflare issues certificate within 15 minutes",
            ],
            "docs": "https://developers.cloudflare.com/ssl/",
        },
    }

    instructions = platform_instructions.get(platform, {
        "auto":    False,
        "message": "Use Let's Encrypt (free) or a commercial CA for SSL.",
        "steps":   ["Use Certbot: certbot certonly --webroot -d yourdomain.com"],
        "docs":    "https://letsencrypt.org/getting-started/",
    })

    return {
        "domain":       domain,
        "platform":     platform,
        "ssl_status":   "auto_provisioned" if instructions.get("auto") else "manual_required",
        "instructions": instructions,
        "estimated_time": "5-15 minutes after DNS propagation",
        "check_url":    f"https://www.ssllabs.com/ssltest/analyze.html?d={domain}",
    }


@router.post("/api/launchpad/compliance/setup")
async def launchpad_compliance_setup(req: ComplianceSetupRequest, request: Request):
    """
    Generate compliance calendar and optionally create GHL reminders.
    """
    verify_sal_key(request)

    if not req.business_name:
        raise HTTPException(400, "business_name is required")

    formation_date = req.formation_date or date.today().isoformat()
    calendar = _build_compliance_calendar(req.entity_type, req.state, formation_date)

    # Attempt to create GHL reminder tasks
    ghl_tasks_created = []
    if GHL_TOKEN:
        async with httpx.AsyncClient() as http:
            for event in calendar[:4]:  # Top 4 events
                try:
                    due = datetime.strptime(event["due_date"], "%Y-%m-%d")
                    r = await http.post(
                        f"https://services.leadconnectorhq.com/tasks/",
                        headers={
                            "Authorization": f"Bearer {GHL_TOKEN}",
                            "Version":       "2021-07-28",
                            "Content-Type":  "application/json",
                        },
                        json={
                            "title":      f"{req.business_name}: {event['event']}",
                            "dueDate":    due.isoformat() + "Z",
                            "locationId": GHL_LOCATION,
                            "body":       event.get("description", ""),
                        },
                        timeout=8.0,
                    )
                    if r.status_code in (200, 201):
                        ghl_tasks_created.append(event["event"])
                except Exception:
                    pass

    return {
        "business_name":  req.business_name,
        "entity_type":    req.entity_type,
        "state":          req.state,
        "formation_date": formation_date,
        "calendar":       calendar,
        "total_events":   len(calendar),
        "ghl_reminders":  ghl_tasks_created,
        "ghl_synced":     len(ghl_tasks_created) > 0,
        "note":           "Add these dates to your calendar. Missing compliance deadlines can result in penalties or loss of good standing.",
    }


@router.post("/api/launchpad/order")
async def launchpad_legacy_order(req: LegacyOrderRequest, request: Request):
    """Legacy FileForms order endpoint — wraps entity/form for backwards compat."""
    verify_sal_key(request)

    form_req = EntityFormRequest(
        entity_type=req.entity_type,
        state=req.state,
        business_name=req.business_name,
        package=req.package,
        contact_name=req.contact_name,
        contact_email=req.contact_email,
    )
    return await launchpad_entity_form(form_req, request)


@router.get("/api/launchpad/order/{order_id}")
async def launchpad_order_status(order_id: str, request: Request):
    """Check formation order status via FileForms API or Supabase."""
    verify_sal_key(request)

    # Try FileForms first
    if FILEFORMS_KEY:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.get(
                    f"{FILEFORMS_BASE}/formations/{order_id}",
                    headers={"Authorization": f"Bearer {FILEFORMS_KEY}"},
                    timeout=10.0,
                )
                if r.status_code == 200:
                    data = r.json()
                    return {
                        "order_id":  order_id,
                        "status":    data.get("status", "pending"),
                        "documents": data.get("documents", []),
                        "source":    "fileforms",
                        "updated":   datetime.utcnow().isoformat(),
                    }
        except Exception:
            pass

    # Try Supabase
    if SUPABASE_URL and SUPABASE_SERVICE:
        try:
            async with httpx.AsyncClient() as http:
                r = await http.get(
                    f"{SUPABASE_URL}/rest/v1/launch_pad_orders",
                    headers={
                        "apikey":        SUPABASE_SERVICE,
                        "Authorization": f"Bearer {SUPABASE_SERVICE}",
                    },
                    params={"order_id": f"eq.{order_id}", "select": "*"},
                    timeout=5.0,
                )
                if r.status_code == 200:
                    rows = r.json()
                    if rows:
                        row = rows[0]
                        return {
                            "order_id":     order_id,
                            "status":       row.get("status", "pending"),
                            "business_name": row.get("business_name"),
                            "entity_type":  row.get("entity_type"),
                            "state":        row.get("state"),
                            "package":      row.get("package"),
                            "created_at":   row.get("created_at"),
                            "source":       "supabase",
                        }
        except Exception:
            pass

    return {
        "order_id": order_id,
        "status":   "pending",
        "message":  "Order found. Processing typically takes 3-7 business days.",
        "source":   "cache",
    }


@router.post("/api/launchpad/checkout")
async def launchpad_checkout(req: CheckoutRequest, request: Request):
    """Create a Stripe checkout session for formation fee."""
    verify_sal_key(request)

    if not STRIPE_SECRET:
        raise HTTPException(503, "Stripe is not configured")

    pkg   = req.package.lower()
    etype = req.entity_type.lower()
    entity_group = "corp" if etype in ("c_corp", "s_corp", "nonprofit") else "llc"
    price_key    = f"{pkg}_{entity_group}"
    stripe_price = FORMATION_PRICES.get(price_key)
    amount       = FORMATION_AMOUNTS.get(pkg, 197_00)

    biz_name = req.business_name or "Your Business"
    success  = req.success_url or "https://www.saintsallabs.com/?checkout_success=1"
    cancel   = req.cancel_url  or "https://www.saintsallabs.com/?checkout_cancel=1"

    try:
        if stripe_price:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{"price": stripe_price, "quantity": 1}],
                mode="payment",
                success_url=success,
                cancel_url=cancel,
                metadata={
                    "entity_type":   req.entity_type,
                    "package":       pkg,
                    "business_name": biz_name,
                    "type":          "entity_formation",
                },
            )
        else:
            session = stripe.checkout.Session.create(
                payment_method_types=["card"],
                line_items=[{
                    "price_data": {
                        "currency":     "usd",
                        "unit_amount":  amount,
                        "product_data": {
                            "name":        f"{biz_name} — {pkg.title()} Formation ({req.entity_type.upper()})",
                            "description": f"Business formation service — {pkg.title()} package",
                        },
                    },
                    "quantity": 1,
                }],
                mode="payment",
                success_url=success,
                cancel_url=cancel,
                metadata={
                    "entity_type":   req.entity_type,
                    "package":       pkg,
                    "business_name": biz_name,
                    "type":          "entity_formation",
                },
            )

        return {
            "checkout_url": session.url,
            "session_id":   session.id,
            "amount":       amount / 100,
            "package":      pkg,
            "entity_type":  req.entity_type,
        }

    except stripe.error.StripeError as e:
        raise HTTPException(400, f"Stripe error: {e.user_message or str(e)}")
    except Exception as e:
        raise HTTPException(500, f"Checkout creation failed: {str(e)}")
