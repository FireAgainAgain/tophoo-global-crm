"""List clocks respect company overrides, ambiguous countries and project boundaries."""
from fastapi.testclient import TestClient
from app.main import app
from app.models import Lead, Customer, ProjectContact
from app.models.communication import CommunicationSetting
from app.schemas.communication import PlaceConfig
from tests.test_global_access import db, headers


def test_list_clocks_use_country_address_and_company_override_without_writes(db):
    leads=[Lead(site_project_id=1,owner_user_id=1,company_name=name,country=country,company_address=address)
           for name,country,address in [('Single','阿联酋',''),('Ambiguous','美国',''),
               ('Address','美国','Los Angeles'),('Override','美国','New York'),('Missing','','')]]
    db.add_all(leads);db.flush()
    db.add(CommunicationSetting(site_project_id=1,target_key=f'leads:{leads[3].id}',lead_id=leads[3].id,
        settings_json=PlaceConfig(country='US',timezone='America/Chicago',city='芝加哥办公室').model_dump_json()))
    # An unrelated project's setting must not override the address-derived zone.
    db.add(CommunicationSetting(site_project_id=2,target_key=f'leads:{leads[2].id}',lead_id=leads[2].id,
        settings_json=PlaceConfig(country='US',timezone='America/New_York').model_dump_json()))
    db.commit()
    original=[(lead.id,lead.updated_at,lead.workflow_status) for lead in leads]
    response=TestClient(app).get('/api/customer-workflow/projects/1/leads',headers=headers(1))
    assert response.status_code==200,response.text
    rows={row['company_name']:row['local_clock'] for row in response.json()['items']}
    assert rows['Single']['timezone']=='Asia/Dubai'
    assert rows['Ambiguous']=={'timezone':None,'hint':'待确认时区'}
    assert rows['Address']['timezone']=='America/Los_Angeles'
    assert rows['Override']=={'timezone':'America/Chicago','city':'芝加哥办公室'}
    assert rows['Missing']=={'timezone':None,'hint':'待补充地区'}
    assert [(lead.id,lead.updated_at,lead.workflow_status) for lead in leads]==original


def test_customer_clocks_use_customer_settings_and_keep_contact_details(db):
    customers = [Customer(workspace_id=1, name=name, company=name, country=country,
                          company_address=address, email='buyer@example.test')
                 for name, country, address in [('Single', '阿联酋', ''), ('Ambiguous', '美国', ''),
                                               ('Address', '美国', 'Los Angeles'), ('Override', '美国', 'New York'),
                                               ('Missing', '', '')]]
    db.add_all(customers)
    db.flush()
    db.add_all([ProjectContact(site_project_id=1, contact_id=c.id, owner_user_id=1, status='active') for c in customers])
    for project, customer, timezone in [(1, customers[3], 'America/Chicago'), (2, customers[2], 'America/New_York')]:
        db.add(CommunicationSetting(site_project_id=project, target_key=f'customers:{customer.id}', customer_id=customer.id,
                                   settings_json=PlaceConfig(country='US', timezone=timezone, city='指定办公室').model_dump_json()))
    db.commit()
    original = [(c.id, c.updated_at, c.email) for c in customers]
    response = TestClient(app).get('/api/contacts/projects/1', headers=headers(1))
    assert response.status_code == 200, response.text
    rows = {row['company_name']: row for row in response.json()['customers']}
    assert rows['Single']['local_clock']['timezone'] == 'Asia/Dubai'
    assert rows['Ambiguous']['local_clock'] == {'timezone': None, 'hint': '待确认时区'}
    assert rows['Address']['local_clock']['timezone'] == 'America/Los_Angeles'
    assert rows['Override']['local_clock'] == {'timezone': 'America/Chicago', 'city': '指定办公室'}
    assert rows['Missing']['local_clock'] == {'timezone': None, 'hint': '待补充地区'}
    assert all(row['email'] == 'buyer@example.test' for row in rows.values())
    assert [(c.id, c.updated_at, c.email) for c in customers] == original


def test_rfq_clocks_match_customer_settings_and_handle_missing_customer(db):
    from app.models import Rfq
    customer=Customer(workspace_id=1,name='Buyer',company='Acme',country='捷克共和国')
    db.add(customer);db.flush()
    db.add_all([Rfq(site_project_id=1,owner_user_id=1,number='Clock',contact_id=customer.id),
                Rfq(site_project_id=1,owner_user_id=1,number='Missing')])
    db.commit()
    client=TestClient(app)
    rows={row['number']:row for row in client.get('/api/rfqs/projects/1',headers=headers(1)).json()}
    assert rows['Clock']['local_clock']['timezone']=='Europe/Prague'
    assert rows['Missing']['local_clock']=={'timezone':None,'hint':'待补充地区'}
    customer.country='美国';customer.company_address='';db.commit()
    rows={row['number']:row for row in client.get('/api/rfqs/projects/1',headers=headers(1)).json()}
    assert rows['Clock']['local_clock']=={'timezone':None,'hint':'待确认时区'}
    db.add(CommunicationSetting(site_project_id=1,target_key=f'customers:{customer.id}',customer_id=customer.id,
        settings_json=PlaceConfig(country='US',timezone='America/Chicago',city='芝加哥办公室').model_dump_json()))
    db.commit()
    before=(customer.updated_at,customer.country,customer.company_address)
    rows={row['number']:row for row in client.get('/api/rfqs/projects/1',headers=headers(1)).json()}
    assert rows['Clock']['local_clock']=={'timezone':'America/Chicago','city':'芝加哥办公室'}
    assert before==(customer.updated_at,customer.country,customer.company_address)
