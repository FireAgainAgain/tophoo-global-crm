"""Edits must not change addition dates or reorder lead/customer lists."""
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import app
from app.models import Customer, Lead, ProjectContact
from tests.test_global_access import db, headers


def test_leads_use_immutable_added_date_and_stable_ties(db):
    client = TestClient(app)
    old = client.post('/api/customer-workflow/projects/1/leads', headers=headers(1), json={'company_name': '旧线索'}).json()
    newer = client.post('/api/customer-workflow/projects/1/leads', headers=headers(1), json={'company_name': '新线索'}).json()
    older_date = datetime(2026, 8, 1, 10)
    db.get(Lead, old['id']).created_at = older_date
    db.get(Lead, newer['id']).created_at = datetime(2026, 9, 1, 10)
    db.commit()
    before = client.get('/api/customer-workflow/projects/1/leads', headers=headers(1)).json()['items']
    assert [item['id'] for item in before] == [newer['id'], old['id']]
    edited = client.put(f"/api/customer-workflow/projects/1/leads/{old['id']}", headers=headers(1), json={'company_name': '旧线索修改'}).json()
    assert edited['added_at'] == edited['created_at'] == older_date.isoformat()
    after = client.get('/api/customer-workflow/projects/1/leads', headers=headers(1)).json()['items']
    assert [item['id'] for item in after] == [newer['id'], old['id']]
    db.get(Lead, old['id']).created_at = db.get(Lead, newer['id']).created_at
    db.commit()
    tied = client.get('/api/customer-workflow/projects/1/leads', headers=headers(1)).json()['items']
    assert [item['id'] for item in tied] == sorted([old['id'], newer['id']], reverse=True)


def test_customers_use_project_addition_instead_of_master_creation(db):
    client = TestClient(app)
    first = client.post('/api/contacts/projects/1', headers=headers(1), json={'company_name': '项目客户一'}).json()
    second = client.post('/api/contacts/projects/1', headers=headers(1), json={'company_name': '项目客户二'}).json()
    relation = db.scalar(select(ProjectContact).where(ProjectContact.contact_id == first['id'], ProjectContact.site_project_id == 1))
    other = db.scalar(select(ProjectContact).where(ProjectContact.contact_id == second['id'], ProjectContact.site_project_id == 1))
    db.get(Customer, first['id']).created_at = datetime(2024, 1, 1)
    relation.created_at = datetime(2026, 9, 1, 10)
    other.created_at = datetime(2026, 8, 1, 10)
    db.commit()
    before = client.get('/api/contacts/projects/1', headers=headers(1)).json()['customers']
    assert [item['id'] for item in before] == [first['id'], second['id']]
    assert before[0]['added_at'] == '2026-09-01T10:00:00'
    assert before[0]['created_at'].startswith('2024-01-01')
    edited = client.put(f"/api/contacts/projects/1/{second['id']}", headers=headers(1), json={'company_name': '客户二修改', 'grade': 'A'}).json()
    assert edited['added_at'] == '2026-08-01T10:00:00'
    after = client.get('/api/contacts/projects/1', headers=headers(1)).json()['customers']
    assert [item['id'] for item in after] == [first['id'], second['id']]
    assert client.get('/api/contacts/projects/2', headers=headers(1)).json()['customers'] == []
