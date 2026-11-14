"""Regression coverage for the eight integration audit findings."""
import json
import pytest
from contextlib import nullcontext
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import ProjectMember, Keyword
from app.dependencies.auth import require_project_write
from fastapi import HTTPException
from tests.test_global_access import db, headers




@pytest.mark.parametrize('method,path,payload', [
    ('POST','/api/keywords/projects/1/categories',{'name':'Blocked'}),
    ('DELETE','/api/keywords/projects/1/categories/1',None),
    ('POST','/api/keywords/projects/1/keywords/bulk-delete',{'keyword_ids':[1]}),
])
def test_viewer_write_guard_covers_all_seo_routers(db,method,path,payload):
    from app.core.modules import PROJECT_MODULES
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2))
    member.role='viewer'; member.permissions_json=json.dumps(list(PROJECT_MODULES))
    db.commit()
    assert TestClient(app).request(method,path,headers=headers(2),json=payload).status_code==403




def test_delete_cleans_historical_children_but_keeps_other_project(db):
    from sqlalchemy import text
    from app.services.project_service import delete_project_cascade
    for sql in [
        'CREATE TABLE crm_selection_tasks (id INTEGER PRIMARY KEY, site_project_id INTEGER REFERENCES site_projects(id))',
        'CREATE TABLE crm_selection_options (id INTEGER PRIMARY KEY, selection_task_id INTEGER REFERENCES crm_selection_tasks(id))',
        'CREATE TABLE crm_prospecting_job_events (id INTEGER PRIMARY KEY, site_project_id INTEGER REFERENCES site_projects(id))',
        'CREATE TABLE crm_prospecting_schedules (id INTEGER PRIMARY KEY, site_project_id INTEGER REFERENCES site_projects(id))',
        'CREATE TABLE competitors (id INTEGER PRIMARY KEY, site_project_id INTEGER REFERENCES site_projects(id))',
    ]: db.execute(text(sql))
    db.commit();db.execute(text('PRAGMA foreign_keys=ON'))
    for name in ('crm_selection_tasks','crm_prospecting_job_events','crm_prospecting_schedules','competitors'):
        db.execute(text(f'INSERT INTO {name} (id,site_project_id) VALUES (1,1),(2,2)'))
    db.execute(text('INSERT INTO crm_selection_options (id,selection_task_id) VALUES (1,1),(2,2)'))
    db.commit();delete_project_cascade(db,1);db.commit()
    for name in ('crm_selection_tasks','crm_selection_options','crm_prospecting_job_events','crm_prospecting_schedules','competitors'):
        assert db.execute(text(f'SELECT id FROM {name}')).scalars().all()==[2],name


def test_delete_full_project_graph_preserves_other_project_and_workspace_masters(db):
    from sqlalchemy import text
    from app.models import Base, Customer, ProjectContact, ProspectingEntry, ProspectingJob, Lead, AiModelConfiguration, AiFeatureBinding, CommunicationScriptCategory, CommunicationScript, Keyword, SiteProject
    from app.services.project_service import delete_project_cascade
    db.execute(text('PRAGMA foreign_keys=ON'))
    db.add(Customer(id=1, workspace_id=1, name='Shared customer'))
    db.add(CommunicationScriptCategory(id=1,site_project_id=1,name='Notes'))
    db.add(AiModelConfiguration(id=1,owner_user_id=1,site_project_id=1,name='Audit model',model='unused',base_url='https://example.test'))
    db.flush()
    db.add_all([
        ProjectContact(site_project_id=1,contact_id=1), ProjectContact(site_project_id=2,contact_id=1),
        ProspectingEntry(site_project_id=1,owner_user_id=1,company_name='Delete this'),
        ProspectingEntry(site_project_id=2,owner_user_id=1,company_name='Keep this'),
        ProspectingJob(site_project_id=1,owner_user_id=1), Lead(site_project_id=1,company_name='Delete lead'),
        AiFeatureBinding(owner_user_id=1,site_project_id=1,feature_key='audit',model_configuration_id=1),
        CommunicationScript(site_project_id=1,category_id=1,title='Audit',content='Note'),
        Keyword(site_project_id=1,keyword='a',normalized_keyword='a'),
        Keyword(site_project_id=2,keyword='b',normalized_keyword='b'),
    ])
    db.commit()
    delete_project_cascade(db,1)
    db.commit()
    assert db.get(Customer,1) is not None
    assert db.get(SiteProject,2) is not None
    assert db.scalar(select(ProjectContact)).site_project_id==2
    assert db.scalar(select(ProspectingEntry)).site_project_id==2
    assert db.scalar(select(Keyword)).site_project_id==2
    for table in Base.metadata.tables.values():
        if 'site_project_id' in table.c:
            assert not db.execute(select(table).where(table.c.site_project_id==1)).first(), table.name






@pytest.fixture(autouse=True)
def isolate_research_helpers(db, monkeypatch):
    # Legacy research serialization bypasses get_db; prevent real-DB reads.
    monkeypatch.setattr('app.core.database.SessionLocal', lambda: nullcontext(db))




def test_viewer_with_module_cannot_write_seo(db):
    member = db.scalar(select(ProjectMember).where(ProjectMember.user_id == 2))
    member.role = 'viewer'
    member.permissions_json = '["keyword_library","market_research"]'
    db.commit()
    from app.models import User, KeywordCategory
    db.add(KeywordCategory(id=1, site_project_id=1, name='Audit category'))
    db.commit()
    try:
        require_project_write(1, db.get(User, 2), db)
    except HTTPException as error:
        assert error.status_code == 403
    else:
        raise AssertionError('Fixture is not read-only')
    client = TestClient(app)
    keyword = client.post('/api/keywords/projects/1/keywords', headers=headers(2), json={'keyword':'audit only in memory','category_id':1})
    research = client.put('/api/market-research/projects/1', headers=headers(2), json={'data':{'product':{'name':'audit only in memory'}}})
    assert keyword.status_code == 403
    assert research.status_code == 404
    assert not db.scalar(select(Keyword).where(Keyword.keyword == 'audit only in memory'))
    assert client.get('/api/keywords/projects/1/categories', headers=headers(2)).status_code == 200


def test_legacy_seo_link_redirect_requests_global_section(db):
    response = TestClient(app).get('/seo', follow_redirects=False)
    assert response.status_code == 404




def test_project_delete_cleans_prospects_and_legacy_suppliers_with_foreign_keys(db):
    from sqlalchemy import text
    from app.models import ProspectingEntry
    from app.services.project_service import delete_project_cascade
    db.execute(text('PRAGMA foreign_keys=ON'))
    db.execute(text('CREATE TABLE crm_suppliers (id INTEGER PRIMARY KEY, site_project_id INTEGER REFERENCES site_projects(id))'))
    db.execute(text('INSERT INTO crm_suppliers VALUES (1, 1), (2, 2)'))
    db.add(ProspectingEntry(site_project_id=1,owner_user_id=1,company_name='Audit prospect'))
    db.commit()
    delete_project_cascade(db,1)
    db.commit()
    assert not db.scalar(select(ProspectingEntry))
    assert db.scalars(text("SELECT site_project_id FROM crm_suppliers")).all() == [2]


def test_project_delete_without_foreign_keys_leaves_no_orphan_prospect(db):
    from app.models import ProspectingEntry, SiteProject
    from app.services.project_service import delete_project_cascade
    db.add(ProspectingEntry(site_project_id=1,owner_user_id=1,company_name='Audit prospect'))
    db.commit()
    delete_project_cascade(db,1)
    db.commit()
    assert db.get(SiteProject,1) is None
    assert not db.scalar(select(ProspectingEntry))
