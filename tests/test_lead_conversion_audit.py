"""Conversion contract, failure atomicity and observed preservation gaps."""
from datetime import datetime
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Customer, Lead, ProjectContact, ProjectMember
from app.services.workflow_people import set_workflow_people
from tests.test_global_access import db, headers

BASE='/api/customer-workflow/projects/1/leads'

def add_lead(db, **values):
    item=Lead(site_project_id=1,owner_user_id=2,company_name='Equipment manufacturer',**values)
    db.add(item);db.commit();return item.id

def test_complete_conversion_and_repeat_submission(db):
    client=TestClient(app)
    lid=add_lead(db,country='Germany',company_website='https://equipment.test',company_type='AHU',company_address='Berlin',customer_source='Exhibition',source_type='自主开发',notes='Company requirements',is_contacted=True,company_linkedin='https://linkedin.com/company/equipment',created_at=datetime(2026,8,1))
    set_workflow_people(db.get(Lead,lid),[{'contact_name':'Buyer','email':'buyer@equipment.test','notes':'Buyer note','is_primary':True},{'contact_name':'Engineer','email':'engineer@equipment.test','phone':'123','whatsapp':'456','linkedin':'https://linkedin.com/in/engineer','notes':'Engineering note'}]);db.commit()
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==200,response.text
    cid=response.json()['customer_id'];item=client.get(f'/api/contacts/projects/1/{cid}/preview',headers=headers(2)).json()
    for key,value in {'country':'德国','company_type':'AHU','company_address':'Berlin','customer_source':'Exhibition','source_type':'自主开发','notes':'Company requirements','company_linkedin':'https://linkedin.com/company/equipment'}.items():assert item[key]==value
    assert len(item['contacts'])==2 and item['contact_name']=='Buyer'
    assert item['contacts'][1]['notes']=='Engineering note' and item['contacts'][1]['whatsapp']=='456'
    assert db.scalar(select(ProjectContact).where(ProjectContact.contact_id==cid)).owner_user_id==2
    assert db.get(Lead,lid) is None
    assert client.post(f'{BASE}/{lid}/to-customers',headers=headers(2)).status_code==404
    assert len(db.scalars(select(Customer)).all())==1
    # These are current business semantics, not a claim of full history transfer.
    assert item['added_at']!='2026-08-01T00:00:00'
    assert 'is_contacted' not in item

@pytest.mark.parametrize('customer_grade, expected', [(None, 'B'), ('A', 'A')])
def test_batch_conversion_fills_only_missing_customer_grade(db, customer_grade, expected):
    client=TestClient(app)
    existing=client.post('/api/contacts/projects/1',headers=headers(2),json={
        'company_name':'Existing customer','company_website':'https://existing.test','grade':customer_grade,
    }).json()
    merged=add_lead(db,company_website='https://existing.test')
    new=add_lead(db,company_website='https://new.test')
    for lead_id in (merged,new):
        url=f'{BASE}/{lead_id}/grade'
        assert client.patch(url,headers=headers(2),json={'grade':'F'}).status_code==422
        response=client.patch(url,headers=headers(2),json={'grade':'B'})
        assert response.status_code==200,response.text
        assert response.json()['grade']=='B'
    response=client.post(BASE+'/batch/to-customers',headers=headers(2),json={'ids':[merged,new]})
    assert response.status_code==200,response.text
    db.expire_all()
    assert db.get(Customer,existing['id']).grade==expected
    assert db.scalar(select(Customer).where(Customer.company_website=='https://new.test')).grade=='B'

@pytest.mark.parametrize('website',['https://','http://','https://[invalid'])
def test_invalid_websites_do_not_merge_unrelated_companies(db,website):
    client=TestClient(app)
    existing=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Different enterprise','company_website':website,'contacts':[]}).json()
    lid=add_lead(db,company_website=website)
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2))
    assert response.status_code==200,response.text
    assert response.json()['customer_id']!=existing['id']

@pytest.mark.parametrize('batch', [False,True])
def test_permissions_and_project_isolation(db,batch):
    client=TestClient(app);lid=add_lead(db)
    url=f'{BASE}/batch/to-customers' if batch else f'{BASE}/{lid}/to-customers'
    options={'json':{'ids':[lid]}} if batch else {}
    assert client.post(url,headers=headers(2),**options).status_code==200
    lid=add_lead(db,company_website='https://other.test')
    db.get(Lead,lid).owner_user_id=1;db.commit()
    url=f'{BASE}/batch/to-customers' if batch else f'{BASE}/{lid}/to-customers'
    options={'json':{'ids':[lid]}} if batch else {}
    assert client.post(url,headers=headers(2),**options).status_code==404
    assert db.get(Lead,lid) is not None
    assert client.post(url.replace('/projects/1/','/projects/2/'),headers=headers(1),**options).status_code==404
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.role='viewer';db.commit()
    assert client.post(url,headers=headers(2),**options).status_code==403


def test_failed_batch_rolls_back_all_moves(db):
    client=TestClient(app)
    client.post('/api/contacts/projects/1',headers=headers(1),json={'company_name':'Other owner','company_website':'https://conflict.test','contacts':[]})
    first=add_lead(db,company_website='https://new.test')
    second=add_lead(db,company_website='https://conflict.test')
    response=client.post(BASE+'/batch/to-customers',headers=headers(2),json={'ids':[first,second]})
    assert response.status_code==409
    db.rollback();db.expire_all()
    assert db.get(Lead,first) is not None and db.get(Lead,second) is not None
    assert len(db.scalars(select(Customer)).all())==1


def test_duplicate_ids_rejected_before_conversion(db):
    client=TestClient(app);lid=add_lead(db)
    response=client.post(BASE+'/batch/to-customers',headers=headers(2),json={'ids':[lid,lid]})
    assert response.status_code==422,response.text
    assert db.get(Lead,lid) is not None
    assert not db.scalars(select(Customer)).all()


def test_merge_retains_existing_notes_but_does_not_transfer_conflicting_lead_notes(db):
    client=TestClient(app)
    existing=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Known enterprise','company_website':'https://equipment.test','notes':'Existing note','contacts':[{'email':'buyer@equipment.test','notes':'Existing person note','is_primary':True}]}).json()
    lid=add_lead(db,company_website='https://equipment.test',notes='Different lead note')
    set_workflow_people(db.get(Lead,lid),[{'email':'buyer@equipment.test','notes':'New conversation detail','is_primary':True}]);db.commit()
    response=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2));assert response.status_code==200
    item=client.get(f"/api/contacts/projects/1/{existing['id']}/preview",headers=headers(2)).json()
    assert item['notes']=='Existing note' and item['contacts'][0]['notes']=='Existing person note'
    assert db.get(Lead,lid) is None
