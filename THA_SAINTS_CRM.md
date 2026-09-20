# Tha Saints CRM deployment contract

This patch repairs the core contact integration. It is not a claim that the full provider API is implemented or that production credentials have been verified.

## Required server configuration

- `SUPABASE_URL` and `SUPABASE_ANON_KEY`: the same Supabase project used by the client session. The server validates each session with `/auth/v1/user`.
- `CRM_TENANT_CONFIG`: JSON keyed by verified user UUID. Example: `{"user-uuid":{"locationId":"workspace-id","tokenEnv":"CRM_WORKSPACE_TOKEN"}}`. Set each referenced token as a server secret. Do not select a workspace from a client-supplied location ID or user-editable metadata.
- Optional server-only `CRM_GATEWAY_KEY` of at least 32 characters, with `GHL_PRIVATE_TOKEN` and `GHL_LOCATION_ID`. Never send this key to a browser or mobile bundle. The former embedded shared key is intentionally rejected by CRM routes.
- Configure CORS to permit the actual app origins. The redesigned web client uses `NEXT_PUBLIC_CRM_API_URL`; mobile uses the existing `MCP_BASE`.

Deploy the backend before its matching clients. `/api/crm` is canonical. `/api/ghl` and the supported `/api/mcp/crm` actions remain compatibility adapters and enforce the same authentication. Register `install_crm(app)` before legacy routers. Keep the three copies of `saints_crm.py` identical until they can share a package.

## Implemented operations

Contact search and pagination; get; upsert; edit; delete; additive/removal tags; list/add notes; list/add contact tasks; pipeline list; opportunity list/stage/status; conversations and message history; SMS/email acceptance; workflows and membership; calendars list; real connection check; limited stats; device dialer links. OpenAPI describes canonical routes after deployment.

An accepted SMS/email is not proof of delivery. A `tel:` link opens the user's device dialer; it does not place or log an automatic provider call. A timeout after a write is ambiguous: inspect the contact before retrying. Upserts follow the workspace's duplicate policy and use `createNewIfDuplicateAllowed:false`; separately adding tags preserves existing tags. Revenue and task metrics return null when unimplemented.

## Not implemented or awaiting configuration

Automated outbound calling and call logging; delivery/event webhook signature verification, durable ingestion and replay protection; OAuth refresh and encrypted credential self-service; calendar event/appointment CRUD and free slots; social publishing; agency provisioning and snapshot installation; creating provider workflows from the builder; complete provider API coverage. Connection mutation and automatic calling return 501 rather than claiming success.

## Validation and release gates

Run `python -m pytest -q tests/test_saints_crm.py` with FastAPI, Pydantic 2, HTTPX, and pytest installed. Tests use mocked provider/auth responses. No live contacts were created, messaged, called, or deleted during this audit.

Before release: rotate the provider token previously committed in browser/mobile code, configure tenant mappings/scopes, verify actual provider responses in a test workspace, and run contact save/read-back/update/pagination tests. Verify an unmapped user and a cross-workspace ID are denied. Only test SMS/email/calls with an explicitly approved test recipient. Enable endpoint health/latency/error monitoring without logging tokens or contact bodies. Do not merge a frontend ahead of its API deployment.
