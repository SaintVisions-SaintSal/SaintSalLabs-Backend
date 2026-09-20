"""Contract and isolation tests. All provider and auth traffic is mocked."""
import json
import os
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from routes import saints_crm as crm

TENANT = crm.Tenant("location_a", "provider-test-token", "user_a")
CONTACT = {"id": "contact_a", "locationId": "location_a", "firstName": "Test", "email": "test@example.invalid", "phone": "+15555550100", "tags": ["existing"]}

@pytest.fixture
def harness(monkeypatch):
    app = FastAPI(); crm.install_crm(app)
    app.dependency_overrides[crm.resolve_tenant] = lambda: TENANT
    calls = []
    replies = {}
    def handler(req):
        payload = json.loads(req.content) if req.content else None
        calls.append((req.method, req.url.path, dict(req.url.params), payload, dict(req.headers)))
        if (req.method, req.url.path) in replies:
            reply = replies[(req.method, req.url.path)]
            if isinstance(reply, Exception): raise reply
            status, body, headers = (*reply, {})[:3] if len(reply) == 2 else reply
            return httpx.Response(status, json=body, headers=headers)
        p = req.url.path
        if p == "/contacts/search": body = {"contacts": [CONTACT], "total": 1}
        elif p == "/contacts/upsert": body = {"contact": CONTACT, "new": False}
        elif p == "/contacts/contact_a": body = {"contact": CONTACT}
        elif p == "/opportunities/pipelines": body = {"pipelines": [{"id": "pipeline_a", "stages": [{"id": "stage_a"}]}]}
        elif p == "/opportunities/opp_a": body = {"opportunity": {"id": "opp_a", "locationId": "location_a", "pipelineId": "pipeline_a"}}
        elif p == "/opportunities/search": body = {"opportunities": [], "meta": {"total": 0}}
        elif p == "/conversations/convo_a": body = {"id": "convo_a", "locationId": "location_a", "contactId": "contact_a"}
        elif p == "/conversations/messages": body = {"messageId": "message_a"}
        elif p == "/workflows": body = {"workflows": [{"id": "workflow_a"}]}
        elif p == "/calendars": body = {"calendars": []}
        elif p.endswith('/notes'): body = {"notes": []}
        elif p.endswith('/tasks'): body = {"tasks": []}
        else: body = {"success": True}
        return httpx.Response(200, json=body)
    original = httpx.AsyncClient
    monkeypatch.setattr(crm.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return TestClient(app), calls, replies, app

def test_missing_session_rejected(harness):
    client, calls, _, app = harness; app.dependency_overrides.clear()
    assert client.get('/api/crm/contacts').status_code == 401
    assert calls == []

def test_embedded_legacy_gateway_key_rejected(harness):
    client, calls, _, app = harness; app.dependency_overrides.clear()
    assert client.get('/api/crm/contacts', headers={'x-sal-key':'saintvision_gateway_2025'}).status_code == 401
    assert calls == []

def test_search_uses_post_and_scoped_pagination(harness):
    client, calls, _, _ = harness
    r=client.get('/api/crm/contacts?query=test&page=2&limit=25')
    assert r.status_code == 200
    assert r.json()['contacts'] == r.json()['data']
    assert calls[0][0:2] == ('POST','/contacts/search')
    assert calls[0][3] == {'locationId':'location_a','page':2,'pageLimit':25,'query':'test'}
    assert calls[0][4]['version'] == 'v3'

@pytest.mark.parametrize('limit',[0,101,-1])
def test_page_limit_validated(harness,limit):
    client,calls,_,_=harness
    assert client.get(f'/api/crm/contacts?limit={limit}').status_code==422
    assert not calls

def test_legacy_alias_and_bridge(harness):
    client,_,_,_=harness
    assert client.get('/api/ghl/contacts').status_code == 200
    assert client.post('/api/mcp/crm',json={'action':'list_contacts'}).json()['contacts']
    assert client.post('/api/mcp/crm',json={'action':'unknown'}).status_code == 422

def test_duplicate_safe_save_preserves_tags(harness):
    client,calls,_,_=harness
    r=client.post('/api/crm/contacts',json={'email':'test@example.invalid','tags':['new']})
    assert r.status_code==200 and r.json()['contact']['id']=='contact_a'
    write=next(c for c in calls if c[1]=='/contacts/upsert')
    assert 'tags' not in write[3] and write[3]['createNewIfDuplicateAllowed'] is False
    assert any(c[0]=='POST' and c[1]=='/contacts/contact_a/tags' for c in calls)

@pytest.mark.parametrize('body',[{}, {'firstName':'Test'}, {'email':'bad'}, {'phone':'555-0100'}, {'email':'test@example.invalid','locationId':'other'}])
def test_contact_validation(harness,body):
    client,calls,_,_=harness
    assert client.post('/api/crm/contacts',json=body).status_code==422
    assert not calls

def test_cross_tenant_write_rejected(harness):
    client,calls,replies,_=harness
    replies[('GET','/contacts/contact_a')]=(200,{'contact':{**CONTACT,'locationId':'location_b'}})
    assert client.patch('/api/crm/contacts/contact_a',json={'firstName':'Changed'}).status_code==404
    assert all(c[0]=='GET' for c in calls)

def test_provider_error_is_never_success(harness):
    client,_,replies,_=harness
    replies[('POST','/contacts/upsert')]=(401,{'message':'secret-test-token'})
    r=client.post('/api/crm/contacts',json={'email':'test@example.invalid'})
    assert r.status_code==502 and 'secret-test-token' not in r.text

def test_rate_limit_preserves_retry_after(harness):
    client,calls,replies,_=harness
    replies[('POST','/contacts/search')]=(429,{}, {'Retry-After':'7'})
    r=client.get('/api/crm/contacts');assert r.status_code==429 and r.headers['retry-after']=='7'
    assert len(calls)==1

def test_timeout_write_not_retried(harness):
    client,calls,replies,_=harness
    replies[('POST','/contacts/upsert')]=httpx.ReadTimeout('timeout')
    assert client.post('/api/crm/contacts',json={'email':'test@example.invalid'}).status_code==504
    assert len(calls)==1

def test_missing_saved_id_is_failure(harness):
    client,_,replies,_=harness
    replies[('POST','/contacts/upsert')]=(200,{'contact':{}})
    assert client.post('/api/crm/contacts',json={'email':'test@example.invalid'}).status_code==502

def test_partial_tag_failure_is_explicit(harness):
    client,_,replies,_=harness
    replies[('POST','/contacts/contact_a/tags')]=(500,{})
    r=client.post('/api/crm/contacts',json={'email':'test@example.invalid','tags':['new']})
    assert r.status_code==502 and r.json()['detail']['partial'] is True

def test_update_no_overwrite_tags(harness):
    client,calls,_,_=harness
    assert client.patch('/api/crm/contacts/contact_a',json={'tags':['new']}).status_code==422
    assert all(c[0]=='GET' for c in calls)

def test_invalid_pipeline_stage_rejected(harness):
    client,calls,_,_=harness
    assert client.patch('/api/crm/opportunities/opp_a/move',json={'pipelineStageId':'other'}).status_code==422
    assert all(c[0]=='GET' for c in calls)

def test_stage_move_calls_provider(harness):
    client,calls,_,_=harness
    assert client.patch('/api/crm/opportunities/opp_a/move',json={'pipelineStageId':'stage_a'}).status_code==200
    assert calls[-1][0:2]==('PUT','/opportunities/opp_a')

def test_send_acceptance_has_message_id(harness):
    client,calls,_,_=harness
    r=client.post('/api/crm/conversations/convo_a/messages',json={'body':'Test','type':'SMS'})
    assert r.status_code==200 and r.json()['accepted'] is True
    assert calls[-1][3]['contactId']=='contact_a' and calls[-1][3]['type']=='SMS'

def test_dnd_blocks_send(harness):
    client,calls,replies,_=harness
    replies[('GET','/contacts/contact_a')]=(200,{'contact':{**CONTACT,'dnd':True}})
    assert client.post('/api/crm/conversations/convo_a/messages',json={'body':'Test'}).status_code==409
    assert not any(c[1]=='/conversations/messages' for c in calls)

def test_email_requires_subject(harness):
    client,_,_,_=harness
    assert client.post('/api/crm/conversations/convo_a/messages',json={'body':'Test','type':'Email'}).status_code==422

def test_dialer_link_does_not_place_call(harness):
    client,calls,_,_=harness
    data=client.get('/api/crm/contacts/contact_a/dialer-link').json()['data']
    assert data=={'url':'tel:+15555550100','mode':'device_dialer','callPlaced':False}
    assert all(c[0]=='GET' for c in calls)
    assert client.post('/api/crm/contacts/contact_a/calls').status_code==501

def test_no_fabricated_connection_lifecycle(harness):
    client,_,_,_=harness
    assert client.post('/api/crm/connect',json={'apiKey':'example'}).status_code==501
    assert client.post('/api/crm/disconnect').status_code==501

def test_task_uses_contact_path(harness):
    client,calls,_,_=harness
    r=client.post('/api/crm/contacts/contact_a/tasks',json={'title':'Follow up','dueDate':'2026-10-01T12:00:00Z'})
    assert r.status_code==200 and calls[-1][1]=='/contacts/contact_a/tasks'
    assert client.get('/api/crm/tasks').status_code==422

def test_workflow_is_scoped(harness):
    client,calls,_,_=harness
    assert client.post('/api/crm/contacts/contact_a/workflows/other').status_code==404
    assert client.post('/api/crm/contacts/contact_a/workflows/workflow_a').status_code==200
    assert calls[-1][1]=='/contacts/contact_a/workflow/workflow_a'

def test_provider_shape_failure_not_empty_list(harness):
    client,_,replies,_=harness
    replies[('POST','/contacts/search')]=(200,{'unexpected':[]})
    assert client.get('/api/crm/contacts').status_code==502

def test_stats_do_not_invent_revenue(harness):
    client,_,_,_=harness
    r=client.get('/api/crm/stats')
    assert r.status_code==200 and r.json()['stats']['total_contacts']==1
    assert r.json()['stats']['revenue_mtd'] is None

def test_invalid_bridge_pagination_is_422(harness):
    client,calls,_,_=harness
    assert client.post('/api/mcp/crm',json={'action':'list_contacts','limit':'bad'}).status_code==422
    assert not calls

def test_cache_disabled_on_success_and_error(harness):
    client,_,_,_=harness
    assert 'no-store' in client.get('/api/crm/contacts').headers['cache-control']
    assert 'no-store' in client.get('/api/crm/contacts?limit=101').headers['cache-control']

def test_verified_session_uses_server_mapping_not_user_metadata(harness,monkeypatch):
    client,calls,replies,app=harness;app.dependency_overrides.clear()
    monkeypatch.setenv('SUPABASE_URL','https://auth.example.invalid')
    monkeypatch.setenv('SUPABASE_ANON_KEY','public-test-key')
    monkeypatch.setenv('CRM_TENANT_CONFIG',json.dumps({'user_a':{'locationId':'location_a','tokenEnv':'CRM_TEST_TOKEN'}}))
    monkeypatch.setenv('CRM_TEST_TOKEN','mapped-test-token')
    replies[('GET','/auth/v1/user')]=(200,{'id':'user_a','user_metadata':{'locationId':'attacker_location'}})
    r=client.get('/api/crm/contacts',headers={'authorization':'Bearer session-test'})
    assert r.status_code==200
    assert calls[-1][3]['locationId']=='location_a'
    assert calls[-1][4]['authorization']=='Bearer mapped-test-token'

def test_unmapped_verified_user_is_rejected(harness,monkeypatch):
    client,calls,replies,app=harness;app.dependency_overrides.clear()
    monkeypatch.setenv('SUPABASE_URL','https://auth.example.invalid')
    monkeypatch.setenv('SUPABASE_ANON_KEY','public-test-key')
    monkeypatch.setenv('CRM_TENANT_CONFIG','{}')
    replies[('GET','/auth/v1/user')]=(200,{'id':'user_a'})
    assert client.get('/api/crm/contacts',headers={'authorization':'Bearer session-test'}).status_code==403
    assert len(calls)==1
