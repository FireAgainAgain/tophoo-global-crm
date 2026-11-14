"""All visible navigation entries participate in module authorization."""
import json
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.modules import module_catalog_payload, normalize_module_keys
from app.main import app
from app.models import Plan, ProjectMember, SiteProject
from tests.test_global_access import db, headers


def grant(db, reads, writes):
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.permissions_json = json.dumps(reads)
    member.write_permissions_json = json.dumps(writes)
    db.commit()


@pytest.mark.parametrize('module,read,write', [
    ('url_navigation','/api/user-links','/api/user-links/categories'),
    ('ai_configuration','/api/ai-config/projects/1','/api/ai-config/projects/1/models'),
    ('mail_configuration','/api/mail/configuration','/api/mail/test-message'),
])
def test_no_access_and_readonly_are_enforced_on_personal_features(db, module, read, write):
    client = TestClient(app)
    context = {**headers(2), 'X-Project-ID': '1'}
    grant(db, [], [])
    assert client.get(read, headers=context).status_code == 403
    assert client.post(write, headers=context, json={}).status_code == 403
    # Dropping project context cannot restore access to a fully revoked module.
    assert client.get(read, headers=headers(2)).status_code == 403
    grant(db, [module], [])
    response = client.get(read, headers=context)
    assert response.status_code == 200
    if module == 'ai_configuration':
        assert response.json()['can_manage'] is False
    assert client.post(write, headers=context, json={}).status_code == 403
    grant(db, [module], [module])
    # Validation means the edit guard passed; no external services are called.
    response = client.post(write, headers=context, json={})
    assert response.status_code in {201, 422}


def test_url_readonly_can_export_and_cannot_modify_categories_or_links(db):
    client = TestClient(app)
    grant(db, ['url_navigation'], ['url_navigation'])
    category = client.post('/api/user-links/categories', headers=headers(2), json={'name':'Personal'}).json()
    link = client.post('/api/user-links', headers=headers(2), json={'name':'Private','url':'https://private.test','category_id':category['id']}).json()
    grant(db, ['url_navigation'], [])
    assert client.get('/api/user-links/export/pdf', headers=headers(2)).status_code == 200
    for method, path in [('PUT',f"/api/user-links/{link['id']}"),('DELETE',f"/api/user-links/{link['id']}"),
        ('POST',f"/api/user-links/{link['id']}/move"),('DELETE',f"/api/user-links/categories/{category['id']}")]:
        assert client.request(method,path,headers=headers(2),json={}).status_code == 403
    assert client.get('/api/user-links', headers=headers(1)).json()['items'] == []


def test_project_management_metadata_edit_does_not_grant_role_administration(db):
    client = TestClient(app)
    path = '/api/workspaces/1/projects/1'
    grant(db, [], [])
    assert client.get(path+'/export/md',headers=headers(2)).status_code == 403
    # Minimal project context must remain available for switching business modules.
    assert client.get('/api/workspaces/1/projects',headers=headers(2)).status_code == 200
    grant(db, ['project_management'], [])
    assert client.get(path+'/export/md',headers=headers(2)).status_code == 200
    assert client.patch(path,headers=headers(2),json={'name':'Denied'}).status_code == 403
    grant(db, ['project_management'], ['project_management'])
    assert client.patch(path,headers=headers(2),json={'name':'Allowed'}).status_code == 200
    assert db.get(SiteProject,1).name == 'Allowed'
    assert client.post(path+'/roles',headers=headers(2),json={'name':'Escalation','permissions':['leads']}).status_code == 403
    assert client.request('DELETE',path,headers=headers(2),json={'confirm_name':'Allowed'}).status_code == 403


def test_workspaces_can_disable_project_management_and_personal_navigation_even_for_owner(db):
    plan = db.get(Plan,1)
    plan.module_keys_json = '["leads"]'
    db.commit()
    client = TestClient(app)
    assert client.get('/api/workspaces/1/projects/1/roles',headers=headers(1)).status_code == 403
    assert client.get('/api/user-links',headers={**headers(1),'X-Project-ID':'1'}).status_code == 403
    assert normalize_module_keys([],include_base=True) == []


def test_role_catalog_contains_every_visible_sidebar_module_and_no_forced_base():
    sidebar = Path('app/templates/partials/sidebar.html').read_text(encoding='utf-8')
    buttons = re.findall(r'<button[^>]*data-crm-section="[^"]+"[^>]*>', sidebar)
    assert buttons and all('data-global-module=' in button or 'data-global-any-module=' in button for button in buttons)
    keys = set(re.findall(r'data-global-module="([^"]+)"',sidebar))
    catalog = module_catalog_payload()
    assert keys | {'rfq','quotations'} == {item['key'] for item in catalog}
    # Customer sales documents are opened from each customer's workspace.
    assert not any(item['is_base'] for item in catalog)


def test_project_header_is_authoritative_and_cannot_point_to_unjoined_project(db):
    client = TestClient(app)
    assert client.get('/api/user-links',headers={**headers(2),'X-Project-ID':'2'}).status_code == 403
    assert client.get('/api/user-links',headers={**headers(2),'X-Project-ID':'bad'}).status_code == 422
