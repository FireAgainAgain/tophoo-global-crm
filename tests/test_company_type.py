"""Company roles survive qualification and never overwrite verified master data."""
from fastapi.testclient import TestClient
from sqlalchemy import select
from app.main import app
from app.models import Customer, Lead
from app.services.company_type import normalize_company_type
from tests.test_global_access import db, headers

BASE='/api/customer-workflow/projects/1'

def test_company_type_acquisition_lead_customer_pool_and_exports(db):
    client=TestClient(app)
    result=client.post('/api/acquisition/projects/1/records',headers=headers(2),json={
        'company_name':'Coil','website':'https://coil.test','company_type':'经销商'}).json()
    assert result['company_type']=='distributor'
    response=client.post('/api/acquisition/projects/1/candidates/actions',headers=headers(2),json={'ids':[result['id']],'action':'to-leads'})
    assert response.status_code==200,response.text
    lead=db.scalar(select(Lead));assert lead.company_type=='distributor'
    assert client.get(BASE+'/leads',headers=headers(2)).json()['items'][0]['company_type']=='distributor'
    response=client.post(BASE+f'/leads/{lead.id}/to-customers',headers=headers(2))
    assert response.status_code==200,response.text
    cid=response.json()['customer_id']
    preview=client.get(f'/api/contacts/projects/1/{cid}/preview',headers=headers(2)).json()
    assert preview['company_type']=='distributor'
    assert client.post(f'/api/contacts/projects/1/{cid}/release',headers=headers(2),json={'reason':'Later'}).status_code==200
    assert client.get(BASE+'/pool',headers=headers(2)).json()['items'][0]['company_type']=='distributor'
    assert client.post(BASE+f'/pool/{cid}/restore',headers=headers(2),json={}).status_code==200
    assert client.get('/api/contacts/projects/1',headers=headers(2)).json()['customers'][0]['company_type']=='distributor'

def test_edit_unknown_custom_and_older_clients_preserve_type(db):
    client=TestClient(app)
    response=client.post(BASE+'/leads',headers=headers(2),json={'company_name':'Coil','company_type':'MANUFACTURER'})
    assert response.status_code==201,response.text
    lead=response.json();assert lead['company_type']=='manufacturer'
    path=BASE+f"/leads/{lead['id']}"
    assert client.put(path,headers=headers(2),json={'company_name':'Coil'}).json()['company_type']=='manufacturer'
    assert client.put(path,headers=headers(2),json={'company_name':'Coil','company_type':'OEM设备集成商'}).json()['company_type']=='OEM设备集成商'
    assert client.put(path,headers=headers(2),json={'company_name':'Coil','company_type':'未知'}).json()['company_type']==''
    assert client.put(path,headers=headers(2),json={'company_name':'Coil','company_type':'1'}).status_code==422

def test_merging_lead_does_not_overwrite_existing_company_type(db):
    client=TestClient(app)
    customer=client.post('/api/contacts/projects/1',headers=headers(2),json={'company_name':'Coil','company_website':'https://coil.test','company_type':'importer'}).json()
    lead=client.post(BASE+'/leads',headers=headers(2),json={'company_name':'Coil','company_website':'https://coil.test','company_type':'manufacturer'}).json()
    assert client.post(BASE+f"/leads/{lead['id']}/to-customers",headers=headers(2)).status_code==200
    assert db.get(Customer,customer['id']).company_type=='importer'
    assert normalize_company_type('工程承包商')=='contractor'
    assert normalize_company_type('End User')=='end_user'


def test_historical_schema_backfill_is_once_only_and_ignores_invalid_types():
    from sqlalchemy import create_engine, text
    from app.services.company_type import ensure_company_type_schema
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        for table in ('crm_customers','crm_leads','crm_prospecting_entries'):
            connection.execute(text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
        connection.execute(text('CREATE TABLE crm_prospecting_candidates (id INTEGER PRIMARY KEY, lead_id INTEGER, company_type VARCHAR(80))'))
        connection.execute(text('INSERT INTO crm_leads (id) VALUES (1),(2)'))
        connection.execute(text("INSERT INTO crm_prospecting_candidates VALUES (1,1,'distributor'),(2,2,'1')"))
    ensure_company_type_schema(engine)
    with engine.begin() as connection:
        assert connection.execute(text('SELECT company_type FROM crm_leads WHERE id=1')).scalar()=='distributor'
        assert connection.execute(text('SELECT company_type FROM crm_leads WHERE id=2')).scalar() is None
        connection.execute(text('UPDATE crm_leads SET company_type=NULL WHERE id=1'))
    ensure_company_type_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text('SELECT company_type FROM crm_leads WHERE id=1')).scalar() is None
