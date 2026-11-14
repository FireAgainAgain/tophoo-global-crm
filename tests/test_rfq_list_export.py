"""Retired RFQ transfer routes must stay unavailable."""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from tests.test_global_access import db, headers

@pytest.mark.parametrize('suffix', ['export/xlsx', *[f'{target}/export/{kind}' for target in ('1','templates/1') for kind in ('xlsx','md','pdf')]])
def test_rfq_exports_removed(db, suffix):
    client=TestClient(app)
    response=client.request('POST' if suffix=='export/xlsx' else 'GET', '/api/rfqs/projects/1/'+suffix, headers=headers(1))
    assert response.status_code==404
