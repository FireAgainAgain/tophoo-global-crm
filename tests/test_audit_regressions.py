"""Regression coverage for the 2026-10-30 permissions and module audit."""
import json
from pathlib import Path
from xml.etree.ElementTree import ParseError

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.modules import normalize_module_keys
from app.core.security import hash_password
from app.main import app
from app.models import Plan, ProjectMember, User
from app.services.billing_service import plan_modules
from tests.test_global_access import db, headers


def grants(db, reads, writes):
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.permissions_json = json.dumps(reads)
    member.write_permissions_json = json.dumps(writes)
    db.commit()


def test_disabled_account_cannot_obtain_token_or_cookie(db):
    user = db.get(User, 2)
    user.email = 'disabled@example.com'
    user.password_hash = hash_password('ValidPassword2026')
    user.is_active = False
    db.commit()
    response = TestClient(app).post('/api/auth/login', json={
        'email': user.email, 'password': 'ValidPassword2026',
    })
    assert response.status_code == 401
    assert 'access_token' not in response.json()
    assert 'set-cookie' not in response.headers


@pytest.mark.parametrize('stored', ['{"leads":true}', '42', '"leads"', '[{}, [], "leads"]', 'null'])
def test_malformed_permission_json_is_safe_and_never_uses_object_keys(db, stored):
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.permissions_json = stored
    member.write_permissions_json = stored
    db.commit()
    response = TestClient(app).get('/api/customer-workflow/projects/1/leads', headers=headers(2))
    assert response.status_code == (200 if stored.startswith('[') else 403)
    assert normalize_module_keys({'leads': True}) == []
    plan = db.get(Plan, 1)
    plan.module_keys_json = stored
    assert plan_modules(plan) == (['leads'] if stored.startswith('[') else [])


@pytest.mark.parametrize('kind,module', [('leads', 'leads'), ('customers', 'customer_list')])
def test_clock_cannot_bypass_entity_module_read_or_write(db, kind, module):
    client = TestClient(app)
    if kind == 'leads':
        item = client.post('/api/customer-workflow/projects/1/leads', headers=headers(2), json={'company_name': 'Private lead'}).json()
    else:
        item = client.post('/api/contacts/projects/1', headers=headers(2), json={'company_name': 'Private customer'}).json()
    endpoint = f'/api/communication/projects/1/entities/{kind}/{item["id"]}'
    grants(db, ['communication_assistant'], ['communication_assistant'])
    assert client.get('/api/communication/projects/1/catalog', headers=headers(2)).status_code == 200
    assert client.get(endpoint, headers=headers(2)).status_code == 403
    payload = {'country': 'GB', 'timezone': 'Europe/London'}
    assert client.put(endpoint, headers=headers(2), json=payload).status_code == 403
    grants(db, ['communication_assistant', module], ['communication_assistant'])
    response = client.get(endpoint, headers=headers(2))
    assert response.status_code == 200 and response.json()['can_edit'] is False
    assert client.put(endpoint, headers=headers(2), json=payload).status_code == 403
    assert client.delete(endpoint, headers=headers(2)).status_code == 403
    grants(db, ['communication_assistant', module], ['communication_assistant', module])
    assert client.put(endpoint, headers=headers(2), json=payload).status_code == 200


def test_clock_related_customer_list_requires_customer_permission(db):
    grants(db, ['communication_assistant'], [])
    response = TestClient(app).get('/api/communication/projects/1/related-customers',
        params={'key': 'US:America/New_York'}, headers=headers(2))
    assert response.status_code == 403






