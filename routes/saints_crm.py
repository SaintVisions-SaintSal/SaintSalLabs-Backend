"""Tha Saints CRM API. Provider identifiers remain internal for compatibility.

Register before legacy routers. /api/crm is canonical; /api/ghl is an alias.
Authentication: verified Supabase user + server-owned CRM_TENANT_CONFIG mapping,
or a server-to-server CRM_GATEWAY_KEY (never embed that key in a client).
No browser cache, synthetic records, implicit retries of writes, or fake success.
"""
import asyncio
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Optional
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator, ValidationError

router = APIRouter(tags=["Tha Saints CRM"])
bridge = APIRouter(tags=["Tha Saints CRM compatibility"])
API_BASE = "https://services.leadconnectorhq.com"
BRAND = "Tha Saints CRM"

@dataclass(frozen=True)
class Tenant:
    location: str
    token: str
    principal: str

async def resolve_tenant(request: Request) -> Tenant:
    gateway = os.getenv("CRM_GATEWAY_KEY", "")
    supplied = request.headers.get("x-sal-key", "")
    config: dict = {}
    principal = "server"
    if gateway and len(gateway) >= 32 and supplied and hmac.compare_digest(gateway, supplied):
        config = {"locationId": os.getenv("GHL_LOCATION_ID"), "token": os.getenv("GHL_PRIVATE_TOKEN")}
    else:
        bearer = request.headers.get("authorization", "")
        if not bearer.startswith("Bearer ") or not bearer[7:].strip():
            raise HTTPException(401, "Sign in to Tha Saints CRM.")
        url, key = os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_ANON_KEY", "")
        if not url.startswith("https://") or not key:
            raise HTTPException(503, "CRM authentication is not configured.")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.get(url.rstrip("/") + "/auth/v1/user", headers={"apikey": key, "Authorization": bearer})
            if res.status_code in (401, 403):
                raise HTTPException(401, "Your session has expired. Sign in again.")
            if res.status_code != 200:
                raise HTTPException(503, "CRM authentication is temporarily unavailable.")
            user = res.json()
            principal = user.get("id", "")
            if not principal:
                raise HTTPException(401, "Invalid session.")
            mappings = json.loads(os.getenv("CRM_TENANT_CONFIG", "{}"))
            config = mappings.get(principal, {})
            if not isinstance(config, dict) or not config:
                raise HTTPException(403, "Your account is not connected to Tha Saints CRM.")
        except (httpx.HTTPError, ValueError, AttributeError):
            raise HTTPException(503, "CRM authentication configuration is unavailable.") from None
    # Location and credential are selected only from trusted server configuration.
    token_env = config.get("tokenEnv", "CRM_UNCONFIGURED_TOKEN")
    if not isinstance(token_env, str):
        raise HTTPException(503, "CRM credential configuration is invalid.")
    token = config.get("token") or os.getenv(token_env, "")
    location = config.get("locationId")
    if not isinstance(token, str) or not token or not isinstance(location, str) or not location:
        raise HTTPException(503, "Tha Saints CRM is not configured for this account.")
    return Tenant(location, token, principal)


def segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(422, "Invalid CRM record identifier.")
    return quote(value, safe="")


async def provider(tenant: Tenant, method: str, path: str, *, params=None, payload=None) -> dict:
    headers = {"Authorization": "Bearer " + tenant.token, "Version": "v3", "Accept": "application/json", "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20, connect=5)) as client:
            # Only reads may be retried: a timeout after a write can mean it succeeded.
            for attempt in range(2 if method == "GET" else 1):
                res = await client.request(method, API_BASE + path, params=params, json=payload, headers=headers)
                if method == "GET" and attempt == 0 and res.status_code in (502, 503, 504):
                    await asyncio.sleep(0.2)
                    continue
                break
        if res.status_code == 429:
            retry = res.headers.get("Retry-After", "60")
            raise HTTPException(429, "Tha Saints CRM is busy. Retry after the indicated delay.", headers={"Retry-After": retry if retry.isdigit() else "60"})
        if res.status_code >= 400:
            status = res.status_code if res.status_code in (400, 404, 409, 422) else 502
            raise HTTPException(status, f"Tha Saints CRM could not complete the request (provider status {res.status_code}).")
        if res.status_code == 204:
            return {}
        data = res.json()
        if not isinstance(data, dict) or data.get("success") is False or data.get("error"):
            raise HTTPException(502, "Tha Saints CRM returned an unsuccessful response.")
        return data
    except httpx.TimeoutException:
        raise HTTPException(504, "Tha Saints CRM timed out. Check the record before repeating a save.") from None
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Tha Saints CRM returned an unavailable or invalid response.") from None


def result(data: Any, key: Optional[str] = None, **extra) -> dict:
    return {"ok": True, "success": True, "data": data, **({key: data} if key else {}), **extra}


def records(data: dict, key: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise HTTPException(502, "Tha Saints CRM returned an invalid record list.")
    return value


def contact_view(c: dict) -> dict:
    return {**c, "name": c.get("name") or " ".join(filter(None, [c.get("firstName"), c.get("lastName")])) or c.get("email") or c.get("phone") or "Unnamed contact", "firstName": c.get("firstName") or "", "lastName": c.get("lastName") or "", "email": c.get("email") or "", "phone": c.get("phone") or "", "tags": c.get("tags") or [], "dateAdded": c.get("dateAdded") or ""}

async def owned(tenant: Tenant, resource: str, record_id: str) -> dict:
    data = await provider(tenant, "GET", f"/{resource}/{segment(record_id)}")
    singular = {"contacts": "contact", "opportunities": "opportunity", "conversations": "conversation"}[resource]
    record = data.get(singular, data)
    if not isinstance(record, dict) or record.get("id") != record_id:
        raise HTTPException(502, "Tha Saints CRM returned an invalid record.")
    if record.get("locationId") != tenant.location:
        raise HTTPException(404, "CRM record not found in this workspace.")
    return record

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class ContactInput(StrictModel):
    firstName: Optional[str] = Field(None, max_length=100)
    lastName: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=254)
    phone: Optional[str] = Field(None, max_length=30)
    companyName: Optional[str] = Field(None, max_length=200)
    source: Optional[str] = Field(None, max_length=200)
    tags: Optional[list[str]] = Field(None, max_length=100)
    customFields: Optional[list[dict[str, Any]]] = Field(None, max_length=100)
    address1: Optional[str] = Field(None, max_length=500)
    city: Optional[str] = Field(None, max_length=100)
    state: Optional[str] = Field(None, max_length=100)
    postalCode: Optional[str] = Field(None, max_length=30)
    country: Optional[str] = Field(None, pattern=r"^[A-Z]{2}$")
    @model_validator(mode="after")
    def validate_identity(self):
        if self.email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", self.email):
            raise ValueError("Enter a valid email address.")
        if self.phone:
            self.phone = re.sub(r"[\s().-]", "", self.phone)
            if not re.fullmatch(r"\+[1-9]\d{6,14}", self.phone):
                raise ValueError("Use an international phone number starting with + and country code.")
        return self

class SearchInput(StrictModel):
    query: str = Field("", max_length=200)
    limit: int = Field(50, ge=1, le=100)
    page: int = Field(1, ge=1)
    offset: int = Field(0, ge=0)
    tag: Optional[str] = Field(None, max_length=100)

async def search(tenant: Tenant, body: SearchInput) -> dict:
    payload = {"locationId": tenant.location, "page": body.page + body.offset // body.limit, "pageLimit": body.limit}
    if body.offset % body.limit:
        raise HTTPException(422, "Offset must be a multiple of the page limit; use page for pagination.")
    if body.query: payload["query"] = body.query
    if body.tag: payload["filters"] = [{"field": "tags", "operator": "contains", "value": body.tag}]
    data = await provider(tenant, "POST", "/contacts/search", payload=payload)
    contacts = [contact_view(c) for c in records(data, "contacts")]
    return result(contacts, "contacts", meta=data.get("meta", {}), total=data.get("total"), page=payload["page"], limit=body.limit)

@router.get("/contacts")
async def list_contacts(query: str = Query("", max_length=200), tag: Optional[str] = Query(None, max_length=100), page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), tenant: Tenant = Depends(resolve_tenant)):
    return await search(tenant, SearchInput(query=query, tag=tag, page=page, limit=limit, offset=offset))

@router.post("/contacts/search")
async def search_contacts(body: SearchInput, tenant: Tenant = Depends(resolve_tenant)):
    return await search(tenant, body)

async def save_contact(body: ContactInput, tenant: Tenant) -> dict:
    if not body.email and not body.phone:
        raise HTTPException(422, "An email or international phone number is required to save a contact.")
    payload = body.model_dump(exclude_unset=True, exclude_none=True)
    # Upsert honors the workspace duplicate policy; tag writes are additive.
    tags = payload.pop("tags", [])
    payload.update(locationId=tenant.location, createNewIfDuplicateAllowed=False)
    payload.setdefault("source", BRAND)
    data = await provider(tenant, "POST", "/contacts/upsert", payload=payload)
    contact = data.get("contact")
    if not isinstance(contact, dict) or not contact.get("id"):
        raise HTTPException(502, "Tha Saints CRM did not confirm a saved contact.")
    if contact.get("locationId") != tenant.location:
        raise HTTPException(502, "Tha Saints CRM returned an unexpected workspace.")
    if tags:
        try:
            await provider(tenant, "POST", f"/contacts/{segment(contact['id'])}/tags", payload={"tags": tags})
        except HTTPException as error:
            raise HTTPException(error.status_code, {"message": "Contact saved, but tags could not be applied. Reload the contact before retrying.", "contactId": contact["id"], "partial": True}) from None
        contact = await owned(tenant, "contacts", contact["id"])
    return result(contact_view(contact), "contact", created=data.get("new", False))

@router.post("/contacts")
@router.post("/contacts/create")
@router.post("/contacts/upsert")
async def create_contact(body: ContactInput, tenant: Tenant = Depends(resolve_tenant)):
    return await save_contact(body, tenant)

@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    return result(contact_view(await owned(tenant, "contacts", contact_id)), "contact")

@router.patch("/contacts/{contact_id}")
@router.put("/contacts/{contact_id}")
async def update_contact(contact_id: str, body: ContactInput, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    payload = body.model_dump(exclude_unset=True)
    if not payload: raise HTTPException(422, "Provide a contact field to update.")
    if "tags" in payload: raise HTTPException(422, "Use the tags endpoint to add or remove tags safely.")
    data = await provider(tenant, "PUT", f"/contacts/{segment(contact_id)}", payload=payload)
    contact = data.get("contact")
    if not isinstance(contact, dict) or contact.get("id") != contact_id:
        raise HTTPException(502, "Tha Saints CRM did not confirm the update.")
    return result(contact_view(contact), "contact")

@router.delete("/contacts/{contact_id}")
async def delete_contact(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    return result(await provider(tenant, "DELETE", f"/contacts/{segment(contact_id)}"))

class TagsInput(StrictModel):
    tags: list[str] = Field(min_length=1, max_length=100)

@router.post("/contacts/{contact_id}/tags")
@router.delete("/contacts/{contact_id}/tags")
async def contact_tags(contact_id: str, body: TagsInput, request: Request, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    return result(await provider(tenant, request.method, f"/contacts/{segment(contact_id)}/tags", payload=body.model_dump()))

class NoteInput(StrictModel):
    body: str = Field(min_length=1, max_length=20000)

@router.get("/contacts/{contact_id}/notes")
async def contact_notes(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    data = await provider(tenant, "GET", f"/contacts/{segment(contact_id)}/notes")
    return result(records(data, "notes"), "notes")

@router.post("/contacts/{contact_id}/notes")
async def add_note(contact_id: str, body: NoteInput, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    return result(await provider(tenant, "POST", f"/contacts/{segment(contact_id)}/notes", payload=body.model_dump()))

class TaskInput(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    dueDate: datetime
    body: str = Field("", max_length=10000)
    completed: bool = False
    assignedTo: Optional[str] = None

@router.get("/contacts/{contact_id}/tasks")
async def contact_tasks(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    data = await provider(tenant, "GET", f"/contacts/{segment(contact_id)}/tasks")
    return result(records(data, "tasks"), "tasks")

@router.post("/contacts/{contact_id}/tasks")
async def add_task(contact_id: str, body: TaskInput, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    if body.dueDate.tzinfo is None: raise HTTPException(422, "Task due date must include a timezone.")
    return result(await provider(tenant, "POST", f"/contacts/{segment(contact_id)}/tasks", payload=body.model_dump(mode="json", exclude_none=True)))

@router.get("/pipelines")
async def pipelines(tenant: Tenant = Depends(resolve_tenant)):
    data = await provider(tenant, "GET", "/opportunities/pipelines", params={"locationId": tenant.location})
    return result(records(data, "pipelines"), "pipelines")

@router.get("/opportunities")
async def opportunities(pipelineId: Optional[str] = None, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant)):
    params = {"locationId": tenant.location, "page": page, "limit": limit}
    if pipelineId: params["pipelineId"] = pipelineId
    data = await provider(tenant, "GET", "/opportunities/search", params=params)
    return result(records(data, "opportunities"), "opportunities", meta=data.get("meta", {}))

class MoveInput(StrictModel):
    pipelineStageId: str

@router.patch("/opportunities/{opportunity_id}/move")
async def move_opportunity(opportunity_id: str, body: MoveInput, tenant: Tenant = Depends(resolve_tenant)):
    opportunity = await owned(tenant, "opportunities", opportunity_id)
    all_pipelines = (await pipelines(tenant))["pipelines"]
    pipeline = next((p for p in all_pipelines if p.get("id") == opportunity.get("pipelineId")), None)
    if not pipeline or not any(s.get("id") == body.pipelineStageId for s in pipeline.get("stages", [])):
        raise HTTPException(422, "Select a stage in this opportunity's pipeline.")
    return result(await provider(tenant, "PUT", f"/opportunities/{segment(opportunity_id)}", payload=body.model_dump()))

class StatusInput(StrictModel):
    status: Literal["open", "won", "lost", "abandoned"]

@router.patch("/opportunities/{opportunity_id}/status")
async def opportunity_status(opportunity_id: str, body: StatusInput, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "opportunities", opportunity_id)
    return result(await provider(tenant, "PUT", f"/opportunities/{segment(opportunity_id)}/status", payload=body.model_dump()))

@router.get("/conversations")
async def conversations(type: Optional[str] = None, limit: int = Query(50, ge=1, le=100), startAfterDate: Optional[str] = None, tenant: Tenant = Depends(resolve_tenant)):
    params = {"locationId": tenant.location, "limit": limit}
    if type: params["lastMessageType"] = "TYPE_CALL" if type == "TYPE_PHONE" else type
    if startAfterDate: params["startAfterDate"] = startAfterDate
    data = await provider(tenant, "GET", "/conversations/search", params=params)
    rows = [{**c, "contactName": c.get("contactName") or c.get("fullName") or "Contact", "type": "TYPE_PHONE" if c.get("lastMessageType") == "TYPE_CALL" else c.get("lastMessageType") or c.get("type") or "TYPE_SMS", "lastMessageBody": c.get("lastMessageBody") or "", "lastMessageDate": c.get("lastMessageDate") or "", "unreadCount": c.get("unreadCount") or 0} for c in records(data, "conversations")]
    return result(rows, "conversations", total=data.get("total"))

@router.get("/conversations/{conversation_id}/messages")
async def messages(conversation_id: str, limit: int = Query(50, ge=1, le=100), lastMessageId: Optional[str] = None, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "conversations", conversation_id)
    params = {"limit": limit}
    if lastMessageId: params["lastMessageId"] = lastMessageId
    return result(await provider(tenant, "GET", f"/conversations/{segment(conversation_id)}/messages", params=params))

class MessageInput(StrictModel):
    body: str = Field(min_length=1, max_length=20000)
    type: Literal["SMS", "Email"] = "SMS"
    subject: Optional[str] = Field(None, max_length=500)

@router.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: MessageInput, tenant: Tenant = Depends(resolve_tenant)):
    convo = await owned(tenant, "conversations", conversation_id)
    contact = await owned(tenant, "contacts", convo.get("contactId", ""))
    channel = body.type.lower()
    if contact.get("dnd") or contact.get("dndSettings", {}).get(channel, {}).get("status") == "active":
        raise HTTPException(409, "This contact has disabled communication on this channel.")
    payload = {"contactId": contact["id"], "type": body.type, "message": body.body, "status": "pending"}
    if body.type == "Email":
        if not body.subject: raise HTTPException(422, "An email subject is required.")
        payload["subject"] = body.subject
    data = await provider(tenant, "POST", "/conversations/messages", payload=payload)
    if not data.get("messageId") and not data.get("emailMessageId"):
        raise HTTPException(502, "Tha Saints CRM did not confirm message acceptance.")
    return result(data, accepted=True)  # Acceptance is not a delivery receipt.

@router.get("/workflows")
async def workflows(tenant: Tenant = Depends(resolve_tenant)):
    data = await provider(tenant, "GET", "/workflows", params={"locationId": tenant.location})
    return result(records(data, "workflows"), "workflows")

@router.post("/contacts/{contact_id}/workflows/{workflow_id}")
@router.delete("/contacts/{contact_id}/workflows/{workflow_id}")
async def workflow_membership(contact_id: str, workflow_id: str, request: Request, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    available = (await workflows(tenant))["workflows"]
    if not any(w.get("id") == workflow_id for w in available): raise HTTPException(404, "Workflow not found in this workspace.")
    return result(await provider(tenant, request.method, f"/contacts/{segment(contact_id)}/workflow/{segment(workflow_id)}", payload={} if request.method == "POST" else None))

@router.get("/calendars")
async def calendars(tenant: Tenant = Depends(resolve_tenant)):
    data = await provider(tenant, "GET", "/calendars", params={"locationId": tenant.location})
    return result(records(data, "calendars"), "calendars")

@router.get("/connection")
async def connection(tenant: Tenant = Depends(resolve_tenant)):
    await search(tenant, SearchInput(limit=1))
    return result({"connected": True, "locationId": tenant.location, "locationName": BRAND, "lastSyncAt": datetime.now(timezone.utc).isoformat()})

@router.get("/contacts/{contact_id}/dialer-link")
async def dialer_link(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    contact = await owned(tenant, "contacts", contact_id)
    if contact.get("dnd") or contact.get("dndSettings", {}).get("call", {}).get("status") == "active":
        raise HTTPException(409, "Calling is disabled for this contact.")
    phone = re.sub(r"[\s().-]", "", contact.get("phone") or "")
    if not re.fullmatch(r"\+[1-9]\d{6,14}", phone): raise HTTPException(422, "This contact needs a valid international phone number.")
    return result({"url": "tel:" + phone, "mode": "device_dialer", "callPlaced": False})

@router.post("/connect")
@router.post("/disconnect")
async def credential_lifecycle(tenant: Tenant = Depends(resolve_tenant)):
    raise HTTPException(501, "CRM connection changes require the server credential administrator; no change was made.")

@router.post("/contacts/{contact_id}/calls")
async def outbound_call(contact_id: str, tenant: Tenant = Depends(resolve_tenant)):
    await owned(tenant, "contacts", contact_id)
    raise HTTPException(501, "Automated dialing is not configured. Use the contact's device dialer. No call was placed.")

@bridge.post("/api/mcp/crm")
async def legacy_crm(request: Request, tenant: Tenant = Depends(resolve_tenant)):
    try: body = await request.json()
    except ValueError: raise HTTPException(422, "Invalid CRM request.") from None
    if not isinstance(body, dict): raise HTTPException(422, "Invalid CRM request.")
    action = body.get("action")
    if action in ("list_contacts", "search_contacts"):
        try: search_body = SearchInput(query=body.get("query", ""), limit=body.get("limit", 50), page=body.get("page", 1))
        except ValidationError: raise HTTPException(422, "Provide a valid search query and pagination.") from None
        return await search(tenant, search_body)
    if action in ("add_contact", "create_contact", "upsert_contact"):
        try: contact = ContactInput.model_validate(body.get("contact") or {k: v for k, v in body.items() if k != "action"})
        except ValidationError: raise HTTPException(422, "Provide valid contact fields, including email or international phone.") from None
        return await save_contact(contact, tenant)
    if action in ("get_pipeline", "list_pipelines"):
        data = await pipelines(tenant)
        return {**data, "pipeline": next(iter(data["pipelines"]), None)}
    raise HTTPException(422, "This CRM action is not supported. No action was performed.")


@router.get("/stats")
async def stats(tenant: Tenant = Depends(resolve_tenant)):
    contacts, pipes, deals = await asyncio.gather(
        search(tenant, SearchInput(limit=10)), pipelines(tenant),
        provider(tenant, "GET", "/opportunities/search", params={"locationId": tenant.location, "status": "open", "limit": 1}),
    )
    total = contacts.get("total")
    if total is None: total = contacts.get("meta", {}).get("total")
    active = deals.get("meta", {}).get("total")
    metrics = {"total_contacts": total, "pipelines_count": len(pipes["pipelines"]), "active_deals": active,
               "revenue_mtd": None, "tasks_due_today": None}
    return {"ok": True, "success": True, "data": metrics, "stats": metrics, "contacts": total,
            "opportunities": active, "pipelines": pipes["pipelines"], "recent_leads": contacts["contacts"],
            "unavailable_metrics": ["revenue_mtd", "tasks_due_today"]}

@router.get("/activity")
async def activity(limit: int = Query(20, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant)):
    data = await search(tenant, SearchInput(limit=limit))
    rows = [{"type": "contact_record", "contact_id": c["id"], "name": c["name"], "timestamp": c.get("dateAdded")} for c in data["contacts"]]
    return result(rows, "activity", source="contacts", is_event_stream=False)

@router.get("/pipeline/{pipeline_id}/deals")
async def pipeline_deals(pipeline_id: str, page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=100), tenant: Tenant = Depends(resolve_tenant)):
    data = await opportunities(pipeline_id, page, limit, tenant)
    return {**data, "deals": data["opportunities"]}

class LegacyTaskInput(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    contact_id: str
    due_date: datetime
    assigned_to: Optional[str] = None
    description: str = Field("", max_length=10000)

@router.post("/tasks")
async def legacy_task_create(body: LegacyTaskInput, tenant: Tenant = Depends(resolve_tenant)):
    return await add_task(body.contact_id, TaskInput(title=body.title, dueDate=body.due_date, body=body.description, assignedTo=body.assigned_to), tenant)

@router.get("/tasks")
async def legacy_tasks(contact_id: str = Query(..., min_length=1), tenant: Tenant = Depends(resolve_tenant)):
    return await contact_tasks(contact_id, tenant)


def install_crm(app):
    @app.middleware("http")
    async def crm_no_store(request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/crm", "/api/ghl", "/api/mcp/crm")):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
        return response
    app.include_router(router, prefix="/api/crm")
    app.include_router(router, prefix="/api/ghl", include_in_schema=False)
    app.include_router(bridge)
