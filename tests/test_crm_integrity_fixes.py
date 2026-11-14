from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.main import app
from app.models import Customer, ProjectContact, User
from tests.test_global_access import db, headers
from tests.test_module_access_levels import set_access
from tests.test_quotations import payload as quote_payload
from tests.test_sales_contracts import customer, payload as contract_payload


def test_conversion_does_not_reuse_customers_from_another_project(db):
    buyer = Customer(workspace_id=1, name="Shared", company="Shared", company_website="https://shared.example.test")
    db.add(buyer)
    db.flush()
    db.add(ProjectContact(site_project_id=2, contact_id=buyer.id, owner_user_id=1, status="active"))
    db.commit()
    set_access(db, ["leads", "customer_list"], ["leads", "customer_list"])
    client = TestClient(app)
    auth = headers(2)
    base = "/api/customer-workflow/projects/1/leads"
    assert client.get("/api/contacts/projects/2", headers=auth).status_code == 403
    lead = client.post(base, headers=auth, json={"company_name": "Shared", "company_website": buyer.company_website})
    assert lead.status_code == 201
    converted = client.post(f"{base}/{lead.json()['id']}/to-customers", headers=auth)
    assert converted.status_code == 200
    customer_id = converted.json()["customer_id"]
    assert customer_id != buyer.id
    assert client.patch(f"/api/contacts/projects/1/{customer_id}/grade", headers=auth, json={"grade": "E"}).status_code == 200
    assert buyer.grade is None


def test_edit_keeps_owner_and_explicit_transfer_moves_quotes(db):
    set_access(db, ["customer_list", "quotations"], ["customer_list", "quotations"])
    client = TestClient(app)
    owner, member = headers(1), headers(2)
    customer_id = customer(db).id
    base = f"/api/contacts/projects/1/{customer_id}"
    quotes = "/api/quotations/projects/1"
    quote = client.post(quotes, headers=owner, json={**quote_payload(), "customer_id": customer_id})
    assert quote.status_code == 201
    assert client.put(base, headers=owner, json={"company_name": "Example Buyer", "owner_user_id": 2}).status_code == 200
    assert client.put(base, headers=owner, json={"company_name": "Example Buyer", "notes": "Update"}).status_code == 200
    relation = db.scalar(select(ProjectContact).where(ProjectContact.contact_id == customer_id))
    assert relation.owner_user_id == 2
    result = client.get(f"{quotes}?customer_id={customer_id}&mine=true", headers=member)
    assert [row["id"] for row in result.json()] == [quote.json()["id"]]


def test_pool_keeps_read_only_contract_archive_and_blocks_deletion(db):
    set_access(db, ["customer_pool"], ["customer_pool"])
    client = TestClient(app)
    auth = headers(1)
    customer_id = customer(db).id
    base = f"/api/contracts/projects/1/customers/{customer_id}"
    document = contract_payload("export", "full", "bank", "100")
    created = client.post(base, headers=auth, json=document)
    assert created.status_code == 201
    path = f"{base}/{created.json()['id']}"
    pdf = client.get(path + "/document/pdf", headers=auth).content
    signed = client.post(path + "/signed?revision=1", headers=auth, files={"file": ("signed.pdf", pdf, "application/pdf")})
    assert signed.status_code == 200
    assert client.post(f"/api/contacts/projects/1/{customer_id}/release", headers=auth, json={"reason": "Archive"}).status_code == 200
    pool = "/api/customer-workflow/projects/1/pool"
    assert client.get(pool, headers=auth).json()["items"][0]["has_archived_contracts"]
    assert client.get(path + "/signed", headers=auth).content == pdf
    assert client.get(path, headers=headers(2)).status_code == 404
    assert client.post(base, headers=auth, json=document).status_code == 404
    assert client.delete(f"{pool}/{customer_id}", headers=auth).status_code == 409
    assert client.post(pool + "/batch/delete", headers=auth, json={"ids": [customer_id]}).status_code == 409


def test_password_change_revokes_other_sessions_and_renews_current_session(db):
    db.get(User, 1).password_hash = hash_password("old-password-test")
    db.commit()
    client = TestClient(app)
    old, current = headers(1), headers(1)
    changed = client.patch("/api/auth/me", headers=current, json={
        "display_name": "Owner", "current_password": "old-password-test", "new_password": "new-password-test",
    })
    assert changed.status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401
    new = {"Authorization": "Bearer " + changed.json()["access_token"]}
    assert client.get("/api/auth/me", headers=new).status_code == 200
