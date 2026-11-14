from uuid import uuid4
from datetime import datetime
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead, LeadInteraction
from app.models.mail import MailDelivery
from app.services import mail as transport
from app.services.workflow_people import set_workflow_people
from tests.test_global_access import db, headers
from tests.test_mail import config, send, lead, no_real_smtp
import pytest


def test_counts_real_accepted_attempts_without_contact_records_or_version_changes(db,monkeypatch):
    client=TestClient(app);config(client);lid=lead(db)
    item=db.get(Lead,lid);set_workflow_people(item,[{'contact_name':'Buyer','email':'buyer@example.com','is_primary':True},{'contact_name':'Engineer','email':'engineer@example.com'},{'contact_name':'No email'}]);db.commit()
    url=f'/api/customer-workflow/projects/1/leads/{lid}/contacts'
    before=client.get(url,headers=headers(1)).json()
    monkeypatch.setattr(transport,'transmit',lambda *_:None)
    key=str(uuid4());assert send(client,lid,key).json()['status']=='accepted'
    assert send(client,lid,key).json()['status']=='accepted'
    send(client,lid,recipient='BUYER@example.com');send(client,lid,recipient='engineer@example.com')
    def reject(*_):raise transport.DeliveryError('failed','Rejected')
    monkeypatch.setattr(transport,'transmit',reject);send(client,lid)
    def uncertain(*_):raise transport.DeliveryError('unknown','Unknown')
    monkeypatch.setattr(transport,'transmit',uncertain);send(client,lid)
    other=lead(db);monkeypatch.setattr(transport,'transmit',lambda *_:None);send(client,other)
    after=client.get(url,headers=headers(1)).json()
    assert after['outreach_stats']['buyer@example.com']['sent_count']==2
    assert after['outreach_stats']['engineer@example.com']['sent_count']==1
    assert after['outreach_stats']['buyer@example.com']['last_sent_at']
    assert after['version']==before['version'] and after['contacts']==before['contacts']
    assert not db.scalars(select(LeadInteraction)).all()
    assert db.get(Lead,lid).workflow_status=='ready'
    summary=client.get(f'/api/mail/projects/1/leads/{lid}/outreach-summary',headers=headers(1))
    assert summary.json()['outreach_stats']==after['outreach_stats']
    assert client.get(f'/api/mail/projects/1/leads/{lid}/outreach-summary',headers=headers(2)).status_code==404
    assert client.get(f'/api/mail/projects/2/leads/{lid}/outreach-summary',headers=headers(1)).status_code==404


def test_history_cursor_is_scoped_case_insensitive_and_readonly(db):
    client=TestClient(app);lid=lead(db);other=lead(db)
    for index in range(25):
        db.add(MailDelivery(owner_user_id=1,site_project_id=1,lead_id=lid,request_key=str(uuid4()),payload_hash='a'*64,message_id=str(uuid4()),sender='sam@example.com',recipient='BUYER@example.com',subject=f'Coils {index}',content='Actual sent body',status='accepted',accepted_at=datetime(2026,10,30,8,0)))
    db.add(MailDelivery(owner_user_id=1,site_project_id=1,lead_id=other,request_key=str(uuid4()),payload_hash='a'*64,message_id=str(uuid4()),sender='sam@example.com',recipient='buyer@example.com',subject='Other lead',content='Do not leak',status='accepted'))
    db.commit();url=f'/api/mail/projects/1/leads/{lid}/outreach-history?recipient=buyer%40example.com'
    first=client.get(url,headers=headers(1));assert first.status_code==200,first.text
    page=first.json();assert page['total']==25 and len(page['items'])==20 and page['next_before_id']
    second=client.get(url+'&before_id='+str(page['next_before_id']),headers=headers(1)).json()
    assert len(second['items'])==5 and second['next_before_id'] is None
    assert not {item['id'] for item in page['items']} & {item['id'] for item in second['items']}
    assert all(item['subject']!='Other lead' for item in page['items']+second['items'])
    assert client.get(url,headers=headers(2)).status_code==404
    assert client.get(url).status_code==401
    assert client.get(url.replace('buyer%40example.com','engineer%40example.com'),headers=headers(1)).json()['total']==0


@pytest.mark.parametrize('batch',[False,True])
def test_outreach_without_chat_records_does_not_block_conversion_and_is_archived(db,monkeypatch,batch):
    client=TestClient(app);config(client);lid=lead(db)
    set_workflow_people(db.get(Lead,lid),[{'contact_name':'Buyer','email':'buyer@example.com','is_primary':True},{'contact_name':'Engineer','email':'engineer@example.com'}]);db.commit()
    monkeypatch.setattr(transport,'transmit',lambda *_:None)
    deliveries=[send(client,lid).json(),send(client,lid,recipient='engineer@example.com').json()]
    assert all(row['status']=='accepted' for row in deliveries)
    assert not db.scalars(select(LeadInteraction)).all()
    base='/api/customer-workflow/projects/1/leads'
    if batch:
        response=client.post(base+'/batch/to-customers',headers=headers(1),json={'ids':[lid]})
    else:
        response=client.post(f'{base}/{lid}/to-customers',headers=headers(1))
    assert response.status_code==200,response.text
    from app.models import LeadConversionHistory,ContactRecord
    import json
    db.expire_all();assert db.get(Lead,lid) is None
    archive=db.scalar(select(LeadConversionHistory).where(LeadConversionHistory.source_lead_id==lid))
    snapshot=json.loads(archive.snapshot_json)
    assert len(snapshot['contacts'])==2
    assert snapshot['outreach_stats']['buyer@example.com']['sent_count']==1
    assert snapshot['outreach_stats']['engineer@example.com']['sent_count']==1
    assert {row['id'] for row in snapshot['outreach_deliveries']}=={row['id'] for row in deliveries}
    assert not db.scalars(select(ContactRecord)).all()
    assert all(db.get(MailDelivery,row['id']).status=='accepted' for row in deliveries)
    customer=client.get(f'/api/contacts/projects/1/{archive.customer_id}/preview',headers=headers(1)).json()
    assert {p['email'] for p in customer['contacts']}=={'buyer@example.com','engineer@example.com'}
