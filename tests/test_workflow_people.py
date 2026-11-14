"""Multi-contact preservation across the complete CRM qualification pipeline."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Customer, Lead, ProjectContact, ProspectingEntry
from app.services.workflow_people import set_workflow_people, workflow_people
from tests.test_global_access import db, headers
from tests.test_customer_people import create_customer

BASE='/api/customer-workflow/projects/1'
PEOPLE=[{'contact_name':'Buyer','email':'buyer@coil.test','is_primary':True},
        {'contact_name':'Engineer','email':'engineer@coil.test','whatsapp':'123','notes':'Technical contact','linkedin':'https://linkedin.com/in/engineer','facebook':'https://facebook.com/engineer','instagram':'https://instagram.com/engineer','youtube':'https://youtube.com/@engineer'}]

def test_result_to_list_to_lead_to_customer_to_pool_preserves_every_person(db):
    client=TestClient(app)
    response=client.post(BASE+'/auto-prospecting/jobs',headers=headers(2),json={
        'source':'名单导入','candidates':[{'company_name':'Coil company','website':'https://coil.test','company_linkedin':'https://linkedin.com/company/coil','company_facebook':'https://facebook.com/coil','company_instagram':'https://instagram.com/coil','company_youtube':'https://youtube.com/@coil','contacts':PEOPLE}]})
    assert response.status_code==201,response.text
    results=client.get(BASE+f"/auto-prospecting/jobs/{response.json()['id']}/candidates",headers=headers(2)).json()['items']
    assert len(results[0]['contacts'])==2
    response=client.post('/api/acquisition/projects/1/candidates/actions',headers=headers(2),json={'ids':[results[0]['id']],'action':'import'})
    assert response.status_code==200,response.text
    entry=db.scalar(select(ProspectingEntry))
    assert len(workflow_people(entry))==2
    response=client.post(BASE+f'/prospecting/{entry.id}/to-leads',headers=headers(2))
    assert response.status_code==200,response.text
    lead=response.json()
    assert lead['contacts'][1]['notes']=='Technical contact'
    response=client.post(BASE+f"/leads/{lead['id']}/to-customers",headers=headers(2))
    assert response.status_code==200,response.text
    cid=response.json()['customer_id']
    preview=client.get(f'/api/contacts/projects/1/{cid}/preview',headers=headers(2)).json()
    assert len(preview['contacts'])==2 and preview['email']=='buyer@coil.test'
    assert preview['contacts'][1]['whatsapp']=='123'
    for key in ('linkedin','facebook','instagram','youtube'):
        assert preview['contacts'][1][key]==PEOPLE[1][key]
        assert preview['company_'+key].startswith('https://')
    assert client.post(f'/api/contacts/projects/1/{cid}/release',headers=headers(2),json={'reason':'Later'}).status_code==200
    pool=client.get(BASE+'/pool',headers=headers(2)).json()['items'][0]
    assert pool['contacts']==preview['contacts']
    assert pool['company_linkedin']==preview['company_linkedin']
    assert client.post(BASE+f'/pool/{cid}/restore',headers=headers(2),json={}).status_code==200
    assert client.get(f'/api/contacts/projects/1/{cid}/preview',headers=headers(2)).json()['contacts']==preview['contacts']

def test_secondary_email_matches_customer_and_appends_without_overwriting_primary(db):
    client=TestClient(app);customer=create_customer(client)
    lead=Lead(site_project_id=1,owner_user_id=2,company_name='Company')
    set_workflow_people(lead,[{'email':'BOB@example.test','contact_name':'Replacement','is_primary':True},
                            {'email':'carol@example.test','contact_name':'Carol'}])
    db.add(lead);db.commit()
    response=client.post(BASE+f'/leads/{lead.id}/to-customers',headers=headers(2))
    assert response.status_code==200,response.text
    assert response.json()['customer_id']==customer['id']
    preview=client.get(f"/api/contacts/projects/1/{customer['id']}/preview",headers=headers(2)).json()
    assert len(preview['contacts'])==3 and preview['contact_name']=='Alice'
    assert preview['contacts'][1]['contact_name']=='Bob'
    assert len(db.scalars(select(Customer)).all())==1

def test_domain_match_does_not_steal_owner_or_overwrite_company(db):
    client=TestClient(app);customer=create_customer(client)
    db.get(Customer,customer['id']).company_website='https://www.example.test/contact'
    lead=Lead(site_project_id=1,owner_user_id=1,company_name='Different name',company_website='https://example.test',email='new@example.test')
    db.add(lead);db.commit();lid=lead.id
    response=client.post(BASE+f'/leads/{lid}/to-customers',headers=headers(1))
    assert response.status_code==409
    assert db.get(Lead,lid) is not None
    assert db.scalar(select(ProjectContact)).owner_user_id==2
    assert db.get(Customer,customer['id']).company=='Company'

def test_edit_and_clear_prospect_contacts_and_legacy_compatibility(db):
    client=TestClient(app)
    response=client.post(BASE+'/prospecting',headers=headers(2),json={'company_name':'Example','contacts':PEOPLE})
    assert response.status_code==201,response.text
    eid=response.json()['id']
    response=client.put(BASE+f'/prospecting/{eid}',headers=headers(2),json={'company_name':'Example','contact_name':'Old client','email':'legacy@coil.test'})
    assert response.status_code==200 and len(response.json()['contacts'])==2
    response=client.put(BASE+f'/prospecting/{eid}',headers=headers(2),json={'company_name':'Example','contacts':[]})
    assert response.status_code==200 and response.json()['contacts']==[] and response.json()['email']==''
    response=client.put(BASE+f'/prospecting/{eid}',headers=headers(2),json={'company_name':'Example','contacts':[PEOPLE[0],PEOPLE[0]]})
    assert response.status_code==422
    assert workflow_people(db.get(ProspectingEntry,eid))==[]


def test_discovery_keeps_multiple_public_emails_and_hunter_people(monkeypatch):
    from app.services import acquisition_discovery as discovery
    html='<a href="mailto:buyer@coil.test">Buyer</a><a href="mailto:engineer@coil.test">Engineer</a><a href="mailto:buyer@coil.test">Again</a>'
    result=discovery.inspect_company({'company_name':'Coil','website':'https://coil.test'},lambda url:(url,html))
    assert {person['email'] for person in result['contacts']}=={'buyer@coil.test','engineer@coil.test'}
    assert sum(person['is_primary'] for person in result['contacts'])==1
    monkeypatch.setattr(discovery,'provider_json',lambda *args,**kwargs:{'data':{'emails':[
        {'value':'buyer@coil.test','first_name':'Alice','confidence':90,'verification':{'status':'valid'}},
        {'value':'engineer@coil.test','first_name':'Bob','confidence':80,'verification':{'status':'valid'}},
        {'value':'bad@coil.test','verification':{'status':'invalid'}}]}})
    result=discovery.enrich_email({'website':'https://coil.test','evidence':{'facts':[]}},'fixture-key')
    assert len(result['contacts'])==2 and result['contacts'][0]['contact_name']=='Alice'


def test_ambiguous_company_matches_leave_lead_intact(db):
    client=TestClient(app)
    first=create_customer(client)
    second=create_customer(client,'Other company')
    # Shared email references two distinct masters; never pick the first arbitrarily.
    lead=Lead(site_project_id=1,owner_user_id=2,company_name='Company',email='bob@example.test')
    db.add(lead);db.commit();lid=lead.id
    response=client.post(BASE+f'/leads/{lid}/to-customers',headers=headers(2))
    assert response.status_code==409 and db.get(Lead,lid) is not None
    assert len(db.scalars(select(Customer)).all())==2


def test_batch_conversion_keeps_all_contacts_and_requires_write_access(db):
    from app.models import ProjectMember
    client=TestClient(app)
    leads=[]
    for index in range(2):
        response=client.post(BASE+'/leads',headers=headers(2),json={'company_name':f'Company {index}',
            'company_type':'distributor','contacts':[{'email':f'buyer{index}@coil.test','is_primary':True},{'email':f'engineer{index}@coil.test'}]})
        assert response.status_code==201,response.text
        leads.append(response.json()['id'])
    member=db.scalar(select(ProjectMember).where(ProjectMember.user_id==2));member.role='viewer';db.commit()
    response=client.post(BASE+'/leads/batch/to-customers',headers=headers(2),json={'ids':leads})
    assert response.status_code==403 and all(db.get(Lead,lid) for lid in leads)
    member.role='custom';db.commit()
    response=client.post(BASE+'/leads/batch/to-customers',headers=headers(2),json={'ids':leads})
    assert response.status_code==200,response.text
    assert response.json()['moved']==2
    customers=client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers']
    assert len(customers)==2 and all(len(item['contacts'])==2 and item['company_type']=='distributor' for item in customers)
    assert not db.scalars(select(Lead)).all()


def test_batch_prospect_conversion_is_not_captured_as_an_integer_item_id(db):
    client=TestClient(app)
    ids=[]
    for index in range(2):
        response=client.post(BASE+'/prospecting',headers=headers(2),json={'company_name':f'Prospect {index}','contacts':[{'email':f'buyer{index}@coil.test'}]})
        assert response.status_code==201,response.text
        ids.append(response.json()['id'])
    response=client.post(BASE+'/prospecting/batch/to-leads',headers=headers(2),json={'ids':ids})
    assert response.status_code==200,response.text
    assert response.json()['moved']==2 and len(db.scalars(select(Lead)).all())==2
