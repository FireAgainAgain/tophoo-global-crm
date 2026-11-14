import json
from fastapi.testclient import TestClient
from app.main import app
from app.models import Customer, CustomerPerson, ProjectContact, Quotation, Rfq
from app.services.quotation_links import live_document
from tests.test_global_access import db, headers
from tests.test_quotations import payload, grant


def test_current_customer_selected_person_and_exports_update_without_rewriting_quote(db,monkeypatch):
    grant(db);client=TestClient(app)
    c=Customer(workspace_id=1,name='Primary',company='Old company',company_address='Old address',people_initialized=True)
    db.add(c);db.flush()
    primary=CustomerPerson(customer_id=c.id,contact_name='Primary',email='primary@example.com',primary_slot=1)
    selected=CustomerPerson(customer_id=c.id,contact_name='Engineer',email='old@example.com',phone='100')
    db.add_all([primary,selected,ProjectContact(site_project_id=1,contact_id=c.id,owner_user_id=1)])
    rfq=Rfq(site_project_id=1,owner_user_id=1,number='v1008',contact_id=c.id);db.add(rfq);db.commit()
    body=payload();body.update(customer_id=c.id,rfq_id=rfq.id);body['document']['contact_person_id']=selected.id
    row=client.post('/api/quotations/projects/1',headers=headers(1),json=body).json()
    item=db.get(Quotation,row['id']);before=(item.data_json,item.revision,item.updated_at)
    c.company='Current company';c.company_address='New address';selected.contact_name='Renamed engineer';selected.email='new@example.com';selected.phone=None;selected.whatsapp='200';rfq.number='v2008';db.commit()
    response=client.get('/api/quotations/projects/1',headers=headers(1));assert response.status_code==200
    current=response.json()[0];d=current['document']
    assert (d['buyer_company'],d['buyer_address'],d['attention'],d['buyer_email'],d['buyer_phone'])==('Current company','New address','Renamed engineer','new@example.com','200')
    assert d['contact_person_id']==selected.id
    assert d['items']==row['document']['items'] and current['totals']==row['totals']
    refs=client.get('/api/quotations/projects/1/references',headers=headers(1)).json()
    assert 'rfqs' not in refs
    assert row['rfq_id'] is None
    assert refs['customers'][0]['people'][1]['contact_name']=='Renamed engineer'
    captured=[]
    monkeypatch.setattr('app.routers.quotation.pdf_bytes',lambda doc:captured.append(doc) or b'%PDF-test')
    assert client.get(f"/api/quotations/projects/1/{item.id}/pdf",headers=headers(1)).status_code==200
    assert captured[-1]['buyer_email']=='new@example.com'
    assert client.post('/api/quotations/projects/1/preview-pdf',headers=headers(1),json=body).status_code==200
    assert captured[-1]['buyer_company']=='Current company'
    selected.email=None;db.commit()
    assert client.get('/api/quotations/projects/1',headers=headers(1)).json()[0]['document']['buyer_email']==''
    assert (item.data_json,item.revision,item.updated_at)==before
    # A historical association outside the visible owner scope must not expose current data.
    original=json.loads(item.data_json)
    assert live_document(db,1,2,original,c.id)==original
    assert live_document(db,2,None,original,c.id)==original
    unlinked=payload();unlinked['number']='QT-MANUAL'
    manual=client.post('/api/quotations/projects/1',headers=headers(1),json=unlinked).json()
    assert manual['document']['buyer_company']==unlinked['document']['buyer_company']
    other=Customer(workspace_id=1,name='Other',company='Other');db.add(other);db.flush()
    unrelated=CustomerPerson(customer_id=other.id,contact_name='Unrelated');db.add(unrelated);db.commit()
    body['document']['contact_person_id']=unrelated.id
    assert client.post('/api/quotations/projects/1',headers=headers(1),json=body).status_code==422


def test_reassign_quote_moves_between_customer_lists(db):
    grant(db)
    client=TestClient(app)
    first=Customer(workspace_id=1,name='First',company='First')
    second=Customer(workspace_id=1,name='Second',company='Second')
    db.add_all([first,second]);db.flush()
    db.add_all([ProjectContact(site_project_id=1,contact_id=c.id,owner_user_id=1,status='active') for c in (first,second)])
    db.commit()
    body=payload()
    body['customer_id']=first.id
    created=client.post('/api/quotations/projects/1',headers=headers(1),json=body).json()
    body.update(customer_id=second.id,revision=created['revision'])
    moved=client.put(f"/api/quotations/projects/1/{created['id']}",headers=headers(1),json=body)
    assert moved.status_code==200,moved.text
    assert moved.json()['document']['buyer_company']=='Second'
    assert moved.json()['totals']==created['totals']
    first_list=client.get(f'/api/quotations/projects/1?customer_id={first.id}&mine=true',headers=headers(1)).json()
    second_list=client.get(f'/api/quotations/projects/1?customer_id={second.id}&mine=true',headers=headers(1)).json()
    assert first_list==[]
    assert [row['id'] for row in second_list]==[created['id']]
