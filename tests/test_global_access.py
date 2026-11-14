"""Integration checks for unified permissions and project data deletion."""
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.core.database import get_db
from app.core.modules import MODULE_CATALOG, CRM_CUSTOMER_MODULES
from app.core.security import create_access_token
from app.models import Base, User, Workspace, WorkspaceMember, Plan, SiteProject, ProjectMember, Keyword
from app.services.global_project_data import delete_all_project_data


@pytest.fixture
def db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([
            User(id=1,email='owner@example.test',password_hash='unused',display_name='Owner',is_admin=False),
            User(id=2,email='sales@example.test',password_hash='unused',display_name='Sales',is_admin=False),
            Plan(id=1,code='test',name='Test',description='Test',module_keys_json=json.dumps(list(MODULE_CATALOG))),
            Workspace(id=1,name='Test',owner_id=1,plan_id=1),
            WorkspaceMember(workspace_id=1,user_id=1,role='owner'),
            WorkspaceMember(workspace_id=1,user_id=2,role='member'),
            SiteProject(id=1,workspace_id=1,name='Demo',site_url='https://demo.example.test'),
            SiteProject(id=2,workspace_id=1,name='Example Studio',site_url='https://studio.example.test'),
            ProjectMember(site_project_id=1,user_id=2,role='custom',permissions_json='["contacts", "project_management", "url_navigation", "ai_configuration", "mail_configuration"]'),
        ])
        session.commit()
        app.dependency_overrides[get_db] = lambda: session
        yield session
        app.dependency_overrides.clear()
    engine.dispose()


def headers(user_id):
    return {'Authorization':'Bearer '+create_access_token(user_id)}


def test_owner_can_use_seo_but_crm_role_cannot(db):
    client = TestClient(app)
    assert client.get('/api/keywords/projects/1/categories',headers=headers(1)).status_code == 200
    assert client.get('/api/keywords/projects/1/categories',headers=headers(2)).status_code == 403
    assert client.get('/api/market-research/projects/1',headers=headers(2)).status_code == 404
    assert client.get('/api/product-tdk/projects/1',headers=headers(2)).status_code == 404
    assert client.get('/api/gsc/projects/1/action-tasks',headers=headers(2)).status_code == 404


def test_non_member_cannot_access_other_project_or_manage_roles(db):
    client = TestClient(app)
    assert client.get('/api/keywords/projects/2/categories',headers=headers(2)).status_code == 403
    assert client.get('/api/workspaces/1/projects/1/roles',headers=headers(2)).status_code == 403
    assert client.get('/api/workspaces/1/projects/1/roles',headers=headers(1)).status_code == 200


def test_workspace_profile_is_an_upper_bound_even_for_owner(db):
    db.get(Plan,1).module_keys_json='["contacts"]'
    db.commit()
    client=TestClient(app)
    assert client.get('/api/keywords/projects/1/categories',headers=headers(1)).status_code == 403
    response=client.get('/api/workspaces/1/projects',headers=headers(1))
    assert response.status_code == 200
    assert response.json()[0]['permissions'] == sorted(CRM_CUSTOMER_MODULES)


def test_project_delete_removes_keywords_and_keeps_other_project(db):
    db.add_all([Keyword(site_project_id=1,keyword='a',normalized_keyword='a'),Keyword(site_project_id=2,keyword='b',normalized_keyword='b')])
    db.commit()
    delete_all_project_data(db,1)
    db.commit()
    assert [item.keyword for item in db.scalars(select(Keyword)).all()] == ['b']
