"""Contact switches preserve lead details, dates and project ownership."""
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from app.main import app
from app.models import Lead, ProjectMember
from app.services.lead_contact_status import ensure_lead_contact_status_schema
from tests.test_global_access import db, headers


def test_toggle_persists_without_resetting_details_or_added_date(db):
    client=TestClient(app)
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(1),json={'company_name':'Test coil buyer','email':'buyer@example.test','notes':'Keep notes'}).json()
    assert lead['is_contacted'] is False
    original_date=datetime(2026,8,1,10)
    db.get(Lead,lead['id']).created_at=original_date
    db.commit()
    url=f"/api/customer-workflow/projects/1/leads/{lead['id']}/contact-status"
    response=client.patch(url,headers=headers(1),json={'is_contacted':True})
    assert response.status_code==200
    saved=response.json()
    assert saved['is_contacted'] is True
    assert saved['added_at']==original_date.isoformat()
    assert saved['email']=='buyer@example.test' and saved['notes']=='Keep notes'
    edited=client.put(url.removesuffix('/contact-status'),headers=headers(1),json={'company_name':'Renamed buyer'}).json()
    assert edited['is_contacted'] is True
    assert client.get('/api/customer-workflow/projects/1/leads',headers=headers(1)).json()['items'][0]['is_contacted'] is True
    assert client.patch(url,headers=headers(1),json={'is_contacted':False}).json()['is_contacted'] is False
    assert client.patch(url,headers=headers(1),json={'is_contacted':'false'}).status_code==422


def test_switch_respects_project_owner_and_read_only_access(db):
    client=TestClient(app)
    owned=client.post('/api/customer-workflow/projects/1/leads',headers=headers(1),json={'company_name':'Owner lead'}).json()
    personal=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={'company_name':'Sales lead'}).json()
    url=lambda project,lead:f'/api/customer-workflow/projects/{project}/leads/{lead}/contact-status'
    assert client.patch(url(1,owned['id']),headers=headers(2),json={'is_contacted':True}).status_code==404
    assert client.patch(url(2,owned['id']),headers=headers(1),json={'is_contacted':True}).status_code==404
    assert client.patch(url(1,personal['id']),headers=headers(2),json={'is_contacted':True}).status_code==200
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.role='viewer';db.commit()
    assert client.patch(url(1,personal['id']),headers=headers(2),json={'is_contacted':False}).status_code==403
    assert db.get(Lead,personal['id']).is_contacted is True


def test_schema_upgrade_preserves_existing_rows_and_is_repeatable():
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY, company_name TEXT)'))
        connection.execute(text("INSERT INTO crm_leads VALUES (1,'Existing buyer')"))
    ensure_lead_contact_status_schema(engine)
    ensure_lead_contact_status_schema(engine)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT company_name,is_contacted FROM crm_leads')).one()==('Existing buyer',0)
    assert 'is_contacted' in {x['name'] for x in inspect(engine).get_columns('crm_leads')}
    engine.dispose()


@pytest.mark.parametrize('value,expected', [
    ('unviewed','unviewed'), ('ready','unviewed'), ('low_match','unviewed'),
    ('contacted','contacted'), ('company_contacted','contacted'), ('replied','priority_developing'),
    ('unfit','unviewed'), ('priority_developing','priority_developing'),
])
def test_review_status_persists_and_does_not_change_customer_fields(db,value,expected):
    client=TestClient(app)
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={'company_name':'Status buyer','notes':'Preserve company notes'}).json()
    assert lead['workflow_status']=='unviewed'
    url=f"/api/customer-workflow/projects/1/leads/{lead['id']}/status"
    item=db.get(Lead,lead['id'])
    item.workflow_status=value
    db.commit()
    assert client.get(url.removesuffix('/status'),headers=headers(2)).json()['workflow_status']==expected
    assert db.get(Lead,lead['id']).workflow_status==value
    saved=client.patch(url,headers=headers(2),json={'workflow_status':value})
    assert saved.status_code==200,saved.text
    assert saved.json()['workflow_status']==expected
    assert saved.json()['is_contacted']==(expected in ('contacted','priority_developing'))
    assert saved.json()['added_at']==lead['added_at']
    assert saved.json()['notes']==lead['notes']
    assert client.patch(url,headers=headers(2),json={'workflow_status':'invalid'}).status_code==422
    assert client.patch(url,headers=headers(2),json={'workflow_status':'fake'}).status_code==422
    converted=client.post(url.removesuffix('/status')+'/to-customers',headers=headers(2))
    assert converted.status_code==200,converted.text
    customer=client.get(f"/api/contacts/projects/1/{converted.json()['customer_id']}/preview",headers=headers(2)).json()
    assert customer['workflow_status'] == '' and 'is_contacted' not in customer


def test_review_status_requires_project_owner_and_write_permission(db):
    client=TestClient(app)
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(1),json={'company_name':'Owner buyer'}).json()
    url=f"/api/customer-workflow/projects/1/leads/{lead['id']}/status"
    assert client.patch(url,headers=headers(2),json={'workflow_status':'checking'}).status_code==404
    assert client.patch(url.replace('/projects/1/','/projects/2/'),headers=headers(1),json={'workflow_status':'checking'}).status_code==404
    personal=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={'company_name':'Personal buyer'}).json()
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2));member.role='viewer';db.commit()
    assert client.patch(f"/api/customer-workflow/projects/1/leads/{personal['id']}/status",headers=headers(2),json={'workflow_status':'checked'}).status_code==403
    assert db.get(Lead,personal['id']).workflow_status=='unviewed'


def test_retired_priority_is_not_selectable_and_legacy_read_preserves_contact_fact(db):
    client=TestClient(app)
    lead=client.post('/api/customer-workflow/projects/1/leads',headers=headers(2),json={'company_name':'Priority prospect'}).json()
    url=f"/api/customer-workflow/projects/1/leads/{lead['id']}/status"
    assert client.patch(url,headers=headers(2),json={'workflow_status':'priority'}).status_code==422
    for contacted in (False,True):
        item=db.get(Lead,lead['id']);item.workflow_status='priority';item.is_contacted=contacted;db.commit()
        result=client.get('/api/customer-workflow/projects/1/leads',headers=headers(2)).json()['items'][0]
        assert result['workflow_status']==('contacted' if contacted else 'unviewed')
        assert result['is_contacted']==contacted
    result=client.patch(url,headers=headers(2),json={'workflow_status':'checking'}).json()
    assert result['workflow_status']=='unviewed' and result['is_contacted'] is False


def test_merge_already_migrated_checking_rows_is_idempotent():
    from app.services.lead_contact_status import unify_lead_status_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY,workflow_status TEXT,is_contacted BOOLEAN,status_schema_version INTEGER)'))
        conn.execute(text("INSERT INTO crm_leads VALUES (1,'checking',0,2),(2,'priority',1,2),(3,'priority',0,2)"))
    for _ in range(2):unify_lead_status_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT workflow_status,is_contacted FROM crm_leads ORDER BY id')).all()==[('ready',0),('contacted',1),('ready',0)]
    engine.dispose()


def test_removed_fake_status_keeps_record_and_priority_development_survives_restart():
    from app.services.lead_contact_status import unify_lead_status_schema, lead_status
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY,workflow_status TEXT,is_contacted BOOLEAN,status_schema_version INTEGER,notes TEXT)'))
        conn.execute(text("INSERT INTO crm_leads VALUES (1,'fake',0,0,'Keep old record'),(2,'fake',0,2,'Keep migrated record'),(3,'priority_developing',1,2,'Keep focus')"))
    for _ in range(2):unify_lead_status_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT workflow_status,is_contacted,notes FROM crm_leads ORDER BY id')).all()==[
            ('unfit',0,'Keep old record'),('unfit',0,'Keep migrated record'),('priority_developing',1,'Keep focus')]
    assert lead_status(Lead(workflow_status='fake'))=='unviewed'
    engine.dispose()


def test_retiring_priority_preserves_dates_notes_and_research_flags():
    from app.services.lead_contact_status import unify_lead_status_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY,workflow_status TEXT,is_contacted BOOLEAN,status_schema_version INTEGER,created_at TEXT,updated_at TEXT,notes TEXT,is_manually_researched BOOLEAN)'))
        conn.execute(text("INSERT INTO crm_leads VALUES (1,'priority',1,2,'2026-08-01','2026-09-01','Keep notes',1),(2,'priority',0,2,'2026-08-02','2026-09-02','Other notes',0)"))
        before=conn.execute(text('SELECT id,is_contacted,created_at,updated_at,notes,is_manually_researched FROM crm_leads ORDER BY id')).all()
    unify_lead_status_schema(engine);unify_lead_status_schema(engine)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT workflow_status FROM crm_leads ORDER BY id')).scalars().all()==['contacted','ready']
        assert conn.execute(text('SELECT id,is_contacted,created_at,updated_at,notes,is_manually_researched FROM crm_leads ORDER BY id')).all()==before
    engine.dispose()


def test_review_status_migrates_old_flag_once_without_guessing_background_checks():
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY,is_contacted BOOLEAN)'))
        conn.execute(text('INSERT INTO crm_leads VALUES (1,1),(2,0)'))
    ensure_lead_contact_status_schema(engine)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT workflow_status FROM crm_leads ORDER BY id')).scalars().all()==['contacted','unviewed']
        conn.execute(text("UPDATE crm_leads SET workflow_status='checking' WHERE id=2"))
    ensure_lead_contact_status_schema(engine)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT workflow_status FROM crm_leads WHERE id=2'))=='checking'
    engine.dispose()


def test_unification_preserves_old_progress_and_does_not_repeat_on_restart():
    from app.services.lead_contact_status import unify_lead_status_schema
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE crm_leads (id INTEGER PRIMARY KEY,workflow_status TEXT,is_contacted BOOLEAN)'))
        conn.execute(text('CREATE TABLE crm_lead_development (lead_id INTEGER,stage TEXT)'))
        conn.execute(text("INSERT INTO crm_leads VALUES (1,'checked',0),(2,'contacted',1),(3,'unviewed',0),(4,'contacted',1),(5,'checking',0),(6,'unviewed',0)"))
        conn.execute(text("INSERT INTO crm_lead_development VALUES (2,'replied'),(3,'following'),(4,'unfit'),(5,'todo'),(6,'developing')"))
    unify_lead_status_schema(engine)
    with engine.begin() as conn:
        assert conn.execute(text('SELECT workflow_status FROM crm_leads ORDER BY id')).scalars().all()==['ready','replied','contacted','unfit','ready','ready']
        conn.execute(text("UPDATE crm_leads SET workflow_status='ready',is_contacted=0 WHERE id=2"))
    unify_lead_status_schema(engine)
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT workflow_status FROM crm_leads WHERE id=2'))=='ready'
    engine.dispose()
