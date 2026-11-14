"""Manual research remains independent and survives conversion and merging."""
import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from app.main import app
from app.models import Customer, Lead, LeadConversionHistory, ProjectMember
from app.services.manual_research import ensure_manual_research_schema
from tests.test_global_access import db, headers


@pytest.mark.parametrize('reviewed', [False, True])
def test_review_survives_conversion_and_partial_edits(db, reviewed):
    client = TestClient(app)
    lead = client.post('/api/customer-workflow/projects/1/leads', headers=headers(2), json={
        'company_name':'Review buyer','is_manually_researched':reviewed}).json()
    url = f"/api/customer-workflow/projects/1/leads/{lead['id']}"
    assert lead['is_manually_researched'] is reviewed
    assert client.put(url, headers=headers(2), json={'company_name':'Review buyer'}).json()['is_manually_researched'] is reviewed
    result = client.post(url+'/to-customers', headers=headers(2))
    assert result.status_code == 200, result.text
    cid = result.json()['customer_id']
    assert db.get(Customer,cid).is_manually_researched is reviewed
    snapshot = db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==cid))
    assert json.loads(snapshot.snapshot_json)['is_manually_researched'] is reviewed
    customer_url = f'/api/contacts/projects/1/{cid}'
    saved = client.patch(customer_url+'/manual-research', headers=headers(2), json={'is_manually_researched':not reviewed})
    assert saved.status_code == 200, saved.text
    assert saved.json()['is_manually_researched'] is not reviewed
    assert client.put(customer_url, headers=headers(2), json={'company_name':'Review buyer'}).json()['is_manually_researched'] is not reviewed
    assert client.get('/api/contacts/projects/1', headers=headers(2)).json()['customers'][0]['is_manually_researched'] is not reviewed


@pytest.mark.parametrize('existing,incoming', [(False,True),(True,False),(False,False),(True,True)])
def test_batch_merge_retains_review_if_either_is_reviewed(db, existing, incoming):
    client = TestClient(app)
    data = {'company_name':'Merge buyer','company_website':'https://merge.example.test'}
    customer = client.post('/api/contacts/projects/1', headers=headers(2), json={**data,'is_manually_researched':existing}).json()
    lead = client.post('/api/customer-workflow/projects/1/leads', headers=headers(2), json={**data,'is_manually_researched':incoming}).json()
    result = client.post('/api/customer-workflow/projects/1/leads/batch/to-customers', headers=headers(2), json={'ids':[lead['id']]})
    assert result.status_code == 200, result.text
    assert db.get(Customer,customer['id']).is_manually_researched is (existing or incoming)


@pytest.mark.parametrize('kind', ['leads','customers'])
def test_updates_are_strict_scoped_and_permission_checked(db, kind):
    client = TestClient(app)
    base = '/api/customer-workflow/projects/1/leads' if kind=='leads' else '/api/contacts/projects/1'
    item = client.post(base, headers=headers(2), json={'company_name':'Private buyer','notes':'Unchanged'}).json()
    url = f"{base}/{item['id']}/manual-research"
    assert item['is_manually_researched'] is False
    saved = client.patch(url, headers=headers(2), json={'is_manually_researched':True})
    assert saved.status_code == 200, saved.text
    assert saved.json()['notes']=='Unchanged' and saved.json()['added_at']==item['added_at']
    assert client.patch(url, headers=headers(2), json={'is_manually_researched':'false'}).status_code == 422
    assert client.patch(url.replace('/projects/1/','/projects/2/'), headers=headers(1), json={'is_manually_researched':False}).status_code == 404
    owner = client.post(base, headers=headers(1), json={'company_name':'Owner buyer'}).json()
    assert client.patch(f"{base}/{owner['id']}/manual-research", headers=headers(2), json={'is_manually_researched':True}).status_code == 404
    member = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.role='viewer';db.commit()
    assert client.patch(url, headers=headers(2), json={'is_manually_researched':False}).status_code == 403
    assert db.get(Lead if kind=='leads' else Customer,item['id']).is_manually_researched is True


def test_schema_upgrade_is_repeatable_and_never_resets_flags():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        for table in ('crm_leads','crm_customers'):
            conn.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
            conn.execute(text(f'INSERT INTO {table} VALUES (1)'))
    ensure_manual_research_schema(engine)
    with engine.begin() as conn:
        for table in ('crm_leads','crm_customers'):
            assert conn.scalar(text(f'SELECT is_manually_researched FROM {table}')) == 0
            conn.execute(text(f'UPDATE {table} SET is_manually_researched=1'))
    ensure_manual_research_schema(engine)
    with engine.connect() as conn:
        for table in ('crm_leads','crm_customers'):
            assert conn.scalar(text(f'SELECT is_manually_researched FROM {table}')) == 1
    engine.dispose()
