"""Full retention, write isolation, rollback and cleanup using independent databases."""
import json
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.main import app
from app.models import Lead, Customer, ContactRecord, FollowUpPlan, LeadInteraction, LeadConversionHistory, ProjectContact, ProjectMember
from app.services.global_project_data import delete_all_project_data
from tests.test_global_access import db, headers

BASE='/api/customer-workflow/projects/1/leads'
PROFILE={'priority':'high','tags':['AHU','AHU','热泵'],'next_followup_date':'2026-10-20'}
RECORD={'occurred_at':'2026-10-13','direction':'outbound','contact_name':'Buyer','channel':'email','subject':'Coil supply','content':'Actual sent message'}

def lead(client,name='Equipment',owner=2,**extra):
    response=client.post(BASE,headers=headers(1),json={'company_name':name,'owner_user_id':owner,'company_website':f'https://{name.lower()}.test',**extra});assert response.status_code==201,response.text
    return response.json()['id']

def test_development_records_convert_to_history_and_customer_tasks(db):
    db.execute(text('PRAGMA foreign_keys=ON'))
    client=TestClient(app);lid=lead(client,notes='Original note',contacts=[{'contact_name':'Buyer','email':'buyer@equipment.test','notes':'Contact original','is_primary':True}])
    db.get(Lead,lid).created_at=datetime(2026,8,1);db.commit()
    response=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=RECORD);assert response.status_code==201,response.text
    rid=response.json()['id']
    assert client.put(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2),json={**RECORD,'content':'Edited actual message'}).status_code==200
    response=client.get(BASE,headers=headers(2)).json()['items'][0]
    assert not response['is_contacted'] and 'development' not in response
    assert response['workflow_status']=='unviewed'
    assert client.put(f'{BASE}/{lid}',headers=headers(2),json={'company_name':'Equipment','notes':'Original note','contacts':response['contacts'],'company_website':'https://equipment.test'}).status_code==200
    assert client.get(f'{BASE}/{lid}/development',headers=headers(2)).status_code==404
    preview=client.post(BASE+'/batch/conversion-preview',headers=headers(2),json={'ids':[lid]}).json()
    assert preview['can_convert'] and preview['items'][0]['mode']=='created'
    assert db.get(Lead,lid) is not None and not db.scalars(select(Customer)).all()
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==200,response.text
    cid=response.json()['customer_id']
    archive=client.get(f'/api/contacts/projects/1/{cid}/conversion-history',headers=headers(2)).json()['items'][0]
    assert archive['source_lead_id']==lid and archive['converted_by']=='Sales'
    snapshot=archive['snapshot'];assert snapshot['notes']=='Original note' and not snapshot['is_contacted']
    assert snapshot['created_at']=='2026-08-01T00:00:00' and snapshot['workflow_status']=='unviewed' and 'development' not in snapshot
    assert snapshot['contacts'][0]['notes']=='Contact original'
    assert snapshot['interactions'][0]['content']=='Edited actual message'
    record=db.scalar(select(ContactRecord));assert record.contact_id==cid and record.subject=='Coil supply' and 'Edited actual message' in record.content
    assert not db.scalars(select(FollowUpPlan)).all()
    assert not db.scalars(select(LeadInteraction)).all()
    assert client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).status_code==404
    assert len(db.scalars(select(LeadConversionHistory)).all())==1 and len(db.scalars(select(ContactRecord)).all())==1


def test_merged_customer_retains_different_notes_in_snapshot(db):
    client=TestClient(app)
    customer=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Equipment','company_website':'https://equipment.test','notes':'Customer note','contacts':[{'email':'buyer@equipment.test','notes':'Existing person note','is_primary':True}]}).json()
    lid=lead(client,notes='Different company note',contacts=[{'email':'buyer@equipment.test','notes':'Different person note','is_primary':True}])
    preview=client.post(BASE+'/batch/conversion-preview',headers=headers(2),json={'ids':[lid]}).json();assert preview['items'][0]['mode']=='merged'
    result=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert result.status_code==200
    assert result.json()['customer_id']==customer['id']
    snapshot=json.loads(db.scalar(select(LeadConversionHistory)).snapshot_json)
    assert snapshot['notes']=='Different company note' and snapshot['contacts'][0]['notes']=='Different person note'
    assert db.get(Customer,customer['id']).notes=='Customer note'
    assert len(db.scalars(select(Customer)).all())==1


def test_profile_and_history_permissions_viewer_and_foreign_project(db):
    db.add(ProjectMember(site_project_id=1,user_id=1,role='owner'));db.commit()
    client=TestClient(app);lid=lead(client,owner=1)
    for method,suffix,payload in [('get','interactions',None),('post','interactions',RECORD)]:
        assert getattr(client,method)(f'{BASE}/{lid}/{suffix}',headers=headers(2),**({'json':payload} if payload else {})).status_code==404
    assert client.put(f'{BASE}/{lid}/development'.replace('/projects/1/','/projects/2/'),headers=headers(1),json=PROFILE).status_code==404
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.role='viewer';db.commit()
    own_lid=lead(client,'Own')
    assert client.put(f'{BASE}/{own_lid}/development',headers=headers(2),json=PROFILE).status_code==404
    assert client.post(f'{BASE}/{own_lid}/interactions',headers=headers(2),json=RECORD).status_code==403
    cid=client.post(f'{BASE}/{lid}/to-customers',headers=headers(1)).json()['customer_id']
    assert client.get(f'/api/contacts/projects/1/{cid}/conversion-history',headers=headers(2)).status_code==404
    assert client.get(f'/api/contacts/projects/2/{cid}/conversion-history',headers=headers(1)).status_code==404


def test_batch_failure_rolls_back_snapshots_records_tasks_and_source_cleanup(db):
    client=TestClient(app)
    client.post('/api/contacts/projects/1',headers=headers(1),json={'company_name':'Other owner','company_website':'https://conflict.test'})
    first=lead(client,'First');second=lead(client,'Conflict')
    client.put(f'{BASE}/{first}/development',headers=headers(2),json=PROFILE)
    client.post(f'{BASE}/{first}/interactions',headers=headers(2),json=RECORD)
    response=client.post(BASE+'/batch/to-customers',headers=headers(2),json={'ids':[first,second]});assert response.status_code==409
    assert db.get(Lead,first) is not None and db.get(Lead,second) is not None
    assert db.scalar(select(LeadInteraction)).content==RECORD['content']
    assert 'development' not in client.get(BASE,headers=headers(2)).json()['items'][0]
    for model in (LeadConversionHistory,ContactRecord,FollowUpPlan):assert not db.scalars(select(model)).all()
    assert len(db.scalars(select(Customer)).all())==1


def test_conversion_failure_after_snapshot_is_atomic(db,monkeypatch):
    from app.routers import customer
    client=TestClient(app);lid=lead(client)
    client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json=RECORD)
    original=customer.retain_conversion
    def fail(*args,**kwargs):original(*args,**kwargs);raise RuntimeError('simulated storage failure')
    monkeypatch.setattr(customer,'retain_conversion',fail)
    response=TestClient(app,raise_server_exceptions=False).post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==500
    assert db.get(Lead,lid) is not None and db.scalar(select(LeadInteraction)) is not None
    assert not db.scalars(select(LeadConversionHistory)).all() and not db.scalars(select(Customer)).all()


def test_manual_mark_does_not_invent_records_and_delete_cleanup(db):
    client=TestClient(app);lid=lead(client)
    assert client.patch(f'{BASE}/{lid}/contact-status',headers=headers(2),json={'is_contacted':True}).status_code==200
    assert client.get(f'{BASE}/{lid}/interactions',headers=headers(2)).json()['records']==[]
    rid=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json={**RECORD,'direction':'inbound'}).json()['id']
    assert client.get(BASE,headers=headers(2)).json()['items'][0]['workflow_status']=='contacted'
    assert client.delete(f'{BASE}/{lid}/interactions/{rid}',headers=headers(2)).status_code==200
    assert client.delete(f'{BASE}/{lid}',headers=headers(2)).status_code==200
    assert not db.scalars(select(LeadInteraction)).all()


def test_retired_settings_are_unavailable_and_reply_status_does_not_downgrade(db):
    client=TestClient(app);lid=lead(client);url=f'{BASE}/{lid}'
    assert client.put(url+'/development',headers=headers(2),json=PROFILE).status_code==404
    client.patch(url+'/status',headers=headers(2),json={'workflow_status':'replied'})
    client.post(url+'/interactions',headers=headers(2),json={**RECORD,'direction':'inbound'})
    assert db.get(Lead,lid).workflow_status=='priority_developing'
    client.post(url+'/interactions',headers=headers(2),json=RECORD)
    assert db.get(Lead,lid).workflow_status=='priority_developing'
    client.patch(url+'/status',headers=headers(2),json={'workflow_status':'unfit'})
    client.post(url+'/interactions',headers=headers(2),json={**RECORD,'direction':'inbound'})
    assert db.get(Lead,lid).workflow_status=='unviewed'
    converted=client.post(url+'/to-customers',headers=headers(2));assert converted.status_code==200
    assert not db.scalars(select(FollowUpPlan)).all()


def test_project_cleanup_removes_history_but_preserves_shared_customer(db):
    db.execute(text('PRAGMA foreign_keys=ON'));client=TestClient(app);lid=lead(client)
    client.put(f'{BASE}/{lid}/development',headers=headers(2),json=PROFILE)
    cid=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).json()['customer_id']
    delete_all_project_data(db,1);db.commit()
    assert db.get(Customer,cid) is not None
    assert not db.scalars(select(LeadConversionHistory)).all() and not db.scalars(select(FollowUpPlan)).all()


def test_invalid_development_and_blank_record_do_not_change_lead(db):
    client=TestClient(app);lid=lead(client)
    assert client.put(f'{BASE}/{lid}/development',headers=headers(2),json={**PROFILE,'stage':'converted'}).status_code==404
    assert client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json={**RECORD,'content':'   '}).status_code==422
    assert not db.get(Lead,lid).is_contacted


def test_large_unicode_history_uses_mysql_longtext_and_schema_upgrade_is_repeatable(db):
    from sqlalchemy.dialects import mysql
    from sqlalchemy.schema import CreateTable
    from app.services.lead_development import ensure_lead_development_schema
    for model in (LeadInteraction,LeadConversionHistory,ContactRecord):
        assert 'LONGTEXT' in str(CreateTable(model.__table__).compile(dialect=mysql.dialect()))
    ensure_lead_development_schema(db.get_bind());ensure_lead_development_schema(db.get_bind())
    client=TestClient(app);lid=lead(client)
    long_content='换热器技术沟通内容'*6000
    # 60,000 characters exceeds the API limit; 45,000 Unicode characters exceed TEXT bytes.
    long_content=long_content[:45000]
    response=client.post(f'{BASE}/{lid}/interactions',headers=headers(2),json={**RECORD,'content':long_content});assert response.status_code==201
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==200,response.text
    assert json.loads(db.scalar(select(LeadConversionHistory)).snapshot_json)['interactions'][0]['content']==long_content
