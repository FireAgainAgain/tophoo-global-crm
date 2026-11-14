"""Condition filtering and candidate limits never rely on a quality score."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.models import Customer, Lead, ProjectContact, ProspectingCandidate, ProspectingEntry, ProspectingJob
from app.routers import customer
from app.services.acquisition_filter import qualify
from app.services.project_service import ensure_acquisition_criteria_schema


def row(**changes):
    return customer.AcquisitionCandidatePayload(**{
        "company_name": "Example heat exchanger HVAC distributor", "country": "Germany",
        "company_type": "distributor", "website": "https://example.com", **changes,
    })


@pytest.mark.parametrize("changes,expected", [
    ({}, "shortlisted"),
    ({"country": "United States", "email": "sales@example.com"}, "filtered"),
    ({"company_type": "manufacturer", "email": "sales@example.com"}, "filtered"),
    ({"country": None}, "pending_review"),
    ({"company_type": None}, "pending_review"),
    ({"company_name": "Example heat exchanger distributor"}, "pending_review"),
    ({"description": "recruitment"}, "filtered"),
])
def test_required_conditions_cannot_be_offset_by_other_facts(changes, expected):
    assert qualify(row(**changes), ["德国"], ["经销商"], ["hvac"], "heat exchanger", ["recruitment"])[0] == expected


def test_unfilled_conditions_do_not_restrict_and_email_is_optional():
    assert qualify(row(country=None, company_type=None, website=None), [], [], [], "", [])[0] == "shortlisted"


def test_external_titles_are_not_verified_company_facts():
    assert qualify(row(), [], [], [], "heat exchanger", [], external=True)[0] == "pending_review"


def test_comma_separated_keywords_are_alternatives_and_english_matches_words():
    assert qualify(row(), [], [], [], "radiator, heat exchanger", ["rib"])[0] == "shortlisted"
    assert qualify(row(company_name="distributor"), [], [], [], "rib", [])[0] == "pending_review"


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://")
    for model in (Customer, ProjectContact, Lead, ProspectingEntry, ProspectingJob, ProspectingCandidate):
        model.__table__.create(engine)
    monkeypatch.setattr(customer, "access", lambda *args: SimpleNamespace(id=1))
    monkeypatch.setattr(customer, "top_admin", lambda *args: False)
    with Session(engine) as session:
        yield session


def create(db, **changes):
    payload = customer.AcquisitionJobPayload(**{"candidates": [row()], **changes})
    return customer.create_acquisition_job(1, payload, SimpleNamespace(id=7), db)


def test_import_persists_passed_pending_and_rejected_separately(db):
    result = create(db, keyword="heat exchanger", target_countries=["德国"], target_types=["distributor"],
                    target_industries=["hvac"], candidates=[
                        row(website="https://passed.example"),
                        row(website="https://pending.example", country=None),
                        row(website="https://rejected.example", company_type="manufacturer"),
                    ])
    assert (result["found_count"], result["shortlisted_count"], result["pending_count"], result["filtered_count"]) == (3, 1, 1, 1)
    assert result["criteria"]["industry"] == ["hvac"]
    assert len(db.scalars(select(ProspectingEntry)).all()) == 1
    states = {x.status for x in db.scalars(select(ProspectingCandidate)).all()}
    assert states == {"shortlisted", "pending_review", "filtered"}


def test_same_task_duplicates_do_not_violate_unique_index(db):
    result = create(db, candidates=[row(), row(company_name="Another page")])
    assert result["found_count"] == 2
    assert result["duplicate_count"] == 1
    assert result["shortlisted_count"] == 1
    assert len(db.scalars(select(ProspectingCandidate)).all()) == 1
    assert create(db)["duplicate_count"] == 1


def test_chinese_company_names_do_not_collapse_to_same_key():
    assert customer.acquisition_key(None, "甲公司") != customer.acquisition_key(None, "乙公司")


def test_import_limit_is_processing_cap_not_target(db):
    result = create(db, limit=1, candidates=[row(website=None), row(company_name="Other", website=None)])
    assert result["found_count"] == 1
    assert result["criteria"]["limit"] == 1


def test_empty_import_does_not_fall_back_to_external_service(db, monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(customer, "external_acquisition_candidates", fetch)
    with pytest.raises(HTTPException): create(db, candidates=[])
    fetch.assert_not_called()


def test_search_limit_and_source_are_enforced(db, monkeypatch):
    monkeypatch.setenv("ACQUISITION_SERPER_API_KEY", "test-only")
    with pytest.raises(HTTPException, match="单次最多处理 20"):
        create(db, source="Serper (Google)", keyword="heat exchanger", limit=50)
    with pytest.raises(HTTPException, match="可执行"):
        create(db, source="Google Places")


def test_legacy_search_cannot_use_server_shared_credentials(db,monkeypatch):
    monkeypatch.setenv("ACQUISITION_SERPER_API_KEY","test-only")
    fetch=Mock();monkeypatch.setattr(customer,"external_acquisition_candidates",fetch)
    with pytest.raises(HTTPException,match="个人数据源"):
        create(db,source="Serper (Google)",keyword="heat exchanger",candidates=[row(country="Germany")])
    fetch.assert_not_called()


@pytest.mark.parametrize("source,key,body", [
    ("Serper (Google)", "ACQUISITION_SERPER_API_KEY", {"organic": [{"title": "Example", "link": "https://example.com", "snippet": "HVAC"}]}),
    ("Brave Search", "ACQUISITION_BRAVE_API_KEY", {"web": {"results": [{"title": "Example", "url": "https://example.com", "description": "HVAC"}]}}),
])
def test_search_request_uses_all_positive_conditions_without_fabricating_country(monkeypatch, source, key, body):
    monkeypatch.setenv(key, "test-only")
    response = Mock()
    response.read.return_value = json.dumps(body).encode()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    call = Mock(return_value=response)
    monkeypatch.setattr(customer, "urlopen", call)
    result = customer.external_acquisition_candidates(source, "heat exchanger", ["德国", "美国"], ["distributor"], ["HVAC"], 10, api_key="personal-test-key")
    request = call.call_args.args[0]
    request_text = request.data.decode() if request.data else request.full_url
    from urllib.parse import unquote
    request_text = unquote(request_text)
    assert "distributor" in request_text and "HVAC" in request_text
    assert result[0].country is None


def test_additive_schema_upgrade_retains_old_jobs():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crm_prospecting_jobs (id INTEGER PRIMARY KEY, min_score INTEGER)"))
        connection.execute(text("INSERT INTO crm_prospecting_jobs VALUES (1,40)"))
    ensure_acquisition_criteria_schema(engine)
    ensure_acquisition_criteria_schema(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT min_score, criteria_json FROM crm_prospecting_jobs")).one() == (40, None)
