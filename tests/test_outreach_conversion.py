from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Lead, LeadInteraction, LeadOutreachDraft
from tests.test_global_access import db, headers
from tests.test_lead_outreach import BASE, lead


def setup_draft(db):
    client=TestClient(app);lid=lead(db);url=f'{BASE}/{lid}/outreach-draft'
    draft={'recipient_name':'Buyer','recipient_email':'buyer@example.com','subject':'Supply','content':'Hello','content_html':'<p><b>Hello</b></p>','content_translation':'您好'}
    assert client.put(url,headers=headers(2),json=draft).status_code==200
    payload={'contact_name':'Buyer','subject':'Supply','content':'Hello','content_translation':'您好','channel':'邮件','expected_draft':draft,'request_key':'conversion-request-123456'}
    return client,lid,url,payload


def test_atomic_conversion_clear_retry_and_customer_retention(db):
    client,lid,url,payload=setup_draft(db)
    payload['clear_draft']=True
    response=client.post(url+'/to-interaction',headers=headers(2),json=payload)
    assert response.status_code==201,response.text
    record=response.json();assert record['content_translation']=='您好'
    assert record['outreach_source']['recipient_email']=='buyer@example.com'
    assert record['outreach_source']['content_html']=='<p><b>Hello</b></p>'
    draft=client.get(url,headers=headers(2)).json()
    assert all(draft[key]=='' for key in payload['expected_draft'])
    assert not db.get(Lead,lid).is_contacted
    assert client.post(url+'/to-interaction',headers=headers(2),json=payload).json()['id']==record['id']
    assert len(db.scalars(select(LeadInteraction)).all())==1
    converted=client.post(f'{BASE}/{lid}/to-customers',headers=headers(2))
    assert converted.status_code==200,converted.text
    cid=converted.json()['customer_id']
    records=client.get(f'/api/contacts/projects/1/{cid}/records',headers=headers(2)).json()['records']
    assert records[0]['outreach_source']['content_html']=='<p><b>Hello</b></p>'


def test_conversion_preserve_and_conflict_guard(db):
    client,lid,url,payload=setup_draft(db)
    assert client.post(url+'/to-interaction',headers=headers(2),json=payload).status_code==201
    assert client.get(url,headers=headers(2)).json()['subject']=='Supply'
    updated={**payload['expected_draft'],'content':'Newer draft'}
    assert client.put(url,headers=headers(2),json=updated).status_code==200
    payload.update(clear_draft=True,request_key='different-request-123456')
    assert client.post(url+'/to-interaction',headers=headers(2),json=payload).status_code==409
    assert client.get(url,headers=headers(2)).json()['content']=='Newer draft'
    assert len(db.scalars(select(LeadInteraction)).all())==1
    assert client.post(url+'/to-interaction',headers=headers(1),json=payload).status_code==409
    assert client.post(url+'/to-interaction',json=payload).status_code==401


def test_invalid_conversion_or_foreign_lead_does_not_clear(db):
    client,lid,url,payload=setup_draft(db)
    response=client.post(url+'/to-interaction',headers=headers(2),json={**payload,'content':' ','clear_draft':True})
    assert response.status_code==422
    assert client.get(url,headers=headers(2)).json()['content']=='Hello'
    assert not db.scalars(select(LeadInteraction)).all()
    other=lead(db,1)
    assert client.post(f'{BASE}/{other}/outreach-draft/to-interaction',headers=headers(2),json=payload).status_code==404
