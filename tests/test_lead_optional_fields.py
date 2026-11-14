"""Partial lead details can be saved with automatic ownership."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Lead
from app.routers import customer


@pytest.mark.parametrize("owner", [None, "", " "])
@pytest.mark.parametrize("source", ["自主开发", "邮件", "RFQ", "rfq", "MIC RFQ", "mic rfq", "客户转介绍", "  展会开发  ", "", "  "])
def test_minimal_lead_can_be_persisted(monkeypatch, owner, source):
    engine = create_engine("sqlite://")
    Lead.__table__.create(engine)
    monkeypatch.setattr(customer, "access", lambda *args: None)
    monkeypatch.setattr(customer, "top_admin", lambda *args: False)
    payload = customer.WorkflowPayload(company_name=" 测试公司 ", owner_user_id=owner, source_type=source)
    with Session(engine) as db:
        result = customer.cl(1, payload, SimpleNamespace(id=7), db)
        saved = db.scalar(select(Lead))
        assert result["company_name"] == "测试公司"
        assert saved.owner_user_id == 7
        assert saved.source_type == ("MIC RFQ" if source.lower().replace(" ", "") == "micrfq" else "RFQ" if source.lower() == "rfq" else source.strip())
        customer.save_w(saved, customer.WorkflowPayload(company_name="测试公司", source_type=saved.source_type), 7)
        db.commit()
        assert saved.source_type == ("MIC RFQ" if source.lower().replace(" ", "") == "micrfq" else "RFQ" if source.lower() == "rfq" else source.strip())
        assert saved.contact_name is None
        assert saved.email is None
        assert saved.country is None


def test_blank_optional_form_values_are_accepted():
    payload = customer.WorkflowPayload(company_name="测试公司", country="", contact_name="", email="", phone="", owner_user_id="")
    assert payload.email is None
    assert payload.owner_user_id is None


def test_company_name_cannot_be_whitespace():
    with pytest.raises(ValidationError, match="请填写公司名称"):
        customer.WorkflowPayload(company_name="   ")


def test_default_owner_for_admin_is_current_user(monkeypatch):
    monkeypatch.setattr(customer, "top_admin", lambda *args: True)
    payload = customer.WorkflowPayload(company_name="测试公司", owner_user_id="")
    assert customer.target_owner(1, payload.owner_user_id, SimpleNamespace(id=7), None) == 7
