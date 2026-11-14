"""RFQ editing preserves historical annotations and project boundaries."""
import json
from fastapi.testclient import TestClient
from app.main import app
from app.models import Rfq, Customer, ProjectContact
from app.models import CustomerPerson
from tests.test_global_access import db, headers


def test_customer_inquiry_quick_edit_preserves_existing_details(db):
    db.add(Customer(id=911, workspace_id=1, name="Buyer", company="Acme"))
    db.flush()
    db.add(ProjectContact(site_project_id=1, contact_id=911, owner_user_id=1, status="active"))
    db.commit()
    client = TestClient(app)
    base = "/api/rfqs/projects/1"
    created = client.post(base, headers=headers(1), json={
        "contact_id": 911, "number": "v261201", "status": "已报价",
        "generic_fields": [{"key": "size", "title": "Size", "content": "120 mm"}],
    })
    assert created.status_code == 200
    rfq_id = created.json()["id"]
    payload = {"number": "v261202", "content": "New inquiry content"}
    result = client.patch(f"{base}/customers/911/{rfq_id}", headers=headers(1), json=payload)
    assert result.status_code == 200
    saved, = client.get(base, headers=headers(1), params={"customer_id": 911}).json()
    assert saved["number"] == payload["number"]
    assert saved["parameters"] == {"size": "120 mm", "customer_inquiry_content": payload["content"]}
    assert saved["status"] == "已报价"
    assert client.patch(f"{base}/customers/912/{rfq_id}", headers=headers(1), json=payload).status_code == 404

    items = [
        {"content": "铜管\n120 mm", "translation": "Copper tubes", "price": "USD 10\nFOB", "notes": "样品"},
        {"content": "不锈钢管", "translation": "", "price": "", "notes": "批量"},
    ]
    result = client.patch(f"{base}/customers/911/{rfq_id}", headers=headers(1), json={
        "number": payload["number"], "inquiry_items": items,
    })
    assert result.status_code == 200
    assert result.json()["inquiry_items"] == items
    result = client.put(f"{base}/{rfq_id}", headers=headers(1), json={
        "number": payload["number"], "contact_id": 911,
        "generic_fields": [{"key": "size", "title": "Size", "content": "130 mm"}],
    })
    assert result.status_code == 200
    assert result.json()["parameters"] == {"size": "130 mm"}
    assert result.json()["inquiry_items"] == items
    result = client.post(f"{base}/customers/911", headers=headers(1), json={
        "number": "v261203", "inquiry_items": items,
    })
    assert result.status_code == 200 and result.json()["inquiry_items"] == items
    assert client.post(f"{base}/customers/911/export/xlsx", headers=headers(1)).status_code == 404
    saved = client.get(base, headers=headers(1), params={"customer_id": 911}).json()
    assert next(row for row in saved if row["number"] == "v261203")["inquiry_items"] == items
    assert client.post(f"{base}/customers/912/export/xlsx", headers=headers(1), json={
        "number": "v261203", "inquiry_items": items,
    }).status_code == 404


def test_rfq_ownership_defaults_transfer_pool_and_historical_access(db):
    from app.models import ProjectMember
    member = db.get(ProjectMember, 1)
    member.permissions_json = '["rfq","customer_list","customer_pool"]'
    member.write_permissions_json = member.permissions_json
    db.add(ProjectMember(site_project_id=1, user_id=1, role='top_admin'))
    customer = Customer(id=901, workspace_id=1, name='Buyer', company='Acme')
    db.add(customer)
    db.flush()
    db.add(ProjectContact(site_project_id=1, contact_id=901, owner_user_id=2, status='active'))
    db.commit()
    client = TestClient(app)
    records = {}
    for status in ('待处理', '推进中', '已报价', '已成交', '已关闭'):
        result = client.post('/api/rfqs/projects/1', json={'contact_id':901, 'status':status}, headers=headers(1))
        assert result.status_code == 200
        records[status] = result.json()
        assert result.json()['owner_user_id'] == 2, 'Administrator-created RFQ follows the customer owner'
    assert len(client.get('/api/rfqs/projects/1', headers=headers(2)).json()) == 5
    snapshot = db.get(Rfq, records['待处理']['id']).contact_snapshot_json
    changed = client.put('/api/contacts/projects/1/901', json={'company_name':'Acme', 'owner_user_id':1}, headers=headers(1))
    assert changed.status_code == 200, changed.text
    for status, row in records.items():
        assert db.get(Rfq, row['id']).owner_user_id == (2 if status in ('已成交','已关闭') else 1)
    assert db.get(Rfq, records['待处理']['id']).contact_snapshot_json == snapshot
    # Former owner retains historical RFQs and can edit them without reclaiming the customer.
    historical = records['已成交']
    path = f"/api/rfqs/projects/1/{historical['id']}"
    assert client.put(path, json={'contact_id':901,'status':'已成交'}, headers=headers(2)).status_code == 200
    assert client.post('/api/rfqs/projects/1', json={'contact_id':901}, headers=headers(2)).status_code == 400
    assert client.post('/api/rfqs/projects/1', json={'owner_user_id':1}, headers=headers(2)).status_code == 403
    assert client.get(path+'/export/md', headers=headers(2)).status_code == 404
    assert client.put(path, json={'contact_id':901,'owner_user_id':1}, headers=headers(2)).status_code == 403
    # Pool clients cannot be newly linked; existing RFQ links remain editable.
    assert client.post('/api/contacts/projects/1/901/release', json={'reason':'test'}, headers=headers(1)).status_code == 200
    assert not client.get('/api/rfqs/projects/1/references', headers=headers(1)).json()['contacts']
    assert client.post('/api/rfqs/projects/1', json={'contact_id':901}, headers=headers(1)).status_code == 400
    assert client.put(path, json={'contact_id':901,'status':'已成交'}, headers=headers(2)).status_code == 200
    assert client.post('/api/customer-workflow/projects/1/pool/901/restore', json={}, headers=headers(2)).status_code == 200
    assert db.get(Rfq, records['待处理']['id']).owner_user_id == 2
    assert db.get(Rfq, records['已关闭']['id']).owner_user_id == 2
    refs = client.get('/api/rfqs/projects/1/references', headers=headers(1)).json()
    assert refs['is_top_admin'] and {owner['id'] for owner in refs['owners']} == {1,2}
    assert refs['contacts'][0]['owner_user_id'] == 2
    assert not client.get('/api/rfqs/projects/1/references', headers=headers(2)).json()['is_top_admin']
    # Explicit administrator assignments are validated against active project members.
    assert client.put(path, json={'contact_id':901,'owner_user_id':999}, headers=headers(1)).status_code == 422
    assigned = client.put(path, json={'contact_id':901,'owner_user_id':1,'status':'已成交'}, headers=headers(1))
    assert assigned.status_code == 200 and assigned.json()['owner_user_id'] == 1
    assert client.get(path+'/export/md', headers=headers(2)).status_code == 404


def test_edit_and_export_keep_legacy_values_and_prune_removed_notes(db):
    db.add(Rfq(id=901, site_project_id=1, owner_user_id=1, number='RFQ-legacy',
               product_number='HX-15', notes='原始内部备注', status='询盘',
               template_fields_json=json.dumps([
                   {'key': 'capacity', 'label_zh': '换热量', 'label_en': 'Capacity', 'unit': 'kW', 'note': '原始字段注释'},
                   {'key': 'removed', 'label_zh': '旧字段'}]),
               parameters_json='{"capacity":"88","removed":"old"}',
               parameter_notes_json=json.dumps({'capacity': '采购备注', 'removed': '删除后应移除'})))
    db.commit()
    client = TestClient(app)
    original = client.get('/api/rfqs/projects/1', headers=headers(1)).json()[0]
    payload = {key: original[key] for key in ('number', 'product_number', 'notes', 'parameter_notes', 'generic_fields')}
    payload['generic_fields'] = [payload['generic_fields'][0]]
    payload['generic_fields'][0]['content'] = '90'
    payload['status'] = '已报价'
    response = client.put('/api/rfqs/projects/1/901', json=payload, headers=headers(1))
    assert response.status_code == 200
    saved = response.json()
    assert saved['product_number'] == 'HX-15'
    assert saved['notes'] == '原始内部备注'
    assert saved['parameter_notes'] == {'capacity': '采购备注'}
    assert saved['parameters'] == {'capacity': '90'}
    assert saved['template_fields'][0]['note'] == '原始字段注释'
    assert saved['template_fields'][0]['unit'] == 'kW'
    assert client.put('/api/rfqs/projects/2/901', json=payload, headers=headers(1)).status_code == 404
    assert client.get('/api/rfqs/projects/1', headers=headers(2)).status_code == 403


def test_duplicate_number_and_invalid_content_do_not_change_saved_rfq(db):
    client = TestClient(app)
    for number in ('RFQ-A', 'RFQ-B'):
        response = client.post('/api/rfqs/projects/1', json={'number': number, 'generic_fields': [{'key': 'request', 'title': '需求', 'content': '原文'}]}, headers=headers(1))
        assert response.status_code == 200
    row = response.json()
    path = f"/api/rfqs/projects/1/{row['id']}"
    assert client.put(path, json={'number': 'RFQ-A'}, headers=headers(1)).status_code == 400
    assert client.put(path, json={'generic_fields': [{'key': 'request', 'title': '', 'content': '无标题'}]}, headers=headers(1)).status_code == 422
    assert client.put(path, json={'generic_fields': [{'key': 'request', 'title': '需求', 'content': 'a' * 20001}]}, headers=headers(1)).status_code == 422
    after = next(item for item in client.get('/api/rfqs/projects/1', headers=headers(1)).json() if item['id'] == row['id'])
    assert after['number'] == 'RFQ-B' and after['generic_fields'][0]['content'] == '原文'


def test_five_statuses_default_legacy_compatibility_and_internal_notes(db):
    client = TestClient(app)
    response = client.post('/api/rfqs/projects/1', json={}, headers=headers(1))
    assert response.status_code == 200 and response.json()['status'] == '待处理'
    path = f"/api/rfqs/projects/1/{response.json()['id']}"
    for status in ('待处理', '推进中', '已报价', '已成交', '已关闭'):
        response = client.put(path, json={'status': status, 'notes': '内部产品 HX-15；停止沟通：客户项目取消'}, headers=headers(1))
        assert response.status_code == 200 and response.json()['status'] == status
        assert '客户项目取消' in response.json()['notes']
    assert client.put(path, json={'status': '无效状态'}, headers=headers(1)).status_code == 422
    assert client.put(path, json={'status': '询盘'}, headers=headers(1)).json()['status'] == '待处理'
    assert client.put(path, json={'status': '沟通失败'}, headers=headers(1)).json()['status'] == '已关闭'
    for legacy in ('需求确认中', '报价准备中'):
        assert client.put(path, json={'status': legacy}, headers=headers(1)).json()['status'] == '推进中'
    item = db.get(Rfq, response.json()['id'])
    item.status = '询盘'
    db.commit()
    rows = client.get('/api/rfqs/projects/1', headers=headers(1)).json()
    assert next(row for row in rows if row['id'] == item.id)['status'] == '待处理'


def test_customer_country_follows_current_customer_in_references_list_and_exports(db):
    contact = Customer(id=901, workspace_id=1, name='采购联系人', company='采购公司', country='Germany')
    db.add(contact)
    db.flush()
    db.add(ProjectContact(site_project_id=1, contact_id=901, owner_user_id=1))
    db.commit()
    client = TestClient(app)
    refs = client.get('/api/rfqs/projects/1/references', headers=headers(1)).json()
    assert refs['contacts'][0]['country'] == 'Germany'
    created = client.post('/api/rfqs/projects/1', json={'contact_id': 901}, headers=headers(1))
    assert created.status_code == 200 and created.json()['contact_country'] == 'Germany'
    path = f"/api/rfqs/projects/1/{created.json()['id']}"
    contact.country = 'Canada'
    db.commit()
    assert client.get('/api/rfqs/projects/1', headers=headers(1)).json()[0]['contact_country'] == 'Canada'
    contact.country = None
    db.commit()
    assert client.get('/api/rfqs/projects/1/references', headers=headers(1)).json()['contacts'][0]['country'] == ''
    assert client.get('/api/rfqs/projects/1', headers=headers(1)).json()[0]['contact_country'] == ''
    assert client.put(path, json={'contact_id': None}, headers=headers(1)).json()['contact_country'] == ''


def test_rfq_person_snapshot_survives_customer_changes_and_validates_person_owner(db):
    customer = Customer(id=901, workspace_id=1, name='Primary', company='Acme', country='Germany',
                        company_type='manufacturer', company_address='Berlin', whatsapp='100',
                        company_linkedin='https://example.test/company')
    other = Customer(id=902, workspace_id=1, name='Other', company='Other Co')
    db.add_all([customer, other])
    db.flush()
    db.add_all([ProjectContact(site_project_id=1, contact_id=901, owner_user_id=1),
                ProjectContact(site_project_id=1, contact_id=902, owner_user_id=1),
                CustomerPerson(id=11, customer_id=901, contact_name='Primary', primary_slot=1),
                CustomerPerson(id=12, customer_id=901, contact_name='Buyer', email='buyer@example.test',
                               whatsapp='200', notes='PRIVATE PERSON REMARK', linkedin='https://example.test/buyer'),
                CustomerPerson(id=21, customer_id=902, contact_name='Other person', primary_slot=1)])
    db.commit()
    client = TestClient(app)
    refs = client.get('/api/rfqs/projects/1/references', headers=headers(1)).json()['contacts']
    ref = next(entry for entry in refs if entry['id'] == 901)
    assert ref['company_type_label'] == '制造商' and ref['company_address'] == 'Berlin'
    assert len(ref['people']) == 2 and ref['people'][0]['is_primary']
    response = client.post('/api/rfqs/projects/1', json={'contact_id': 901, 'contact_person_id': 12}, headers=headers(1))
    assert response.status_code == 200
    saved = response.json()
    assert saved['contact_snapshot_saved'] and saved['contact_name'] == 'Buyer'
    assert saved['contact_whatsapp'] == '200' and saved['company_type_label'] == '制造商'
    path = f"/api/rfqs/projects/1/{saved['id']}"
    customer.name = 'New Primary'
    customer.company_address = 'New address'
    db.get(CustomerPerson, 12).contact_name = 'Changed buyer'
    db.commit()
    loaded = client.get('/api/rfqs/projects/1', headers=headers(1)).json()[0]
    assert loaded['contact_name'] == 'Buyer' and loaded['company_address'] == 'New address'
    assert client.put(path, json={'contact_id': 901, 'contact_person_id': 21}, headers=headers(1)).status_code == 422
    assert client.post('/api/rfqs/projects/1', json={'contact_person_id': 12}, headers=headers(1)).status_code == 422
    # Deleting the live person must not erase the RFQ's historical contact or block edits.
    db.delete(db.get(CustomerPerson, 12))
    db.commit()
    kept = client.put(path, json={'contact_id': 901, 'contact_person_id': 12, 'status': '已报价'}, headers=headers(1))
    assert kept.status_code == 200 and kept.json()['contact_name'] == 'Buyer'
    # An older client omitting the new field also preserves the saved contact.
    kept = client.put(path, json={'contact_id': 901}, headers=headers(1))
    assert kept.json()['contact_name'] == 'Buyer'
    switched = client.put(path, json={'contact_id': 902, 'contact_person_id': 21}, headers=headers(1))
    assert switched.json()['contact_name'] == 'Other person'
    cleared = client.put(path, json={'contact_id': None}, headers=headers(1)).json()
    assert cleared['contact_person_id'] is None and not cleared['contact_snapshot_saved']
    assert cleared['contact_name'] == ''


def test_rfq_defaults_to_primary_and_migration_is_repeatable(db):
    from sqlalchemy import create_engine, inspect, text
    from app.services.project_service import ensure_rfq_schema
    customer = Customer(id=901, workspace_id=1, name='Primary', company='Acme')
    db.add(customer)
    db.flush()
    db.add_all([ProjectContact(site_project_id=1, contact_id=901, owner_user_id=1),
                CustomerPerson(id=11, customer_id=901, contact_name='Primary', primary_slot=1)])
    db.commit()
    result = TestClient(app).post('/api/rfqs/projects/1', json={'contact_id': 901}, headers=headers(1)).json()
    assert result['contact_person_id'] == 11 and result['contact_snapshot_saved']
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE crm_rfqs (id INTEGER PRIMARY KEY, status VARCHAR(40), template_key VARCHAR(60), company_id INTEGER, contact_id INTEGER)'))
    ensure_rfq_schema(engine)
    ensure_rfq_schema(engine)
    assert {'contact_person_id', 'contact_snapshot_json'} <= {column['name'] for column in inspect(engine).get_columns('crm_rfqs')}
    engine.dispose()
