"""Regression checks that prevent SEO modules from returning to CRM."""

from app.main import app


def test_project_keeps_keywords_and_retires_seo_routes():
    paths = set(app.openapi()["paths"])
    forbidden_prefixes = (
        "/api/gsc",
        "/api/product-tdk",
        "/api/article-tdk",
        "/api/seo",
    )
    assert not any(path.startswith(forbidden_prefixes) for path in paths)
    assert any(path.startswith("/api/keywords") for path in paths)
    assert any(path.startswith("/api/mic-products") for path in paths)


def test_crm_routes_include_current_business_modules():
    paths = set(app.openapi()["paths"])
    assert not any(path.startswith(("/api/product-research", "/api/capabilities")) for path in paths)
    assert any(path.startswith("/api/contacts") for path in paths)
    assert any(path.startswith("/api/rfqs") for path in paths)
    assert any(path.startswith("/api/billing") for path in paths)
    assert not any(path.startswith("/api/selections") for path in paths)
