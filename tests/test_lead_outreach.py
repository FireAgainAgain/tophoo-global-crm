import json
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead, LeadInteraction, LeadOutreachDraft, LeadConversionHistory
from tests.test_global_access import db, headers

BASE='/api/customer-workflow/projects/1/leads'

def lead(db,owner=2):
    item=Lead(site_project_id=1,owner_user_id=owner,company_name='Outreach buyer')
    db.add(item);db.commit();return item.id

def test_draft_persistence_does_not_contact_or_change_company(db):
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    assert client.get(url,headers=headers(2)).json()=={'recipient_name':'','recipient_email':'','subject':'','content':'','content_html':'','content_translation':'','updated_at':None}
    body={'content':'Subject: Coil supply\r\n\r\nDear buyer,','content_translation':'标题：盘管供应\n\n您好，'}
    response=client.put(url,headers=headers(2),json=body)
    assert response.status_code==200,response.text
    assert response.json()['content']=='Subject: Coil supply\n\nDear buyer,'
    assert client.get(url,headers=headers(2)).json()==response.json()
    assert not db.get(Lead,lid).is_contacted
    assert not db.scalars(select(LeadInteraction)).all()
    assert db.get(Lead,lid).notes is None
    assert client.put(url,headers=headers(2),json={'content':'','content_translation':''}).status_code==200

def test_draft_scope_and_validation(db):
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    other=lead(db,1)
    assert client.get(f'{BASE}/{other}/outreach-draft',headers=headers(2)).status_code==404
    assert client.put(f'{BASE}/{other}/outreach-draft',headers=headers(2),json={'content':'overwrite'}).status_code==404
    assert client.get(url.replace('/projects/1/','/projects/2/'),headers=headers(1)).status_code==404
    assert client.put(url,headers=headers(2),json={'content':'x'*50001}).status_code==422
    assert client.get(url).status_code==401

def test_conversion_retains_draft_and_transferred_record(db):
    client=TestClient(app);lid=lead(db);body={'content':'Subject: Coil supply\nDear buyer','content_translation':'主题：盘管供应\n您好'}
    assert client.put(f'{BASE}/{lid}/outreach-draft',headers=headers(2),json=body).status_code==200
    response=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json={**body,'channel':'邮件'})
    assert response.status_code==201,response.text
    assert not db.get(Lead,lid).is_contacted
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==200,response.text
    cid=response.json()['customer_id'];assert db.get(LeadOutreachDraft,lid) is None
    history=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==cid))
    assert json.loads(history.snapshot_json)['outreach_draft']==body
    records=client.get(f'/api/contacts/projects/1/{cid}/records',headers=headers(2)).json()['records']
    assert records[0]['content']==body['content'] and records[0]['content_translation']==body['content_translation']

def test_delete_lead_removes_draft(db):
    client=TestClient(app);lid=lead(db)
    client.put(f'{BASE}/{lid}/outreach-draft',headers=headers(2),json={'content':'draft'})
    result=client.post(BASE+'/batch/delete',headers=headers(2),json={'ids':[lid]})
    assert result.status_code==200,result.text
    assert db.get(LeadOutreachDraft,lid) is None


def test_draft_subject_legacy_update_and_conversion(db):
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    result=client.put(url,headers=headers(2),json={'subject':'Coil supply','content':'Dear buyer','content_translation':'您好'})
    assert result.status_code==200
    assert result.json()['subject']=='Coil supply' and result.json()['updated_at']
    # Old clients do not erase the newly added subject.
    result=client.put(url,headers=headers(2),json={'content':'Updated body','content_translation':'更新'})
    assert result.json()['subject']=='Coil supply'
    assert client.put(url,headers=headers(2),json={'subject':'x'*261}).status_code==422
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2))
    assert response.status_code==200
    history=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==response.json()['customer_id']))
    assert json.loads(history.snapshot_json)['outreach_draft']['subject']=='Coil supply'


def test_upgrade_old_drafts_preserves_text_and_is_repeatable():
    from sqlalchemy import create_engine, text, inspect
    from app.services.lead_development import ensure_lead_development_schema
    engine=create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE crm_lead_outreach_drafts (lead_id INTEGER PRIMARY KEY, content TEXT NOT NULL, content_translation TEXT NOT NULL, updated_at DATETIME)'))
        connection.execute(text("INSERT INTO crm_lead_outreach_drafts VALUES (1, 'Old subject and body', '旧翻译', NULL)"))
    ensure_lead_development_schema(engine)
    ensure_lead_development_schema(engine)
    with engine.connect() as connection:
        item=connection.execute(text('SELECT * FROM crm_lead_outreach_drafts')).mappings().one()
        assert item['subject']=='' and item['content']=='Old subject and body' and item['content_translation']=='旧翻译'
        assert item['recipient_name']=='' and item['recipient_email']==''
    engine.dispose()


def test_recipient_persistence_validation_and_conversion(db):
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    result=client.put(url,headers=headers(2),json={'recipient_name':' Engineer ','recipient_email':' engineer@example.com ','content':'Hello'})
    assert result.status_code==200,result.text
    assert result.json()['recipient_name']=='Engineer'
    assert result.json()['recipient_email']=='engineer@example.com'
    result=client.put(url,headers=headers(2),json={'content':'Updated'})
    assert result.json()['recipient_email']=='engineer@example.com'
    assert client.get(url,headers=headers(2)).json()['recipient_name']=='Engineer'
    for email in ['invalid','a@@example.com','a b@example.com']:
        assert client.put(url,headers=headers(2),json={'recipient_email':email}).status_code==422
    assert not db.scalars(select(LeadInteraction)).all()
    result=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2))
    assert result.status_code==200,result.text
    history=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.customer_id==result.json()['customer_id']))
    snapshot=json.loads(history.snapshot_json)['outreach_draft']
    assert snapshot['recipient_name']=='Engineer' and snapshot['recipient_email']=='engineer@example.com'
