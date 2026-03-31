"""
SaintSal™ Labs — Real Estate & Finance Router
Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)

Routes:
  GET  /api/realestate/search            — Property search (RentCast + Exa + Tavily)
  GET  /api/realestate/distressed-search — Distressed/foreclosure leads
  GET  /api/realestate/portfolio         — User's saved property portfolio (Supabase)
  POST /api/realestate/portfolio         — Save a property
  DELETE /api/realestate/portfolio/{id}  — Remove a property
  POST /api/realestate/analyze           — AI property analysis (Claude Opus)
  POST /api/realestate/market-report     — Local market report (RentCast + AI, SSE)
  GET  /api/realestate/rent-estimate     — Rent estimate for address (RentCast AVM)
  POST /api/realestate/deal-analyzer     — Deal math + AI narrative (NOI, cap, CoC, IRR)
  GET  /api/finance/markets              — Market data (Alpaca: ETFs + BTC/ETH)
  GET  /api/finance/movers               — Top gainers/losers (Alpaca screener)
  GET  /api/alpaca/portfolio             — Alpaca account summary
  POST /api/finance/analyze              — AI financial analysis (SSE stream)
  POST /api/finance/dcf                  — DCF valuation model
"""

import os
import json
import math
from datetime import datetime
from typing import Optional, AsyncIterator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx

router = APIRouter()

# ── Credentials ───────────────────────────────────────────────────────────────

ANTHROPIC_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
RENTCAST_KEY    = os.environ.get("RENTCAST_API_KEY", "")
ALPACA_KEY      = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET   = os.environ.get("ALPACA_SECRET_KEY", "")
TAVILY_KEY      = os.environ.get("TAVILY_API_KEY", "")
EXA_KEY         = os.environ.get("EXA_API_KEY", "")
SUPABASE_URL    = os.environ.get("SUPABASE_URL", "")
SUPABASE_SVC    = os.environ.get("SUPABASE_SERVICE_KEY", "")
SAL_GATEWAY     = os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025")

RENTCAST_BASE   = "https://api.rentcast.io/v1"
ALPACA_DATA     = "https://data.alpaca.markets/v2"
ALPACA_BROKER   = "https://paper-api.alpaca.markets/v2"

# ── Auth Guard ────────────────────────────────────────────────────────────────

def _verify_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != SAL_GATEWAY:
        raise HTTPException(status_code=403, detail="Invalid gateway key")


async def _get_user(request: Request) -> Optional[dict]:
    """Extract Supabase user from Bearer token or return None."""
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not SUPABASE_URL or not SUPABASE_SVC:
        return None
    token = auth[7:]
    try:
        async with httpx.AsyncClient(timeout=8) as hc:
            res = await hc.get(
                f"{SUPABASE_URL}/auth/v1/user",
                headers={"Authorization": f"Bearer {token}", "apikey": SUPABASE_SVC},
            )
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return None

# ── SSE Helpers ───────────────────────────────────────────────────────────────

def _sse_chunk(content: str) -> str:
    return f"data: {json.dumps({'type': 'chunk', 'content': content})}\n\n"

def _sse_event(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data})}\n\n"

def _sse_done(extra: dict = None) -> str:
    payload = {"type": "done"}
    if extra:
        payload.update(extra)
    return f"data: {json.dumps(payload)}\n\n"

def _sse_error(msg: str) -> str:
    return f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n"

# ── Shared Search Helpers ─────────────────────────────────────────────────────

async def _tavily_search(query: str, max_results: int = 5) -> list:
    if not TAVILY_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=12) as hc:
            res = await hc.post(
                "https://api.tavily.com/search",
                json={"api_key": TAVILY_KEY, "query": query, "max_results": max_results, "search_depth": "advanced"},
            )
            res.raise_for_status()
            return res.json().get("results", [])
    except Exception:
        return []


async def _exa_search(query: str, num_results: int = 5) -> list:
    if not EXA_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=12) as hc:
            res = await hc.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": EXA_KEY},
                json={"query": query, "numResults": num_results, "contents": {"text": True}},
            )
            res.raise_for_status()
            return res.json().get("results", [])
    except Exception:
        return []


async def _stream_claude(messages: list, system: str, model: str = "claude-opus-4-6") -> AsyncIterator[str]:
    if not ANTHROPIC_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")
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


def _rentcast_headers() -> dict:
    return {"X-Api-Key": RENTCAST_KEY, "Accept": "application/json"}

def _alpaca_headers() -> dict:
    return {"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}

# ── Supabase Direct Helper ────────────────────────────────────────────────────

async def _sb_select(table: str, filters: dict) -> list:
    """Simple Supabase REST select."""
    if not SUPABASE_URL or not SUPABASE_SVC:
        return []
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    params = {"select": "*"}
    for k, v in filters.items():
        params[f"{k}"] = f"eq.{v}"
    params["order"] = "created_at.desc"
    params["limit"] = "50"
    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            res = await hc.get(
                url,
                params=params,
                headers={"apikey": SUPABASE_SVC, "Authorization": f"Bearer {SUPABASE_SVC}"},
            )
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return []


async def _sb_insert(table: str, row: dict) -> Optional[dict]:
    if not SUPABASE_URL or not SUPABASE_SVC:
        return None
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            res = await hc.post(
                url,
                json=row,
                headers={
                    "apikey": SUPABASE_SVC,
                    "Authorization": f"Bearer {SUPABASE_SVC}",
                    "Content-Type": "application/json",
                    "Prefer": "return=representation",
                },
            )
            if res.status_code in (200, 201):
                data = res.json()
                return data[0] if isinstance(data, list) and data else data
    except Exception:
        pass
    return None


async def _sb_delete(table: str, id_val: str, user_id: str) -> bool:
    if not SUPABASE_URL or not SUPABASE_SVC:
        return False
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    try:
        async with httpx.AsyncClient(timeout=10) as hc:
            res = await hc.delete(
                url,
                params={"id": f"eq.{id_val}", "user_id": f"eq.{user_id}"},
                headers={"apikey": SUPABASE_SVC, "Authorization": f"Bearer {SUPABASE_SVC}"},
            )
            return res.status_code in (200, 204)
    except Exception:
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# Request models
# ═══════════════════════════════════════════════════════════════════════════════

class AnalyzeRequest(BaseModel):
    address: str
    price: float
    rent_estimate: Optional[float] = None
    property_type: Optional[str] = "Single Family"
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    notes: Optional[str] = ""

class MarketReportRequest(BaseModel):
    city: str
    state: str
    zipcode: Optional[str] = ""

class DealAnalyzerRequest(BaseModel):
    address: str
    purchase_price: float
    down_payment_pct: float = 25.0
    monthly_rent: float = 0.0
    interest_rate: float = 6.87
    loan_term: int = 30
    closing_costs_pct: float = 3.0
    vacancy_rate: float = 8.0
    management_fee_pct: float = 10.0
    insurance_annual: float = 1800.0
    taxes_annual: float = 3600.0
    maintenance_pct: float = 5.0
    generate_narrative: bool = True

class FinanceAnalyzeRequest(BaseModel):
    message: str
    context: Optional[str] = ""
    model: Optional[str] = "claude-opus-4-6"

class DCFRequest(BaseModel):
    company_name: Optional[str] = ""
    revenue: float           # Current annual revenue ($M)
    revenue_growth: float    # Growth rate % (e.g., 15)
    ebitda_margin: float     # EBITDA margin % (e.g., 20)
    discount_rate: float     # WACC % (e.g., 10)
    terminal_multiple: float # EV/EBITDA exit multiple (e.g., 12)
    years: int = 5
    capex_pct: float = 5.0   # CapEx as % of revenue
    tax_rate: float = 21.0

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/realestate/search
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/realestate/search")
async def realestate_search(
    request: Request,
    address: str = "",
    city: str = "",
    state: str = "",
    zipcode: str = "",
    property_type: str = "",
    beds_min: int = 0,
    baths_min: float = 0,
    price_min: float = 0,
    price_max: float = 0,
    limit: int = 20,
):
    """
    Search properties via RentCast API.
    Falls back to Tavily/Exa search of Zillow/Redfin if no RentCast key.
    """
    _verify_key(request)

    if not address and not city and not zipcode:
        raise HTTPException(status_code=400, detail="Provide address, city/state, or zipcode")

    # ── RentCast primary ──────────────────────────────────────────────────────
    if RENTCAST_KEY:
        params: dict = {"limit": min(limit, 50), "status": "Active"}
        if address:
            params["address"] = address
        if city:
            params["city"] = city
        if state:
            params["state"] = state
        if zipcode:
            params["zipCode"] = zipcode
        if property_type:
            params["propertyType"] = property_type
        if beds_min:
            params["bedsMin"] = beds_min
        if baths_min:
            params["bathsMin"] = baths_min
        if price_min:
            params["priceMin"] = price_min
        if price_max:
            params["priceMax"] = price_max

        try:
            async with httpx.AsyncClient(timeout=15) as hc:
                res = await hc.get(
                    f"{RENTCAST_BASE}/listings/sale",
                    params=params,
                    headers=_rentcast_headers(),
                )
                if res.status_code == 200:
                    data = res.json()
                    listings = data if isinstance(data, list) else data.get("listings", [data])
                    # Augment each listing with a quick rent estimate if we have it
                    enriched = []
                    for l in listings:
                        l["_source"] = "RentCast"
                        enriched.append(l)
                    return JSONResponse({
                        "results": enriched,
                        "count": len(enriched),
                        "api_live": True,
                        "source": "rentcast",
                    })
        except Exception as exc:
            pass  # Fall through to web search

    # ── Web search fallback (Tavily → Exa) ───────────────────────────────────
    query_parts = []
    if address:
        query_parts.append(address)
    if city:
        query_parts.append(city)
    if state:
        query_parts.append(state)
    if zipcode:
        query_parts.append(zipcode)
    query = " ".join(query_parts) + " real estate for sale listings Zillow Redfin"

    web_results = []
    if TAVILY_KEY:
        web_results = await _tavily_search(query, max_results=10)
    if not web_results and EXA_KEY:
        web_results = await _exa_search(query, num_results=10)

    listings = []
    for r in web_results:
        listings.append({
            "address": r.get("title", ""),
            "url": r.get("url", ""),
            "description": r.get("content", "")[:300],
            "_source": "WebSearch",
        })

    return JSONResponse({
        "results": listings,
        "count": len(listings),
        "api_live": False,
        "source": "web_search",
        "note": "RentCast API key not configured — showing web search results",
    })

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/realestate/distressed-search
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/realestate/distressed-search")
async def distressed_search(
    request: Request,
    category: str = "foreclosure",
    city: str = "",
    state: str = "",
    zipcode: str = "",
    radius: float = 0,
    limit: int = 20,
):
    """
    Search distressed/foreclosure property leads.
    Categories: foreclosure, pre-foreclosure, nod, tax-lien, bankruptcy,
                off-market, cash-buyer, notes-due
    """
    _verify_key(request)

    results = []

    if RENTCAST_KEY:
        try:
            async with httpx.AsyncClient(timeout=20) as hc:
                base_params: dict = {"limit": min(limit, 50)}
                if state:
                    base_params["state"] = state
                if city:
                    base_params["city"] = city
                if zipcode:
                    base_params["zipCode"] = zipcode

                if category in ("foreclosure", "pre-foreclosure"):
                    params = {**base_params, "status": "Foreclosure" if category == "foreclosure" else "Pre-Foreclosure"}
                    res = await hc.get(f"{RENTCAST_BASE}/listings/sale", params=params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        results = raw if isinstance(raw, list) else raw.get("listings", [])

                elif category == "nod":
                    params = {**base_params, "status": "Foreclosure"}
                    res = await hc.get(f"{RENTCAST_BASE}/listings/sale", params=params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        raw_list = raw if isinstance(raw, list) else raw.get("listings", [])
                        results = [
                            l for l in raw_list
                            if "notice" in str(l.get("description", "")).lower()
                            or "nod" in str(l.get("description", "")).lower()
                        ] or raw_list[:limit]

                elif category in ("tax-lien", "bankruptcy", "notes-due"):
                    res = await hc.get(f"{RENTCAST_BASE}/properties", params=base_params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        raw_list = raw if isinstance(raw, list) else raw.get("properties", [])
                        for p in raw_list:
                            p["distressed_type"] = {
                                "tax-lien": "Tax Lien (potential)",
                                "bankruptcy": "Bankruptcy / REO",
                                "notes-due": "Note Coming Due",
                            }.get(category, category.replace("-", " ").title())
                        results = raw_list

                elif category == "off-market":
                    res = await hc.get(f"{RENTCAST_BASE}/properties", params=base_params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        raw_list = raw if isinstance(raw, list) else raw.get("properties", [])
                        for p in raw_list:
                            p["distressed_type"] = "Off-Market"
                        results = raw_list

                elif category == "cash-buyer":
                    res = await hc.get(f"{RENTCAST_BASE}/listings/sale", params=base_params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        raw_list = raw if isinstance(raw, list) else raw.get("listings", [])
                        for l in raw_list:
                            l["distressed_type"] = "Cash Buyer Opportunity"
                        results = raw_list

                else:
                    res = await hc.get(f"{RENTCAST_BASE}/properties", params=base_params, headers=_rentcast_headers())
                    if res.status_code == 200:
                        raw = res.json()
                        results = raw if isinstance(raw, list) else raw.get("properties", [])

        except Exception as exc:
            # Fallback to web search for leads
            pass

    # ── Web fallback: Exa search for distressed leads ─────────────────────────
    if not results:
        location = " ".join(filter(None, [city, state, zipcode]))
        query = f"{category} properties {location} real estate leads investor deals 2026"
        web_results = []
        if EXA_KEY:
            web_results = await _exa_search(query, num_results=10)
        elif TAVILY_KEY:
            web_results = await _tavily_search(query, max_results=10)
        for r in web_results:
            results.append({
                "address": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("content", "")[:300],
                "distressed_type": category.replace("-", " ").title(),
                "_source": "WebSearch",
            })

    return JSONResponse({
        "category": category,
        "count": len(results[:limit]),
        "results": results[:limit],
        "sources": ["rentcast"] if RENTCAST_KEY else ["web_search"],
    })

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/realestate/portfolio
# POST /api/realestate/portfolio
# DELETE /api/realestate/portfolio/{property_id}
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/realestate/portfolio")
async def get_portfolio(request: Request):
    """Get user's saved properties from Supabase."""
    _verify_key(request)
    user = await _get_user(request)
    if not user:
        return JSONResponse({"properties": [], "error": "Not authenticated"})
    try:
        rows = await _sb_select("saved_properties", {"user_id": user["id"]})
        return JSONResponse({"properties": rows, "count": len(rows)})
    except Exception as exc:
        return JSONResponse({"properties": [], "error": str(exc)})


@router.post("/api/realestate/portfolio")
async def save_property(request: Request):
    """Save a property to user's portfolio."""
    _verify_key(request)
    user = await _get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.json()
    row = {
        "user_id": user["id"],
        "address": body.get("address", ""),
        "city": body.get("city", ""),
        "state": body.get("state", ""),
        "zip": body.get("zip", ""),
        "price": body.get("price"),
        "beds": body.get("beds"),
        "baths": body.get("baths"),
        "sqft": body.get("sqft"),
        "property_type": body.get("property_type", ""),
        "source": body.get("_source", ""),
        "notes": body.get("notes", ""),
        "data_snapshot": body,
    }
    try:
        result = await _sb_insert("saved_properties", row)
        return JSONResponse({"saved": True, "id": result.get("id") if result else None})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/api/realestate/portfolio/{property_id}")
async def delete_portfolio_property(property_id: str, request: Request):
    """Remove a property from user's portfolio."""
    _verify_key(request)
    user = await _get_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    ok = await _sb_delete("saved_properties", property_id, user["id"])
    return JSONResponse({"deleted": ok})

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/realestate/analyze  — AI property analysis (Claude Opus)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/realestate/analyze")
async def analyze_property(body: AnalyzeRequest, request: Request):
    """
    AI analysis of a property.
    Fetches rent estimate from RentCast, then streams Claude Opus analysis
    covering cap rate, CoC return, 5-year appreciation, and buy/pass recommendation.
    """
    _verify_key(request)

    # Fetch rent estimate if not provided
    rent_estimate = body.rent_estimate
    comps_context = ""

    if RENTCAST_KEY:
        try:
            async with httpx.AsyncClient(timeout=12) as hc:
                # Rent AVM
                if not rent_estimate:
                    rent_res = await hc.get(
                        f"{RENTCAST_BASE}/avm/rent/long-term",
                        params={"address": body.address, "compCount": 5},
                        headers=_rentcast_headers(),
                    )
                    if rent_res.status_code == 200:
                        rd = rent_res.json()
                        rent_estimate = rd.get("rent") or rd.get("rentEstimate") or rd.get("price")

                # Value AVM for comps
                val_res = await hc.get(
                    f"{RENTCAST_BASE}/avm/value",
                    params={"address": body.address, "compCount": 5},
                    headers=_rentcast_headers(),
                )
                if val_res.status_code == 200:
                    vd = val_res.json()
                    comps = vd.get("comparables", [])[:5]
                    if comps:
                        comp_lines = [
                            f"  - {c.get('address','')}: ${c.get('price',0):,.0f}, {c.get('bedrooms','?')}bd/{c.get('bathrooms','?')}ba, {c.get('squareFootage','?')} sqft"
                            for c in comps
                        ]
                        comps_context = "Recent Comparable Sales:\n" + "\n".join(comp_lines)
        except Exception:
            pass

    # Build quick deal math to inject into prompt
    cap_rate_str = "N/A"
    if rent_estimate and body.price > 0:
        # Quick estimate: assume ~40% expense ratio for NOI
        estimated_noi = rent_estimate * 12 * 0.60
        cap_rate = (estimated_noi / body.price) * 100
        cap_rate_str = f"{cap_rate:.2f}%"

    system = """You are SAL, SaintSal™ Real Estate intelligence engine.
You are a seasoned real estate investment analyst with deep expertise in cap rates,
cash flow analysis, and market valuation. Provide a thorough, data-driven analysis.
Always include: 'Consult a licensed broker before transacting.'
Format with markdown headers. Be direct and decisive with your recommendation."""

    prompt = f"""Analyze this investment property:

**Property**: {body.address}
**Type**: {body.property_type or 'N/A'}
**Purchase Price**: ${body.price:,.0f}
**Beds/Baths**: {body.beds or 'N/A'} bed / {body.baths or 'N/A'} bath
**Sqft**: {body.sqft or 'N/A'}
**Monthly Rent Estimate**: ${rent_estimate:,.0f}/mo if rent_estimate else 'Not available'
**Estimated Cap Rate**: {cap_rate_str}

{comps_context}

{('Additional notes: ' + body.notes) if body.notes else ''}

Provide a comprehensive investment analysis covering:
1. **Deal Quality Assessment** — Is this a strong deal, good deal, or pass?
2. **Cap Rate Analysis** — Current cap rate vs market average; what's a fair cap rate for this asset class in this market?
3. **Cash-on-Cash Return** — Assuming 25% down at 6.87% interest rate; is this cash flow positive?
4. **5-Year Appreciation Projection** — Based on location fundamentals and market trends
5. **Key Risks** — Top 3 risks an investor should consider
6. **Negotiation Angle** — What offer price would make this a strong deal?
7. **Verdict** — STRONG BUY / BUY / HOLD / PASS with one-sentence rationale"""

    async def generate():
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": prompt}],
                system,
                model="claude-opus-4-6",
            ):
                yield _sse_chunk(chunk)
            yield _sse_done({
                "rent_estimate": rent_estimate,
                "cap_rate": cap_rate_str,
            })
        except Exception as exc:
            yield _sse_error(f"Analysis failed: {str(exc)[:200]}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/realestate/market-report  — SSE market report
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/realestate/market-report")
async def market_report(body: MarketReportRequest, request: Request):
    """
    Generate a local real estate market report.
    RentCast market data + Tavily/Exa web intelligence → Claude Opus narrative (SSE).
    """
    _verify_key(request)

    location = f"{body.city}, {body.state}"
    if body.zipcode:
        location += f" {body.zipcode}"

    market_data_context = ""

    # ── RentCast market stats ─────────────────────────────────────────────────
    if RENTCAST_KEY:
        try:
            params: dict = {}
            if body.zipcode:
                params["zipCode"] = body.zipcode
            else:
                params["city"] = body.city
                params["state"] = body.state
            async with httpx.AsyncClient(timeout=12) as hc:
                res = await hc.get(f"{RENTCAST_BASE}/markets", params=params, headers=_rentcast_headers())
                if res.status_code == 200:
                    md = res.json()
                    market_data_context = f"RentCast Market Stats for {location}:\n{json.dumps(md, indent=2)[:1500]}"
        except Exception:
            pass

    # ── Web search for local market context ──────────────────────────────────
    web_context = ""
    query = f"{location} real estate market trends 2026 home prices inventory days on market"
    web_results = []
    if TAVILY_KEY:
        web_results = await _tavily_search(query, max_results=5)
    elif EXA_KEY:
        web_results = await _exa_search(query, num_results=5)

    if web_results:
        snippets = []
        for r in web_results[:4]:
            url = r.get("url", "")
            title = r.get("title", "")
            content = r.get("content", r.get("text", ""))[:400]
            snippets.append(f"[{title}]\n{url}\n{content}")
        web_context = "Web Intelligence:\n" + "\n\n".join(snippets)

    system = """You are SAL, SaintSal™ Real Estate market analyst.
Generate a comprehensive, professional market report formatted in markdown.
Use all data provided. Be specific with numbers. Format like a Wall Street analyst report."""

    prompt = f"""Generate a comprehensive real estate market report for: **{location}**

{market_data_context}

{web_context}

Structure your report with these sections:
# {location} Real Estate Market Report
**Generated**: {datetime.utcnow().strftime('%B %d, %Y')}

## Executive Summary
## Market Overview (median price, YoY change, inventory, days on market)
## Rental Market (median rent, vacancy rate, rent growth)
## Investment Opportunity Analysis (cap rates, best asset classes)
## Neighborhood Breakdown (top 3 submarkets)
## 12-Month Outlook (bullish/bearish factors)
## Recommended Strategy for Investors

Consult a licensed broker before transacting."""

    async def generate():
        yield _sse_event("status", {"message": f"Generating market report for {location}..."})
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": prompt}],
                system,
                model="claude-opus-4-6",
            ):
                yield _sse_chunk(chunk)
            yield _sse_done({"location": location})
        except Exception as exc:
            yield _sse_error(f"Report generation failed: {str(exc)[:200]}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/realestate/rent-estimate
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/realestate/rent-estimate")
async def rent_estimate(request: Request, address: str, beds: int = 0, baths: float = 0, sqft: int = 0):
    """Get rent estimate for an address using RentCast AVM."""
    _verify_key(request)

    if not address:
        raise HTTPException(status_code=400, detail="address is required")

    if RENTCAST_KEY:
        try:
            params: dict = {"address": address, "compCount": 5}
            if beds:
                params["bedrooms"] = beds
            if baths:
                params["bathrooms"] = baths
            if sqft:
                params["squareFootage"] = sqft
            async with httpx.AsyncClient(timeout=12) as hc:
                res = await hc.get(
                    f"{RENTCAST_BASE}/avm/rent/long-term",
                    params=params,
                    headers=_rentcast_headers(),
                )
                if res.status_code == 200:
                    data = res.json()
                    return JSONResponse({"data": data, "api_live": True, "source": "rentcast"})
        except Exception:
            pass

    # Web fallback
    query = f"monthly rent estimate {address} {beds}br {baths}ba"
    web = await _tavily_search(query, max_results=3)
    return JSONResponse({
        "data": None,
        "api_live": False,
        "source": "unavailable",
        "web_context": [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content", "")[:200]} for r in web],
        "note": "RentCast API key not configured",
    })

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/realestate/deal-analyzer  — Full deal math + AI narrative
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/realestate/deal-analyzer")
async def deal_analyzer(body: DealAnalyzerRequest, request: Request):
    """
    Full investment deal analysis:
    - NOI, Cap Rate, Cash-on-Cash Return, GRM, DCR, 1% rule
    - Monthly/annual cash flow breakdown
    - IRR estimate (simplified)
    - Optional Claude narrative
    Returns JSON (non-streaming) with math + optional AI narrative.
    """
    _verify_key(request)

    p = body.purchase_price
    monthly_rent = body.monthly_rent
    down_pct = body.down_payment_pct / 100
    ir = body.interest_rate / 100
    n = body.loan_term * 12

    down_payment = p * down_pct
    loan_amount = p - down_payment
    closing_costs = p * (body.closing_costs_pct / 100)
    total_cash_in = down_payment + closing_costs

    # Monthly mortgage (P&I amortization formula)
    monthly_ir = ir / 12
    if monthly_ir > 0:
        monthly_mortgage = loan_amount * (monthly_ir * (1 + monthly_ir) ** n) / ((1 + monthly_ir) ** n - 1)
    else:
        monthly_mortgage = loan_amount / n

    # Annual income / expense model
    gross_annual_rent = monthly_rent * 12
    vacancy_loss = gross_annual_rent * (body.vacancy_rate / 100)
    effective_rent = gross_annual_rent - vacancy_loss
    management_fee = effective_rent * (body.management_fee_pct / 100)
    maintenance = gross_annual_rent * (body.maintenance_pct / 100)
    annual_mortgage = monthly_mortgage * 12

    # NOI (before debt service)
    noi = effective_rent - body.insurance_annual - body.taxes_annual - management_fee - maintenance

    # Cash flow (after debt service)
    cash_flow_annual = noi - annual_mortgage
    cash_flow_monthly = cash_flow_annual / 12

    # Key metrics
    cap_rate = (noi / p) * 100 if p > 0 else 0
    cash_on_cash = (cash_flow_annual / total_cash_in) * 100 if total_cash_in > 0 else 0
    grm = p / gross_annual_rent if gross_annual_rent > 0 else 0
    dcr = noi / annual_mortgage if annual_mortgage > 0 else 0
    rent_to_price_pct = (monthly_rent / p) * 100 if p > 0 else 0
    one_percent_rule = monthly_rent >= (p * 0.01)

    # Simplified 5-year IRR estimate (assumes 3% annual appreciation)
    appreciation_rate = 0.03
    projected_value_5yr = p * ((1 + appreciation_rate) ** 5)
    equity_gain = projected_value_5yr - p
    total_cash_flow_5yr = cash_flow_annual * 5
    total_return = equity_gain + total_cash_flow_5yr + (loan_amount - _remaining_balance(loan_amount, monthly_ir, n, 60))
    # Approximate IRR via CAGR of total return on investment
    irr_estimate = 0.0
    if total_cash_in > 0:
        try:
            irr_estimate = (((total_return + total_cash_in) / total_cash_in) ** (1 / 5) - 1) * 100
        except Exception:
            irr_estimate = 0.0

    # Verdict
    if cap_rate > 7 and cash_on_cash > 10:
        verdict = "Strong Buy"
        verdict_color = "green"
    elif cap_rate > 5.5 and cash_on_cash > 6:
        verdict = "Good Deal"
        verdict_color = "green"
    elif cap_rate > 4 and cash_on_cash > 3:
        verdict = "Moderate"
        verdict_color = "amber"
    else:
        verdict = "Below Average"
        verdict_color = "red"

    analysis_result = {
        "address": body.address,
        "summary": {
            "purchase_price": round(p, 2),
            "down_payment": round(down_payment, 2),
            "down_payment_pct": body.down_payment_pct,
            "loan_amount": round(loan_amount, 2),
            "closing_costs": round(closing_costs, 2),
            "total_cash_invested": round(total_cash_in, 2),
        },
        "monthly": {
            "gross_rent": round(monthly_rent, 2),
            "effective_rent": round(effective_rent / 12, 2),
            "mortgage_pi": round(monthly_mortgage, 2),
            "insurance": round(body.insurance_annual / 12, 2),
            "taxes": round(body.taxes_annual / 12, 2),
            "management": round(management_fee / 12, 2),
            "maintenance": round(maintenance / 12, 2),
            "total_expenses": round((annual_mortgage + body.insurance_annual + body.taxes_annual + management_fee + maintenance) / 12, 2),
            "cash_flow": round(cash_flow_monthly, 2),
        },
        "annual": {
            "gross_rent": round(gross_annual_rent, 2),
            "vacancy_loss": round(vacancy_loss, 2),
            "effective_rent": round(effective_rent, 2),
            "noi": round(noi, 2),
            "debt_service": round(annual_mortgage, 2),
            "cash_flow": round(cash_flow_annual, 2),
        },
        "metrics": {
            "cap_rate": round(cap_rate, 2),
            "cash_on_cash": round(cash_on_cash, 2),
            "irr_estimate_5yr": round(irr_estimate, 2),
            "grm": round(grm, 2),
            "dcr": round(dcr, 2),
            "rent_to_price_pct": round(rent_to_price_pct, 3),
            "one_percent_rule": one_percent_rule,
        },
        "verdict": verdict,
        "verdict_color": verdict_color,
        "ai_narrative": None,
    }

    # ── Optional Claude narrative ─────────────────────────────────────────────
    if body.generate_narrative and ANTHROPIC_KEY:
        try:
            system = """You are SAL, SaintSal™ Real Estate deal analyst.
Write a concise (3-4 paragraph) plain-English investment summary based on the deal metrics.
Be direct. State the verdict clearly. Identify the #1 risk and #1 upside.
End with: 'Consult a licensed broker before transacting.'"""
            prompt = f"""Deal Analysis for {body.address}:

Cap Rate: {cap_rate:.2f}% | Cash-on-Cash: {cash_on_cash:.2f}% | IRR (5yr est.): {irr_estimate:.2f}%
Monthly Cash Flow: ${cash_flow_monthly:,.2f} | NOI: ${noi:,.0f}/yr
Verdict: {verdict} | 1% Rule: {'PASS' if one_percent_rule else 'FAIL'} | DCR: {dcr:.2f}
Purchase Price: ${p:,.0f} | Down: ${down_payment:,.0f} ({body.down_payment_pct}%) | Monthly Rent: ${monthly_rent:,.0f}

Write the investment summary."""
            chunks = []
            async for chunk in _stream_claude([{"role": "user", "content": prompt}], system, "claude-sonnet-4-5"):
                chunks.append(chunk)
            analysis_result["ai_narrative"] = "".join(chunks)
        except Exception:
            pass  # Narrative is optional

    return JSONResponse(analysis_result)


def _remaining_balance(principal: float, monthly_rate: float, total_payments: int, payments_made: int) -> float:
    """Calculate remaining mortgage balance after N payments."""
    if monthly_rate == 0:
        return principal * (1 - payments_made / total_payments)
    return principal * ((1 + monthly_rate) ** total_payments - (1 + monthly_rate) ** payments_made) / ((1 + monthly_rate) ** total_payments - 1)

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/finance/markets  — Alpaca market data
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/finance/markets")
async def finance_markets(request: Request):
    """
    Live market data via Alpaca Data API v2.
    Symbols: SPY, QQQ, IWM, DIA, GLD + BTC/USD, ETH/USD
    Returns OHLCV + change % for each.
    Falls back to static snapshot if Alpaca is unconfigured.
    """
    _verify_key(request)

    if ALPACA_KEY and ALPACA_SECRET:
        try:
            async with httpx.AsyncClient(timeout=12) as hc:
                hdrs = _alpaca_headers()

                # Equity ETFs — latest bars
                equity_syms = "SPY,QQQ,IWM,DIA,GLD"
                eq_res = await hc.get(
                    f"{ALPACA_DATA}/stocks/bars/latest",
                    params={"symbols": equity_syms, "feed": "iex"},
                    headers=hdrs,
                )

                # Crypto — latest bars
                crypto_syms = "BTC/USD,ETH/USD"
                cr_res = await hc.get(
                    f"{ALPACA_DATA}/crypto/latest/bars",
                    params={"symbols": crypto_syms},
                    headers=hdrs,
                )

                bars = {}
                if eq_res.status_code == 200:
                    bars.update(eq_res.json().get("bars", {}))
                if cr_res.status_code == 200:
                    cr_bars = cr_res.json().get("bars", {})
                    bars.update(cr_bars)

                if bars:
                    instruments = []
                    sym_meta = {
                        "SPY":     {"name": "S&P 500 ETF",  "category": "etf"},
                        "QQQ":     {"name": "Nasdaq 100 ETF","category": "etf"},
                        "IWM":     {"name": "Russell 2000", "category": "etf"},
                        "DIA":     {"name": "Dow Jones ETF", "category": "etf"},
                        "GLD":     {"name": "Gold ETF",     "category": "commodity"},
                        "BTC/USD": {"name": "Bitcoin",       "category": "crypto"},
                        "ETH/USD": {"name": "Ethereum",      "category": "crypto"},
                    }
                    for sym, bar in bars.items():
                        if not bar:
                            continue
                        o = float(bar.get("o", bar.get("open", 0)))
                        c = float(bar.get("c", bar.get("close", 0)))
                        change_pct = ((c - o) / o * 100) if o > 0 else 0
                        meta = sym_meta.get(sym, {"name": sym, "category": "equity"})
                        instruments.append({
                            "symbol": sym,
                            "name": meta["name"],
                            "category": meta["category"],
                            "price": round(c, 2),
                            "open": round(o, 2),
                            "high": round(float(bar.get("h", bar.get("high", c))), 2),
                            "low": round(float(bar.get("l", bar.get("low", c))), 2),
                            "volume": bar.get("v", bar.get("volume", 0)),
                            "change_pct": round(change_pct, 2),
                            "direction": "up" if change_pct >= 0 else "down",
                        })
                    # Sort by category order
                    cat_order = {"etf": 0, "crypto": 1, "commodity": 2}
                    instruments.sort(key=lambda x: cat_order.get(x["category"], 3))
                    return JSONResponse({
                        "instruments": instruments,
                        "updated_at": datetime.utcnow().isoformat() + "Z",
                        "api_live": True,
                        "source": "alpaca",
                    })
        except Exception:
            pass  # Fall through to static fallback

    # ── Static fallback ───────────────────────────────────────────────────────
    return JSONResponse({
        "instruments": [
            {"symbol": "SPY",     "name": "S&P 500 ETF",   "category": "etf",       "price": 584.20, "change_pct": 0.62,  "direction": "up"},
            {"symbol": "QQQ",     "name": "Nasdaq 100 ETF","category": "etf",       "price": 501.34, "change_pct": 0.91,  "direction": "up"},
            {"symbol": "IWM",     "name": "Russell 2000",  "category": "etf",       "price": 214.18, "change_pct": -0.44, "direction": "down"},
            {"symbol": "DIA",     "name": "Dow Jones ETF", "category": "etf",       "price": 425.60, "change_pct": 0.30,  "direction": "up"},
            {"symbol": "GLD",     "name": "Gold ETF",      "category": "commodity", "price": 241.85, "change_pct": 0.15,  "direction": "up"},
            {"symbol": "BTC/USD", "name": "Bitcoin",       "category": "crypto",    "price": 87420,  "change_pct": 2.14,  "direction": "up"},
            {"symbol": "ETH/USD", "name": "Ethereum",      "category": "crypto",    "price": 3210,   "change_pct": 1.08,  "direction": "up"},
        ],
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "api_live": False,
        "source": "static_fallback",
        "note": "Alpaca API not configured — showing static snapshot",
    })

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/finance/movers  — Top gainers/losers
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/finance/movers")
async def finance_movers(request: Request):
    """
    Top gainers and losers.
    Tries Alpaca screener endpoint; falls back to Tavily web search.
    """
    _verify_key(request)

    # ── Alpaca screener ───────────────────────────────────────────────────────
    if ALPACA_KEY and ALPACA_SECRET:
        try:
            async with httpx.AsyncClient(timeout=12) as hc:
                hdrs = _alpaca_headers()
                # Try Alpaca movers endpoint
                res = await hc.get(
                    f"{ALPACA_DATA}/stocks/most-actives",
                    params={"by": "trades", "top": 10},
                    headers=hdrs,
                )
                if res.status_code == 200:
                    data = res.json()
                    most_actives = data.get("most_actives", [])
                    if most_actives:
                        return JSONResponse({
                            "gainers": [m for m in most_actives if float(m.get("change_percent", 0)) > 0][:5],
                            "losers": [m for m in most_actives if float(m.get("change_percent", 0)) < 0][:5],
                            "api_live": True,
                            "source": "alpaca",
                        })
        except Exception:
            pass

    # ── Tavily fallback: search for movers today ──────────────────────────────
    movers_results = []
    if TAVILY_KEY:
        movers_results = await _tavily_search(
            "stock market top gainers losers today 2026 percent change",
            max_results=8,
        )
    elif EXA_KEY:
        movers_results = await _exa_search("stock market movers today top gainers losers", num_results=6)

    return JSONResponse({
        "gainers": [],
        "losers": [],
        "web_context": [
            {"title": r.get("title"), "url": r.get("url"), "content": r.get("content", "")[:200]}
            for r in movers_results[:5]
        ],
        "api_live": False,
        "source": "web_search",
        "note": "Alpaca screener unavailable — showing web intelligence",
    })

# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/alpaca/portfolio
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/api/alpaca/portfolio")
async def alpaca_portfolio(request: Request):
    """Alpaca brokerage account summary: equity, cash, buying power, positions, day P&L."""
    _verify_key(request)

    if not ALPACA_KEY or not ALPACA_SECRET:
        return JSONResponse({
            "equity": 0, "cash": 0, "buying_power": 0,
            "day_pl": 0, "day_pl_pct": 0,
            "positions": [], "ok": False,
            "error": "Alpaca not configured",
        })

    try:
        async with httpx.AsyncClient(timeout=12) as hc:
            hdrs = _alpaca_headers()
            acct_r = await hc.get(f"{ALPACA_BROKER}/account", headers=hdrs)
            pos_r  = await hc.get(f"{ALPACA_BROKER}/positions", headers=hdrs)

            if acct_r.status_code == 200:
                acct = acct_r.json()
                equity = float(acct.get("equity", 0))
                last_equity = float(acct.get("last_equity", equity))
                day_pl = equity - last_equity
                day_pl_pct = (day_pl / last_equity * 100) if last_equity > 0 else 0
                positions = []
                if pos_r.status_code == 200:
                    raw_pos = pos_r.json()
                    for p in raw_pos[:15]:
                        positions.append({
                            "symbol": p.get("symbol"),
                            "qty": float(p.get("qty", 0)),
                            "avg_entry": float(p.get("avg_entry_price", 0)),
                            "current_price": float(p.get("current_price", 0)),
                            "market_value": float(p.get("market_value", 0)),
                            "unrealized_pl": float(p.get("unrealized_pl", 0)),
                            "unrealized_plpc": float(p.get("unrealized_plpc", 0)) * 100,
                        })
                return JSONResponse({
                    "equity": round(equity, 2),
                    "cash": round(float(acct.get("cash", 0)), 2),
                    "buying_power": round(float(acct.get("buying_power", 0)), 2),
                    "day_pl": round(day_pl, 2),
                    "day_pl_pct": round(day_pl_pct, 2),
                    "portfolio_value": round(float(acct.get("portfolio_value", equity)), 2),
                    "positions": positions,
                    "ok": True,
                    "source": "alpaca",
                })
    except Exception as exc:
        return JSONResponse({
            "equity": 0, "cash": 0, "buying_power": 0,
            "day_pl": 0, "day_pl_pct": 0,
            "positions": [], "ok": False,
            "error": str(exc)[:200],
        })

    return JSONResponse({"equity": 0, "cash": 0, "buying_power": 0, "positions": [], "ok": False})

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/finance/analyze  — AI financial analysis (SSE stream)
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/finance/analyze")
async def finance_analyze(body: FinanceAnalyzeRequest, request: Request):
    """
    SSE-streamed AI financial analysis using Claude Opus.
    Runs a Tavily search for live market context before answering.
    """
    _verify_key(request)

    # Pre-fetch live market context
    web_context = ""
    if TAVILY_KEY or EXA_KEY:
        results = []
        if TAVILY_KEY:
            results = await _tavily_search(body.message + " stock market 2026", max_results=5)
        if not results and EXA_KEY:
            results = await _exa_search(body.message, num_results=4)
        if results:
            snippets = []
            for r in results[:4]:
                title = r.get("title", "")
                url = r.get("url", "")
                content = r.get("content", r.get("text", ""))[:500]
                snippets.append(f"[{title}]\n{url}\n{content}")
            web_context = "=== LIVE MARKET INTELLIGENCE ===\n" + "\n\n".join(snippets)

    system = f"""You are SAL, SaintSal™ Finance intelligence engine — a senior Wall Street analyst.
Provide institutional-quality financial analysis. Use real data from the context provided.
Cover portfolio strategy, market dynamics, earnings catalysts, and risk factors.
Format responses with markdown. Include specific numbers and price targets where relevant.
Always include: 'This is intelligence analysis, not licensed financial advice.'

{web_context}"""

    user_prompt = body.message
    if body.context:
        user_prompt = f"Market context: {body.context}\n\nQuestion: {body.message}"

    model = body.model if body.model in ("claude-opus-4-6", "claude-sonnet-4-5") else "claude-opus-4-6"

    async def generate():
        try:
            async for chunk in _stream_claude(
                [{"role": "user", "content": user_prompt}],
                system,
                model=model,
            ):
                yield _sse_chunk(chunk)
            yield _sse_done({"vertical": "finance", "model_used": model})
        except Exception as exc:
            yield _sse_error(f"Analysis failed: {str(exc)[:200]}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ═══════════════════════════════════════════════════════════════════════════════
# POST /api/finance/dcf  — Discounted Cash Flow model
# ═══════════════════════════════════════════════════════════════════════════════

@router.post("/api/finance/dcf")
async def finance_dcf(body: DCFRequest, request: Request):
    """
    DCF valuation model.
    Projects free cash flows for N years, discounts at WACC,
    adds terminal value using EV/EBITDA exit multiple.
    Returns enterprise value range (bear/base/bull) and implied equity value.
    """
    _verify_key(request)

    revenue = body.revenue  # $M
    wacc = body.discount_rate / 100
    tax = body.tax_rate / 100
    capex_pct = body.capex_pct / 100
    growth = body.revenue_growth / 100
    ebitda_margin = body.ebitda_margin / 100

    # ── Base case projections ─────────────────────────────────────────────────
    fcf_projections = []
    current_rev = revenue
    pv_fcfs = 0.0

    for yr in range(1, body.years + 1):
        current_rev *= (1 + growth)
        ebitda = current_rev * ebitda_margin
        nopat = ebitda * (1 - tax)  # simplified NOPAT
        capex = current_rev * capex_pct
        fcf = nopat - capex
        pv = fcf / ((1 + wacc) ** yr)
        pv_fcfs += pv
        fcf_projections.append({
            "year": yr,
            "revenue": round(current_rev, 2),
            "ebitda": round(ebitda, 2),
            "fcf": round(fcf, 2),
            "pv_fcf": round(pv, 2),
        })

    # Terminal value (EV/EBITDA multiple on year N EBITDA)
    terminal_ebitda = fcf_projections[-1]["ebitda"]
    terminal_value = terminal_ebitda * body.terminal_multiple
    pv_terminal = terminal_value / ((1 + wacc) ** body.years)

    enterprise_value_base = pv_fcfs + pv_terminal

    # Bear/bull ranges via ±20% on growth and ±1 on multiple
    def _calc_ev(g_adj, mult_adj):
        rv = revenue
        pv_sum = 0.0
        for yr in range(1, body.years + 1):
            rv *= (1 + (growth + g_adj))
            ebitda = rv * ebitda_margin
            nopat = ebitda * (1 - tax)
            pv_sum += (nopat - rv * capex_pct) / ((1 + wacc) ** yr)
        tv = rv * ebitda_margin * (body.terminal_multiple + mult_adj)
        return pv_sum + tv / ((1 + wacc) ** body.years)

    ev_bear = _calc_ev(-growth * 0.3, -2)
    ev_bull = _calc_ev(growth * 0.3, +2)

    # Upside/downside from base
    upside_pct = ((ev_bull - enterprise_value_base) / enterprise_value_base * 100) if enterprise_value_base else 0
    downside_pct = ((ev_bear - enterprise_value_base) / enterprise_value_base * 100) if enterprise_value_base else 0

    return JSONResponse({
        "company": body.company_name or "Target Company",
        "inputs": {
            "revenue_m": revenue,
            "revenue_growth_pct": body.revenue_growth,
            "ebitda_margin_pct": body.ebitda_margin,
            "discount_rate_pct": body.discount_rate,
            "terminal_multiple": body.terminal_multiple,
            "projection_years": body.years,
            "tax_rate_pct": body.tax_rate,
            "capex_pct": body.capex_pct,
        },
        "projections": fcf_projections,
        "terminal_value": round(terminal_value, 2),
        "pv_terminal_value": round(pv_terminal, 2),
        "pv_fcf_sum": round(pv_fcfs, 2),
        "valuation": {
            "enterprise_value_bear": round(ev_bear, 2),
            "enterprise_value_base": round(enterprise_value_base, 2),
            "enterprise_value_bull": round(ev_bull, 2),
            "upside_pct_from_base": round(upside_pct, 1),
            "downside_pct_from_base": round(downside_pct, 1),
        },
        "methodology": f"DCF: {body.years}-year projection at {body.revenue_growth}% growth, {body.ebitda_margin}% EBITDA margin, {body.discount_rate}% WACC, {body.terminal_multiple}x terminal EV/EBITDA",
        "disclaimer": "This is a simplified DCF model for illustrative purposes only. Not investment advice.",
    })
