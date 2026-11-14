"""Read/edit grants apply to actual HTTP writes and survive role reassignment."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import ProjectMember, ProjectRole
from tests.test_global_access import db, headers

BASE = '/api/workspaces/1/projects/1'


def set_access(db, reads, writes):
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.permissions_json = json.dumps(reads)
    member.write_permissions_json = json.dumps(writes)
    db.commit()
    return member


@pytest.mark.parametrize('path,method', [
    ('/api/contacts/projects/1', 'post'),
    ('/api/customer-workflow/projects/1/leads', 'post'),
    ('/api/customer-workflow/projects/1/leads/999/to-customers', 'post'),
    ('/api/acquisition/projects/1/tasks', 'post'),
    ('/api/acquisition/projects/1/results/delete', 'post'),
    ('/api/followups/projects/1/customers/999', 'post'),
    ('/api/contacts/projects/1/999/records', 'post'),
    ('/api/rfqs/projects/1', 'post'),
    ('/api/competitors/projects/1', 'post'),
    ('/api/communication-scripts/projects/1/categories', 'post'),
    ('/api/keywords/projects/1/categories', 'post'),
    ('/api/mic-products/projects/1/999', 'delete'),
])
def test_read_only_blocks_mutations_before_handler_or_missing_object(db, path, method):
    from app.core.modules import PROJECT_MODULES
    set_access(db, sorted(PROJECT_MODULES), [])
    response = TestClient(app).request(method, path, headers=headers(2), json={})
    assert response.status_code == 403, (path, response.text)
    assert '只读' in response.json()['detail']


def test_mixed_permissions_sync_immediately_and_cannot_grant_edit_without_read(db):
    client = TestClient(app)
    role = client.post(BASE+'/roles', headers=headers(1), json={
        'name': 'Research editor', 'permissions': ['contacts', 'knowledge_base'],
        'write_permissions': ['knowledge_base'],
    }).json()
    member = set_access(db, [], [])
    response = client.patch(BASE+f'/members/{member.id}', headers=headers(1), json={
        'role': 'custom', 'project_role_id': role['id'], 'write_permissions': ['contacts'],
    })
    assert response.status_code == 200
    assert response.json()['write_permissions'] == ['knowledge_base']
    assert client.get('/api/contacts/projects/1', headers=headers(2)).status_code == 200
    assert client.post('/api/contacts/projects/1', headers=headers(2), json={}).status_code == 403
    assert client.post('/api/communication-scripts/projects/1/categories', headers=headers(2), json={'name': 'Can edit'}).status_code == 201
    response = client.put(BASE+f"/roles/{role['id']}", headers=headers(1), json={
        'name': 'Research viewer', 'permissions': ['contacts', 'knowledge_base'], 'write_permissions': [],
    })
    assert response.status_code == 200
    assert client.post('/api/communication-scripts/projects/1/categories', headers=headers(2), json={'name': 'Denied'}).status_code == 403
    assert client.get('/api/workspaces/1/projects', headers=headers(2)).json()[0]['write_permissions'] == []
    response = client.put(BASE+f"/roles/{role['id']}", headers=headers(1), json={
        'name': 'Invalid', 'permissions': ['contacts'], 'write_permissions': ['knowledge_base'],
    })
    assert response.status_code == 422
    db.expire_all()
    assert db.get(ProjectRole, role['id']).name == 'Research viewer'


def test_legacy_editors_and_viewers_keep_access_and_personal_keys_are_independent(db):
    client = TestClient(app)
    member = set_access(db, ['contacts'], [])
    assert client.put('/api/acquisition/projects/1/connections/tavily', headers=headers(2), json={'api_key': 'fixture-user-2-key'}).status_code == 200
    assert client.post('/api/acquisition/projects/1/connections/tavily/reveal', headers=headers(2)).json()['api_key'] == 'fixture-user-2-key'
    assert client.get('/api/acquisition/projects/1/sources', headers=headers(1)).json()['sources'][0]['configured'] is False
    member.write_permissions_json = None
    db.commit()
    assert client.post('/api/contacts/projects/1', headers=headers(2), json={'company_name': 'Legacy editor'}).status_code == 201
    member.role = 'viewer'
    db.commit()
    assert client.get('/api/contacts/projects/1', headers=headers(2)).status_code == 200
    assert client.post('/api/contacts/projects/1', headers=headers(2), json={}).status_code == 403


def test_visits_record_only_foreground_project_and_self_with_utc_and_throttling(db):
    client = TestClient(app)
    member = set_access(db, ['contacts'], [])
    assert member.last_accessed_at is None
    client.get('/api/contacts/projects/1', headers=headers(2))
    client.get('/api/workspaces/1/projects', headers=headers(2))
    db.refresh(member)
    assert member.last_accessed_at is None
    assert client.post('/api/projects/1/visit', headers=headers(2)).status_code == 200
    db.refresh(member)
    first = member.last_accessed_at
    assert abs((datetime.now(timezone.utc).replace(tzinfo=None)-first).total_seconds()) < 5
    result = client.get(BASE+'/members', headers=headers(1)).json()
    assert result['members'][0]['last_accessed_at'].endswith('+00:00')
    client.post('/api/projects/1/visit', headers=headers(2))
    db.refresh(member)
    assert member.last_accessed_at == first
    member.last_accessed_at = first-timedelta(minutes=2)
    db.commit()
    client.post('/api/projects/1/visit', headers=headers(2))
    db.refresh(member)
    assert member.last_accessed_at >= first
    assert client.post('/api/projects/2/visit', headers=headers(2)).status_code == 403
    assert client.post('/api/projects/1/visit').status_code == 401
