"""Customer people, primary selection and preservation of legacy data."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Customer, CustomerPerson, ProjectContact, ProjectMember, Lead
from app.services.customer_people import ensure_customer_people_schema
from tests.test_global_access import db, headers


def create_customer(client, company="Company", owner=2):
    response = client.post('/api/contacts/projects/1', headers=headers(1), json={
        'company_name': company, 'owner_user_id': owner, 'notes': 'Company information',
        'contacts': [
            {'contact_name': 'Alice', 'email': 'alice@example.test', 'phone': '111', 'whatsapp': 'wa1', 'notes': 'Alice note', 'is_primary': True},
            {'contact_name': 'Bob', 'email': 'bob@example.test', 'phone': '222', 'whatsapp': 'wa2', 'notes': 'Bob note'},
        ],
    })
    assert response.status_code == 201, response.text
    return response.json()


def test_create_edit_switch_primary_and_export(db):
    client = TestClient(app)
    customer = create_customer(client)
    assert len(customer['contacts']) == 2
    assert customer['contact_name'] == 'Alice'
    assert customer['other_channels'] == 'Alice note'
    contacts = customer['contacts']
    contacts[0]['is_primary'] = False
    contacts[1].update(is_primary=True, notes='Bob updated note')
    contacts.append({'contact_name': 'Carol', 'email': 'carol@example.test', 'notes': 'Carol note'})
    response = client.put(f"/api/contacts/projects/1/{customer['id']}", headers=headers(2), json={
        'company_name': 'Updated company', 'notes': 'Other information', 'contacts': contacts})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['contact_name'] == 'Bob'
    assert updated['email'] == 'bob@example.test'
    assert updated['phone'] == '222' and updated['whatsapp'] == 'wa2'
    assert updated['other_channels'] == 'Bob updated note'
    assert updated['notes'] == 'Other information'
    assert len(updated['contacts']) == 3
    assert sum(person['is_primary'] for person in updated['contacts']) == 1
    assert {person['id'] for person in contacts[:2]} <= {person['id'] for person in updated['contacts']}
    listing = client.get('/api/contacts/projects/1', headers=headers(2)).json()['customers'][0]
    preview = client.get(f"/api/contacts/projects/1/{customer['id']}/preview", headers=headers(2)).json()
    assert listing['contacts'] == preview['contacts'] == updated['contacts']
    for suffix in ("pdf", "md"):
        assert client.get(f"/api/contacts/projects/1/{customer['id']}/export/{suffix}", headers=headers(2)).status_code == 404


@pytest.mark.parametrize('primary_flags', [(False, False), (True, True)])
def test_invalid_primary_is_atomic(db, primary_flags):
    client = TestClient(app)
    customer = create_customer(client)
    contacts = customer['contacts']
    for person, primary in zip(contacts, primary_flags):
        person['is_primary'] = primary
    response = client.put(f"/api/contacts/projects/1/{customer['id']}", headers=headers(2), json={
        'company_name': 'Should not persist', 'contacts': contacts})
    assert response.status_code == 422
    db.rollback()  # The isolated fixture shares one session; real requests close it.
    original = client.get(f"/api/contacts/projects/1/{customer['id']}/preview", headers=headers(2)).json()
    assert original['company_name'] == 'Company'
    assert original['contact_name'] == 'Alice'
    assert sum(person['is_primary'] for person in original['contacts']) == 1


def test_person_ids_and_owner_permissions_are_scoped(db):
    db.add(ProjectMember(site_project_id=1, user_id=1, role='owner'))
    db.commit()
    client = TestClient(app)
    mine = create_customer(client, 'Mine')
    other = create_customer(client, 'Other', owner=1)
    foreign = {**other['contacts'][0], 'is_primary': True}
    response = client.put(f"/api/contacts/projects/1/{mine['id']}", headers=headers(2), json={
        'company_name': 'Mine', 'contacts': [foreign]})
    assert response.status_code == 422
    db.rollback()
    assert client.put(f"/api/contacts/projects/1/{other['id']}", headers=headers(2), json={
        'company_name': 'Unauthorized', 'contacts': other['contacts']}).status_code == 404
    assert client.get(f"/api/contacts/projects/2/{mine['id']}/preview", headers=headers(2)).status_code == 403
    assert db.get(Customer, other['id']).company == 'Other'


def test_legacy_primary_updates_preserve_secondary_people(db):
    client = TestClient(app)
    customer = create_customer(client)
    response = client.put(f"/api/contacts/projects/1/{customer['id']}", headers=headers(2), json={
        'company_name': 'Company', 'contact_name': 'Legacy Alice', 'email': 'new@example.test', 'other_channels': 'Primary note'})
    assert response.status_code == 200, response.text
    updated = response.json()
    assert len(updated['contacts']) == 2
    assert updated['contacts'][0]['contact_name'] == 'Legacy Alice'
    assert updated['contacts'][1]['contact_name'] == 'Bob'


def test_migration_preserves_old_fields_and_runs_once(db):
    db.add(Customer(id=123, workspace_id=1, name='Old person', company='Old company', notes='Old company information',
                    email='old@example.test', phone='123', whatsapp='wa', other_channels='Old contact note'))
    db.add(ProjectContact(site_project_id=1, contact_id=123, owner_user_id=2))
    db.commit()
    ensure_customer_people_schema(db.get_bind())
    ensure_customer_people_schema(db.get_bind())
    db.expire_all()
    people = db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id == 123)).all()
    assert len(people) == 1 and people[0].primary_slot == 1
    assert people[0].contact_name == 'Old person' and people[0].notes == 'Old contact note'
    assert people[0].email == 'old@example.test' and people[0].phone == '123'
    assert db.get(Customer, 123).notes == 'Old company information'
    assert db.get(Customer, 123).other_channels == 'Old contact note'


def test_lead_conversion_keeps_people_and_creates_a_primary(db):
    client = TestClient(app)
    customer = create_customer(client)
    db.add(Lead(id=501, site_project_id=1, owner_user_id=2, company_name='Company',
                contact_name='Alice updated', email='alice@example.test', other_channels='Converted primary note'))
    db.add(Lead(id=502, site_project_id=1, owner_user_id=2, company_name='New company',
                contact_name='New person', email='new@example.test'))
    db.commit()
    assert client.post('/api/customer-workflow/projects/1/leads/501/to-customers', headers=headers(2)).status_code == 200
    preview = client.get(f"/api/contacts/projects/1/{customer['id']}/preview", headers=headers(2)).json()
    assert len(preview['contacts']) == 2
    assert preview['contacts'][0]['contact_name'] == 'Alice'
    assert preview['contacts'][0]['notes'] == 'Alice note'
    assert preview['contacts'][1]['contact_name'] == 'Bob'
    response = client.post('/api/customer-workflow/projects/1/leads/502/to-customers', headers=headers(2))
    assert response.status_code == 200, response.text
    new_id = response.json()['customer_id']
    preview = client.get(f'/api/contacts/projects/1/{new_id}/preview', headers=headers(2)).json()
    assert len(preview['contacts']) == 1 and preview['contacts'][0]['is_primary']
    assert preview['contacts'][0]['contact_name'] == 'New person'


def test_partial_update_does_not_remove_other_people(db):
    client = TestClient(app)
    customer = create_customer(client)
    bob = {**customer['contacts'][1], 'is_primary': True}
    response = client.put(f"/api/contacts/projects/1/{customer['id']}", headers=headers(2), json={
        'company_name': 'Company', 'contacts': [bob]})
    assert response.status_code == 200
    assert len(response.json()['contacts']) == 2
    assert response.json()['contact_name'] == 'Bob'


def test_direct_person_actions_do_not_overwrite_company_or_other_contacts(db):
    client=TestClient(app);customer=create_customer(client);base=f"/api/contacts/projects/1/{customer['id']}/people"
    response=client.post(base,headers=headers(2),json={'contact_name':'Carol','email':'carol@example.test','notes':'Carol note'})
    assert response.status_code==201,response.text
    added=response.json();carol=next(person for person in added['contacts'] if person['contact_name']=='Carol')
    assert len(added['contacts'])==3 and added['contact_name']=='Alice'
    response=client.put(f"{base}/{carol['id']}",headers=headers(2),json={'contact_name':'Carol edited','email':'carol@example.test','notes':'New note'})
    updated=response.json();assert response.status_code==200
    assert updated['company_name']==customer['company_name'] and updated['notes']==customer['notes']
    assert db.scalar(select(ProjectContact).where(ProjectContact.contact_id==customer['id'])).owner_user_id==2
    assert next(person for person in updated['contacts'] if person['contact_name']=='Bob')['notes']=='Bob note'
    response=client.post(f"{base}/{carol['id']}/primary",headers=headers(2))
    assert response.status_code==200 and response.json()['contact_name']=='Carol edited'
    assert sum(person['is_primary'] for person in response.json()['contacts'])==1
    assert client.delete(f"{base}/{carol['id']}",headers=headers(2)).status_code==422
    db.rollback()
    bob=next(person for person in customer['contacts'] if person['contact_name']=='Bob')
    response=client.delete(f"{base}/{carol['id']}?replacement_id={bob['id']}",headers=headers(2))
    assert response.status_code==200 and response.json()['contact_name']=='Bob'
    assert len(response.json()['contacts'])==2


def test_delete_last_person_stays_empty_after_migration_and_preserves_history(db):
    from app.models import ContactRecord
    from datetime import datetime
    client=TestClient(app);customer=create_customer(client);base=f"/api/contacts/projects/1/{customer['id']}/people"
    alice,bob=customer['contacts']
    db.add(ContactRecord(site_project_id=1,contact_id=customer['id'],contact_name='Alice',direction='outbound',
                         occurred_at=datetime.now(),channel='email',content='Historical message'))
    db.commit()
    assert client.delete(f"{base}/{bob['id']}",headers=headers(2)).status_code==200
    response=client.delete(f"{base}/{alice['id']}",headers=headers(2))
    assert response.status_code==200 and response.json()['contacts']==[]
    assert response.json()['contact_name']=='' and response.json()['email']==''
    ensure_customer_people_schema(db.get_bind());db.expire_all()
    assert not db.scalars(select(CustomerPerson).where(CustomerPerson.customer_id==customer['id'])).all()
    assert db.get(Customer,customer['id']).company=='Company'
    assert db.scalar(select(ContactRecord).where(ContactRecord.contact_id==customer['id'])).content=='Historical message'
    response=client.post(base,headers=headers(2),json={'contact_name':'New first person'})
    assert response.status_code==201 and response.json()['contacts'][0]['is_primary']


def test_whole_customer_form_can_explicitly_delete_people(db):
    client=TestClient(app);customer=create_customer(client);alice,bob=customer['contacts']
    bob['is_primary']=True
    response=client.put(f"/api/contacts/projects/1/{customer['id']}",headers=headers(2),json={
        'company_name':'Company','contacts':[bob],'deleted_contact_ids':[alice['id']]})
    assert response.status_code==200 and response.json()['contact_name']=='Bob'
    assert len(response.json()['contacts'])==1
    response=client.put(f"/api/contacts/projects/1/{customer['id']}",headers=headers(2),json={
        'company_name':'Company','contacts':[],'deleted_contact_ids':[bob['id']]})
    assert response.status_code==200 and response.json()['contacts']==[]


def test_direct_actions_reject_foreign_person_and_customer(db):
    db.add(ProjectMember(site_project_id=1,user_id=1,role='owner'));db.commit()
    client=TestClient(app);mine=create_customer(client);other=create_customer(client,'Other',1)
    base=f"/api/contacts/projects/1/{mine['id']}/people/{other['contacts'][0]['id']}"
    assert client.delete(base,headers=headers(2)).status_code==404
    assert client.put(base,headers=headers(2),json={'contact_name':'Bad'}).status_code==404
    assert client.post(base+'/primary',headers=headers(2)).status_code==404
    assert client.post(f"/api/contacts/projects/1/{other['id']}/people",headers=headers(2),json={'contact_name':'Bad'}).status_code==404


def test_viewer_and_pool_cannot_mutate_people(db):
    client=TestClient(app);customer=create_customer(client);person=customer['contacts'][0]
    base=f"/api/contacts/projects/1/{customer['id']}/people"
    member=db.scalar(select(ProjectMember).where(ProjectMember.site_project_id==1,ProjectMember.user_id==2))
    member.role='viewer';db.commit()
    assert client.post(base,headers=headers(2),json={'contact_name':'Blocked'}).status_code==403
    assert client.put(f"{base}/{person['id']}",headers=headers(2),json={'contact_name':'Blocked'}).status_code==403
    assert client.delete(f"{base}/{person['id']}",headers=headers(2)).status_code==403
    assert client.post(f"{base}/{person['id']}/primary",headers=headers(2)).status_code==403
    assert client.put(f"/api/contacts/projects/1/{customer['id']}",headers=headers(2),json={
        'company_name':'Blocked','contacts':[],'deleted_contact_ids':[person['id']]}).status_code==403
    member.role='custom'
    db.scalar(select(ProjectContact).where(ProjectContact.contact_id==customer['id'])).status='pool'
    db.commit()
    assert client.post(base,headers=headers(2),json={'contact_name':'Blocked'}).status_code==409


def test_social_links_company_and_people_edit_clear_export_and_legacy_preservation(db):
    client=TestClient(app)
    links={key:'https://'+key+'.com/person' for key in ('linkedin','facebook','instagram','youtube')}
    company={"company_"+key:'https://'+key+'.com/company' for key in links}
    response=client.post('/api/contacts/projects/1',headers=headers(2),json={
        'company_name':'Social company',**company,'contacts':[{'contact_name':'Buyer','is_primary':True,**links}]})
    assert response.status_code==201,response.text
    customer=response.json();cid=customer['id'];person=customer['contacts'][0];pid=person['id']
    assert all(customer[key]==value for key,value in company.items())
    assert all(person[key]==value for key,value in links.items())
    response=client.put(f'/api/contacts/projects/1/{cid}/people/{pid}',headers=headers(2),json={'contact_name':'Edited','phone':'123'})
    assert response.status_code==200 and response.json()['contacts'][0]['linkedin']==links['linkedin']
    response=client.put(f'/api/contacts/projects/1/{cid}',headers=headers(2),json={'company_name':'Edited company'})
    assert response.status_code==200 and response.json()['company_youtube']==company['company_youtube']
    assert response.json()['contacts'][0]['instagram']==links['instagram']
    response=client.put(f'/api/contacts/projects/1/{cid}/people/{pid}',headers=headers(2),json={'contact_name':'Edited','linkedin':''})
    assert response.status_code==200 and response.json()['contacts'][0]['linkedin']==''
    assert response.json()['contacts'][0]['facebook']==links['facebook']
    response=client.put(f'/api/contacts/projects/1/{cid}',headers=headers(2),json={'company_name':'Edited company','company_linkedin':''})
    assert response.status_code==200 and response.json()['company_linkedin']==''
    assert response.json()['company_facebook']==company['company_facebook']
    response=client.post(f'/api/contacts/projects/1/{cid}/people',headers=headers(2),json={'linkedin':'javascript:alert(1)'})
    assert response.status_code==422
