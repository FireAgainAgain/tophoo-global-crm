"""Regression coverage for customer contracts and financial document output."""
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pypdf import PdfReader

from app.main import app
from app.models import Customer, ProjectContact
from tests.test_global_access import db, headers


def customer(db, company="Example Buyer"):
    item = Customer(workspace_id=1, name=company, company=company)
    db.add(item)
    db.flush()
    db.add(ProjectContact(site_project_id=1, owner_user_id=1, contact_id=item.id, status="active"))
    db.commit()
    return item


def payload(layout, payment_mode, receipt_mode, unit_price):
    return {
        "number": "ER1111V",
        "document": {
            "layout": layout, "payment_mode": payment_mode, "receipt_mode": receipt_mode,
            "currency": "CNY", "buyer_company": "Example Buyer", "seller_company": "Example Seller",
            "deposit_percent": "50", "beneficiary_name": "BANK BENEFICIARY", "beneficiary_bank": "TEST BANK",
            "bank_account": "BANK-EXAMPLE", "alipay_name": "ALIPAY BENEFICIARY", "alipay_account": "ALIPAY-EXAMPLE",
            "invoice": "含税，开具增值税专用发票" if layout == "domestic" else "",
            "items": [{"description": "不锈钢换热管 3排27孔\n铝翅片", "quantity": "1", "unit_price": unit_price, "unit": "台"}],
        },
    }


@pytest.mark.parametrize("layout,mode,receipt,price,payment,balance", [
    ("domestic", "deposit", "bank", "15000", "定金", "尾款"),
    ("export", "full", "bank", "3923", "Full Payment", None),
    ("export", "deposit", "alipay", "3922", "Deposit Payment", "Balance Payment"),
])
def test_contract_exports_match_amount_and_receipt(db, layout, mode, receipt, price, payment, balance):
    client = TestClient(app)
    base = f"/api/contracts/projects/1/customers/{customer(db).id}"
    data = payload(layout, mode, receipt, price)
    saved = client.post(base, json=data, headers=headers(1))
    assert saved.status_code == 201, saved.text
    row = saved.json()
    path = f"{base}/{row['id']}/document/"
    pdf = client.get(path + "pdf", headers=headers(1))
    excel = client.get(path + "xlsx", headers=headers(1))
    assert pdf.status_code == excel.status_code == 200
    pdf_text = " ".join(page.extract_text() for page in PdfReader(BytesIO(pdf.content)).pages)
    workbook = load_workbook(BytesIO(excel.content))
    values = [cell.value for cells in workbook.active.iter_rows() for cell in cells if cell.value is not None]
    text = " ".join(str(value) for value in values)
    assert f"{float(price):,.2f}" in pdf_text
    assert float(price) in values
    if layout == "domestic":
        assert "人民币壹万伍仟元整" in text and "增值税专用发票" in text
    else:
        assert payment in pdf_text
    assert payment in text
    if balance:
        assert balance in text and float(price) / 2 in values
    else:
        assert "Balance Payment" not in pdf_text + text
    included = "BANK-EXAMPLE" if receipt == "bank" else "ALIPAY-EXAMPLE"
    excluded = "ALIPAY-EXAMPLE" if receipt == "bank" else "BANK-EXAMPLE"
    assert included in pdf_text and included in text
    assert excluded not in pdf_text + text


def test_quote_snapshot_permissions_and_signed_archive(db):
    from tests.test_quotations import payload as quote_payload
    from tests.test_module_access_levels import set_access

    client = TestClient(app)
    buyer = customer(db)
    other = customer(db, "Different Buyer")
    buyer_id = buyer.id
    base = f"/api/contracts/projects/1/customers/{buyer_id}"
    quote = client.post("/api/quotations/projects/1", headers=headers(1),
                        json={**quote_payload(), "customer_id": buyer_id}).json()
    domestic = client.get(base + "/defaults?layout=domestic", headers=headers(1)).json()["document"]
    assert domestic["layout"] == "domestic" and domestic["currency"] == "CNY"
    converted = client.get(base + f"/defaults?layout=domestic&quotation_id={quote['id']}",
                           headers=headers(1)).json()["document"]
    assert converted["layout"] == "domestic" and converted["currency"] == quote["document"]["currency"]
    assert converted["items"][0]["unit_price"] == quote["document"]["items"][0]["unit_price"]
    defaults = client.get(base + f"/defaults?quotation_id={quote['id']}", headers=headers(1)).json()
    assert defaults["document"]["layout"] == "export"
    assert defaults["document"]["buyer_company"] == "Example Buyer"
    assert defaults["document"]["items"][0]["description"] == "2 HP"
    data = {**defaults, "number": "ER1111V"}
    created = client.post(base, headers=headers(1), json=data)
    assert created.status_code == 201, created.text
    row = created.json()
    assert row["source_quote_number"] == quote["number"]
    assert client.post(base, headers=headers(1), json=data).status_code == 409
    assert client.post(base.replace(f"/customers/{buyer_id}", f"/customers/{other.id}"), headers=headers(1), json=data).status_code == 422
    buyer.company = "Changed Customer"
    db.commit()
    row_path = f"{base}/{row['id']}"
    assert client.get(row_path, headers=headers(1)).json()["document"]["buyer_company"] == "Example Buyer"
    set_access(db, ["customer_list"], [])
    assert client.get(row_path, headers=headers(2)).status_code == 404
    assert client.post(base, headers=headers(2), json=data).status_code == 403
    sent = client.patch(row_path + "/status", headers=headers(1), json={"status": "已发出", "revision": 1}).json()
    assert sent["status"] == "已发出"
    assert client.put(row_path, headers=headers(1), json={**data, "revision": sent["revision"]}).status_code == 409
    pdf = client.get(row_path + "/document/pdf", headers=headers(1)).content
    signed_path = row_path + "/signed"
    assert client.post(signed_path + "?revision=2", headers=headers(1), files={"file": ("bad.pdf", b"bad")}).status_code == 422
    signed = client.post(signed_path + "?revision=2", headers=headers(1), files={"file": ("signed.pdf", pdf)})
    assert signed.status_code == 200 and signed.json()["status"] == "已签署"
    assert client.get(signed_path, headers=headers(1)).content == pdf
    assert client.get(base, headers=headers(1)).json()[0]["has_signed"]
