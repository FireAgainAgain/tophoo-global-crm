import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import ProjectMember
from tests.test_global_access import db, headers

BASE = '/api/workspaces/1/projects/1'

@pytest.mark.parametrize('role', ['engineer', 'viewer', 'order'])
def test_reject_obsolete_assignments(db, role):
    response = TestClient(app).patch(BASE + '/members/1', headers=headers(1), json={'role': role})
    assert response.status_code == 422
    assert db.get(ProjectMember, 1).role == 'custom'


def test_two_roles_and_legacy_compatibility(db):
    client = TestClient(app)
    legacy = db.get(ProjectMember, 1)
    original = legacy.permissions_json
    assert client.get(BASE + '/members', headers=headers(1)).status_code == 200
    assert legacy.permissions_json == original
    assert client.post(BASE + '/roles', headers=headers(1), json={'name': 'Extra'}).status_code == 201
    assert client.patch(BASE + '/members/1', headers=headers(1), json={'role': 'sales', 'project_role_id': 99}).status_code == 400
    for role in ['sales', 'top_admin']:
        response = client.patch(BASE + '/members/1', headers=headers(1), json={'role': role})
        assert response.status_code == 200, response.text
        assert response.json()['role'] == role
        assert response.json()['project_role_id'] is None
    response = client.patch(BASE + '/members/1', headers=headers(1), json={'role': 'sales'})
    assert response.status_code == 400
