# CLAUDE.md — SaintSalLabs-Backend
# SaintSal™ Labs — AI Platform Backend
# Saint Vision Technologies LLC | US Patent #10,290,222 (HACP™)
# Owner: Ryan "Cap" Capatosto

---

## IDENTITY

This is the **SaintSal™ Labs backend** — the Python/FastAPI server powering `https://www.saintsallabs.com`.
It serves the web frontend (vanilla JS) AND the iOS app (React Native/Expo).
All AI, data, and integration logic lives here. The frontend and iOS are thin clients.

---

## STACK

| Layer | Technology |
|-------|-----------|
| Framework | Python 3.11 + FastAPI |
| Hosting | Render (auto-deploy from main branch) |
| Database | Supabase PostgreSQL |
| Auth | Supabase Auth (verified via JWT) |
| Static Files | FastAPI StaticFiles (serves web frontend) |
| AI Gateway | Claude → GPT-5 → Gemini → Grok (fallback chain) |

---

## GOLDEN RULES — VIOLATE NONE

1. **STATIC MOUNT LAST** — `app.mount("/", StaticFiles(...))` MUST be the LAST line before `if __name__ == "__main__"`. If ANY endpoint is defined after the static mount, it will 404. This kills features silently. Do not move the static mount. Do not add endpoints below it.

2. **BACKEND FIRST, FRONTEND SECOND** — Build and test every endpoint with `curl` before touching any frontend code.

3. **NO DIRECT API KEYS IN FRONTEND** — Every external API call goes through this backend. The iOS and web apps send `x-sal-key: saintvision_gateway_2025`. That's the only auth they use.

4. **FALLBACK EVERYTHING** — Every external API call (LLMs, search, data providers) has a try/except with a fallback. No single provider failure kills a feature.

5. **ADDITIVE ONLY** — New features go in NEW endpoints, NEW routes. Never modify a working endpoint unless the task explicitly requires it.

6. **VERIFY WITH EVIDENCE** — `curl` the endpoint, read the output, THEN say it works. "Should work" is not evidence.

7. **TIER GATING** — Every premium endpoint calls `check_tier()` before execution. Free users hit Free endpoints only.

---

## CSS VARIABLES (use in all frontend files served from this backend)

```css
--bg: #0b0b0f;
--bg2: #131318;
--bg3: #1a1a22;
--t1: #e8e6e1;
--t2: #999;
--t3: #666;
--brd: #1e1e28;
--gold: #f59e0b;
--green: #00ff88;
--purple: #a78bfa;
--blue: #60a5fa;
--coral: #f87171;
--teal: #2dd4bf;
--amber: #fbbf24;
--mono: 'SF Mono', Monaco, Consolas, monospace;
```

---

## AUTH HEADER

iOS and web send: `x-sal-key: saintvision_gateway_2025`

All endpoints validate this header:
```python
def verify_sal_key(request: Request):
    key = request.headers.get("x-sal-key")
    if key != os.environ.get("SAL_GATEWAY_KEY", "saintvision_gateway_2025"):
        raise HTTPException(403, "Invalid gateway key")
```

---

## ALL ENDPOINTS — MASTER LIST

### Section 1: Core Chat Engine (8 Verticals)
```
POST /api/mcp/chat              — SSE streaming. Params: { message, vertical, model?, conversation_id, user_id, team_ids?, news_prefs? }
GET  /api/verticals/trending    — Trending content per vertical. Params: ?vertical=&user_id=
```

### Section 2: Builder v2 (5-Agent Pipeline)
```
POST /api/builder/agent          — v1 pipeline (3-agent, keep for backwards compat)
POST /api/builder/agent/v2       — v2 pipeline (5-agent SSE: Grok→Stitch→Sonnet→Opus→GPT5)
POST /api/builder/agent/v2/approve — Resume pipeline after design approval
POST /api/builder/iterate        — Diff-based code editing (not full regen)
POST /api/builder/deploy         — Deploy to Vercel/Render/Cloudflare
GET  /api/builder/models         — Available models per tier
POST /api/builder/stitch         — Direct Stitch MCP proxy
POST /api/builder/v2/generate    — Quick build (no pipeline)
```

### Section 3: Career + Business
```
GET  /api/career/jobs            — Job search (Exa + Tavily)
POST /api/career/resume          — Resume generation
POST /api/career/enhance         — AI resume enhancement
POST /api/career/coach           — Career coaching
POST /api/career/interview       — Interview prep
POST /api/career/cover-letter    — Cover letter (Claude Sonnet)
POST /api/career/swot            — SWOT analysis
POST /api/career/bizplan         — Business plan generation (SSE stream)
POST /api/career/linkedin-optimize — LinkedIn profile optimizer
POST /api/career/salary-negotiate  — Salary negotiation coach
POST /api/career/network-map       — Network mapping (Apollo + Claude)
POST /api/business/plan            — Full business plan AI (SSE, PDF/DOCX output)
POST /api/business/patent-search   — IP/Patent intelligence (Teams+)
```

### Section 4: Creative Studio
```
POST /api/creative/generate        — Content gen (caption/blog/image/video/email)
POST /api/creative/image           — Image gen (DALL-E/Grok/Stitch/SDXL routing)
POST /api/creative/social/post     — Social posting via GHL
POST /api/creative/calendar        — Content calendar AI
POST /api/creative/calendar/batch-generate — Batch generate week of posts
POST /api/creative/brand-profile   — Create/update brand profile
```

### Section 5: Launch Pad (Business Formation)
```
POST /api/launchpad/name-check     — Name availability (GoDaddy + FileForms + trademark)
POST /api/launchpad/entity-advisor — AI entity type recommendation
POST /api/launchpad/domain/purchase — Domain purchase via GoDaddy
POST /api/launchpad/entity/form    — LLC/Corp formation via FileForms
POST /api/launchpad/entity/ein     — EIN filing
POST /api/launchpad/dns/configure  — Auto DNS setup (GoDaddy)
POST /api/launchpad/ssl/provision  — SSL provisioning
POST /api/launchpad/compliance/setup — Compliance calendar (GHL reminders)
POST /api/launchpad/order          — FileForms formation order (legacy)
```

### Section 6: CookinCards™
```
POST /api/cards/scan             — Camera → Ximilar TCG/Sport ID + eBay listings
POST /api/cards/grade            — Full PSA-style grading (front+back, 70/30 weighted)
POST /api/cards/quick-grade      — Fast condition check (NM/LP/MP/HP/D)
POST /api/cards/centering        — Centering only
POST /api/cards/slab-read        — OCR graded slab label
POST /api/cards/price            — Price lookup by card ID
GET  /api/cards/search           — Search by name/set/year (Pokemon TCG API)
GET  /api/cards/collection       — User's saved collection
POST /api/cards/collection/add   — Add card to collection
GET  /api/cards/market/trending  — Trending cards + price movers
GET  /api/cards/deals            — Card deals
```

### Section 7: CRM + GHL
```
GET  /api/ghl/stats              — Pipeline stats for dashboard
POST /api/mcp/crm                — GHL CRM actions (list_contacts, add_contact, get_pipeline)
```

### Section 8: Finance
```
GET  /api/finance/markets        — Market data (Alpaca)
GET  /api/alpaca/portfolio       — Portfolio summary
```

### Section 9: Real Estate
```
GET  /api/realestate/search      — Property search
GET  /api/realestate/distressed-search — Distressed property leads
GET  /api/realestate/portfolio   — RE portfolio
```

### Section 10: Voice
```
POST /api/voice/transcribe       — STT via Deepgram
POST /api/voice/synthesize       — TTS via ElevenLabs
```

### Section 11: Social
```
GET  /api/social/platforms       — Connected social platform status
POST /api/marketing/daily-content — GHL Social Studio daily content
```

### Section 12: Pricing + Checkout
```
GET  /api/pricing/tiers          — Subscription tier info
POST /api/checkout/session       — Stripe checkout
POST /api/checkout/create-session — Stripe session create
GET  /api/checkout/session-status — Stripe session status
POST /api/stripe/webhook         — Stripe events webhook
```

### Section 13: Metering
```
POST /api/metering/log           — Log compute usage
GET  /api/metering/usage         — Get user's remaining compute
```

---

## INTELLIGENCE VERTICALS — MODEL ROUTING

| Vertical | Primary Model | Tools |
|----------|--------------|-------|
| Sports + News | Grok 4.20 | Tavily + Exa (live scores, breaking news) |
| Search/Research | Claude Opus 4.6 | Exa + Tavily Deep + Perplexity |
| Finance | Claude Opus + Grok 4.20 | Alpaca (market data) |
| Real Estate | Claude Sonnet 4.6 | RentCast + PropertyAPI + Google Maps |
| Healthcare | Claude Opus 4.6 ONLY | Exa (PubMed) — zero hallucination tolerance |
| Legal | Claude Opus 4.6 | Exa (case law) + Tavily |
| Technology | Claude Sonnet + GPT-5 | Grok |
| Gov/Defense | Claude Opus 4.6 | Azure AI Search |

**Fallback chain:** Claude → GPT-5 → Gemini → Grok

---

## BUILDER v2 — 5-AGENT SSE PIPELINE

```
Phase 1:  Grok 4.20        → plan_ready       (architecture + component tree)
Phase 2a: Google Stitch MCP → design_ready     (full UI screens, HTML/CSS)
          ─── PAUSE: User reviews designs ───
          ─── POST /api/builder/agent/v2/approve to continue ───
Phase 2b: Claude Sonnet 4.6 → scaffold_ready   (file tree + route structure)
Phase 3:  Claude Opus 4.6   → files_ready      (synthesis: designs + scaffold = final code)
Phase 4:  GPT-5 Core        → validation_ready (lint + test + optimization)
```

### SSE Events
```
agent_status     — { agent, status, message }
plan_ready       — { plan, components, tech_stack }
design_ready     — { screens: [{name, html, css, thumbnail}], session_id }
scaffold_ready   — { files: [{path, description}] }
files_ready      — { files: [{path, content, language}] }
validation_ready — { lint_results, test_results, suggestions }
deploy_ready     — { url, platform }
error            — { agent, message, recoverable }
complete         — { total_time, agents_used }
```

---

## XIMILAR API (CookinCards)

```
Base URL: https://api.ximilar.com
Auth: Authorization: Token {XIMILAR_API_KEY}

Endpoints:
  POST /collectibles/v2/tcg_id    — Pokemon, MTG, Yu-Gi-Oh!, Lorcana
  POST /collectibles/v2/sport_id  — Baseball, Basketball, Football, Hockey
  POST /card-grader/v2/grade      — Full grading (centering, corners, edges, surface)
  POST /card-grader/v2/condition  — Quick condition (NM/LP/MP/HP/D)
  POST /card-grader/v2/centering  — Centering only

Options: get_listings: true (eBay prices), get_slab_detail: true (slab OCR)
```

---

## SUBSCRIPTION TIERS

| Tier | Monthly | Compute Min | Models |
|------|---------|-------------|--------|
| Free | $0 | 100/mo | SAL Mini only |
| Starter | $27 | 500/mo | + SAL Pro |
| Pro | $97 | 2,000/mo | + SAL Max (Opus) + Builder v2 + Voice + Creative |
| Teams | $297 | 10,000/mo | + SAL Max Fast + Multi-seat + SAINT Leads |
| Enterprise | $497 | Unlimited | + API + White-label + HACP™ license |

---

## SUPABASE TABLES

```sql
profiles              — user profile, tier, stripe_customer_id, ghl_location_id
conversations         — chat history (messages as JSONB)
usage_log             — compute metering
builder_sessions      — saved builds + pipeline state
builder_projects      — published builder projects
user_preferences      — settings, business DNA, news prefs
card_collections      — CookinCards collections
collection_cards      — individual cards with values
launch_pad_orders     — business formation orders
brand_profiles        — Creative Studio brand profiles
business_plans        — saved business plans
content_calendar      — scheduled social content
```

---

## ENV VARS — ALL REQUIRED

```bash
# Core
SUPABASE_URL=https://euxrlpuegeiggedqbkiv.supabase.co
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_KEY=
SAL_GATEWAY_KEY=saintvision_gateway_2025

# LLMs
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GEMINI_API_KEY=
XAI_API_KEY=
AZURE_AI_FOUNDRY_KEY=
AZURE_AI_FOUNDRY_ENDPOINT=
AZURE_OPENAI_ENDPOINT=
PERPLEXITY_API_KEY=

# Search
EXA_API_KEY=
TAVILY_API_KEY=
AZURE_SEARCH_KEY=
AZURE_SEARCH_ENDPOINT=
AZURE_SEARCH_INDEX=

# Voice
ELEVENLABS_API_KEY=
ELEVENLABS_AGENT_ID=agent_5401k855rq5afqprn6vd3mh6sn7z
DEEPGRAM_API_KEY=

# CRM + Business
GHL_LOCATION_ID=oRA8vL3OSiCPjpwmEC0V
GHL_PRIVATE_TOKEN=
GHL_WEBHOOK_SECRET=
STRIPE_SECRET_KEY=
STRIPE_WEBHOOK_SECRET=
RESEND_API_KEY=

# Real Estate
RENTCAST_API_KEY=
PROPERTY_API_KEY=
GOOGLE_MAPS_API_KEY=

# Formation + Domains
FILEFORMS_API_KEY=
GODADDY_API_KEY=
GODADDY_API_SECRET=

# Collectibles
XIMILAR_API_KEY=

# Media
REPLICATE_API_TOKEN=
RUNWAY_API_KEY=

# Finance
ALPACA_API_KEY=
ALPACA_SECRET_KEY=
```

---

## STATIC MOUNT PATTERN (CRITICAL)

```python
# ═══════════════════════════════════════════════════════════════
# STATIC MOUNT — THIS MUST BE THE LAST THING BEFORE __main__
# Every endpoint MUST be defined above this line.
# Adding endpoints below this line = silent 404 for those endpoints.
# ═══════════════════════════════════════════════════════════════
_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
```

---

## VERIFICATION BEFORE EVERY COMMIT

```bash
# 1. All endpoints respond
for ep in "/api/mcp/chat" "/api/cards/search?query=pikachu" "/api/career/jobs" "/api/ghl/stats" "/api/builder/agent/v2"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://www.saintsallabs.com${ep}")
  echo "  $code $ep"
done

# 2. No hardcoded keys in server.py
grep -n "sk-ant-\|sk-proj-\|tvly-\|xai-\|d3af35" server.py | head -5
# MUST return nothing

# 3. Static mount is last
tail -20 server.py
# MUST show app.mount() immediately before __main__
```

---

## BUILD + DEPLOY

```bash
# Deploy to Render (auto on push to main)
git add .
git commit -m "feat: [describe what changed]"
git push origin main
# Render picks up the push and redeploys in ~2 min

# Manual deploy check
curl https://www.saintsallabs.com/api/mcp/chat -X POST \
  -H "x-sal-key: saintvision_gateway_2025" \
  -H "Content-Type: application/json" \
  -d '{"message":"ping","vertical":"search","user_id":"test"}'
```

---

## THE STANDARD

This backend powers SaintSal™ Labs — a patented AI platform (HACP™ US #10,290,222) serving 175+ countries.
Every endpoint should be fast, fallback-safe, and return real data.
No mocked responses in production. No "I don't have access to live data."
If a search tool is available, USE IT. If a model fails, fall through to the next.
Build it like JP Morgan is reviewing the code.
