"""CRM leaf grants are enforced at HTTP boundaries, including cross-list transfers."""
import json
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.modules import CRM_CUSTOMER_MODULES, normalize_module_keys
from app.dependencies.auth import member_permissions, member_write_permissions
from app.models import ProjectMember, Plan
from tests.test_global_access import db, headers

READS = {
    'communication_assistant': '/api/communication/projects/1/catalog',
    'auto_prospecting': '/api/acquisition/projects/1/results',
    'leads': '/api/customer-workflow/projects/1/leads',
    'customer_list': '/api/contacts/projects/1',
    'customer_pool': '/api/customer-workflow/projects/1/pool',
}
WRITES = {
    'communication_assistant': ('PUT', '/api/communication/projects/1/entities/customers/999'),
    'auto_prospecting': ('POST', '/api/acquisition/projects/1/records'),
    'leads': ('POST', '/api/customer-workflow/projects/1/leads'),
    'customer_list': ('POST', '/api/contacts/projects/1'),
    'customer_pool': ('POST', '/api/customer-workflow/projects/1/pool/999/restore'),
}


def grant(db, reads, writes=()):
    member = db.get(ProjectMember, 1)
    member.permissions_json = json.dumps(list(reads))
    member.write_permissions_json = json.dumps(list(writes))
    db.commit()
    return member


@pytest.mark.parametrize('module', CRM_CUSTOMER_MODULES)
def test_each_page_is_independent(db, module):
    grant(db, [module])
    client = TestClient(app)
    for key, path in READS.items():
        response = client.get(path, headers=headers(2))
        assert response.status_code == (200 if key == module else 403), (module, key, response.text)
    # Direct API access must enforce read-only even if the UI is bypassed.
    for key, (method, path) in WRITES.items():
        response = client.request(method, path, headers=headers(2), json={})
        assert response.status_code == 403, (module, key, response.text)


def test_legacy_read_write_and_empty_grants(db):
    member = grant(db, ['contacts'], ['contacts'])
    assert member_permissions(member) == set(CRM_CUSTOMER_MODULES)
    assert member_write_permissions(member) == set(CRM_CUSTOMER_MODULES)
    member = grant(db, ['contacts'])
    assert member_permissions(member) == set(CRM_CUSTOMER_MODULES)
    assert member_write_permissions(member) == set()
    assert normalize_module_keys(['customer_list']) == ['customer_list']
    assert normalize_module_keys([]) == []


def test_role_edit_removes_one_page_without_affecting_the_others(db):
    client = TestClient(app)
    response = client.post('/api/workspaces/1/projects/1/roles', headers=headers(1), json={'name':'CRM', 'permissions':['contacts'], 'write_permissions':['contacts']})
    assert response.status_code == 201, response.text
    role = response.json()
    assert set(role['permissions']) == set(CRM_CUSTOMER_MODULES)
    response = client.patch('/api/workspaces/1/projects/1/members/1', headers=headers(1), json={'role':'custom','project_role_id':role['id']})
    assert response.status_code == 200
    remaining = [key for key in CRM_CUSTOMER_MODULES if key != 'customer_pool']
    response = client.put(f"/api/workspaces/1/projects/1/roles/{role['id']}", headers=headers(1), json={'name':'CRM', 'permissions':remaining, 'write_permissions':['leads']})
    assert response.status_code == 200
    assert client.get(READS['customer_pool'], headers=headers(2)).status_code == 403
    assert client.get(READS['leads'], headers=headers(2)).status_code == 200
    response = client.post(WRITES['leads'][1],headers=headers(2),json={'company_name':'Allowed lead'})
    assert response.status_code == 201, response.text
    assert client.post(WRITES['customer_list'][1],headers=headers(2),json={'company_name':'Blocked customer'}).status_code == 403


def test_transfers_require_destination_edit_and_plan_stays_upper_bound(db):
    grant(db, CRM_CUSTOMER_MODULES, ['leads','auto_prospecting'])
    client = TestClient(app)
    assert client.post('/api/customer-workflow/projects/1/leads/999/to-customers', headers=headers(2), json={}).status_code == 403
    grant(db, CRM_CUSTOMER_MODULES, ['customer_list'])
    assert client.post('/api/contacts/projects/1/999/release', headers=headers(2), json={'reason':'test'}).status_code == 403
    db.get(Plan,1).module_keys_json = '["customer_list"]'
    db.commit()
    assert client.get(READS['leads'], headers=headers(1)).status_code == 403
    assert client.get(READS['customer_list'], headers=headers(1)).status_code == 200


@pytest.mark.parametrize('module,method,path,allowed', [
    ('communication_assistant', 'PUT', '/api/communication/projects/1/entities/customers/999', 422),
    ('auto_prospecting', 'DELETE', '/api/acquisition/projects/1/jobs/999', 404),
    ('leads', 'POST', '/api/customer-workflow/projects/1/leads', 422),
    ('customer_list', 'POST', '/api/contacts/projects/1', 422),
    ('customer_pool', 'DELETE', '/api/customer-workflow/projects/1/pool/999', 404),
])
def test_edit_grant_only_unlocks_its_own_module(db, module, method, path, allowed):
    client = TestClient(app)
    grant(db, CRM_CUSTOMER_MODULES, [module])
    response = client.request(method, path, headers=headers(2), json={})
    assert response.status_code == allowed, response.text
    for other, (other_method, other_path) in WRITES.items():
        if other != module:
            assert client.request(other_method, other_path, headers=headers(2), json={}).status_code == 403


def test_acquisition_cannot_convert_without_lead_edit(db):
    grant(db, ['auto_prospecting'], ['auto_prospecting'])
    response = TestClient(app).post('/api/acquisition/projects/1/candidates/actions', headers=headers(2), json={'ids':[999], 'action':'to-leads'})
    assert response.status_code == 403
