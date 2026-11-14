"""Structured acquisition is independent of model configuration."""

from pathlib import Path

from sqlalchemy import create_engine, text

from app.routers import ai_config
from app.services.project_service import retire_ai_search_parse_binding


def test_ai_parser_is_not_an_exposed_feature_or_endpoint():
    assert "auto_prospecting_parse" not in ai_config.FEATURES
    assert not any(route.path.endswith("/parse-prospecting") for route in ai_config.router.routes)


def test_search_form_has_no_ai_or_natural_language_controls():
    markup = (Path(__file__).resolve().parents[1] / "app/templates/partials/crm_auto_prospecting.html").read_text(encoding="utf-8")
    for name in ("keyword", "countries", "industry", "types", "exclude"):
        assert f'name="{name}"' in markup
    for marker in ('name="goal"', "data-acq-ai", "data-acq-mode", "自然语言"):
        assert marker not in markup
    for marker in ('name="min_score"', 'name="schedule"', "data-acq-depth", "搜索模式"):
        assert marker not in markup
    assert 'data-acq-filter="pending_review"' in markup


def test_retirement_only_removes_parser_bindings_and_keeps_models():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crm_ai_model_configurations (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(text("CREATE TABLE crm_ai_feature_bindings (id INTEGER PRIMARY KEY, feature_key TEXT, model_configuration_id INTEGER)"))
        connection.execute(text("INSERT INTO crm_ai_model_configurations VALUES (7, 'saved model')"))
        connection.execute(text("INSERT INTO crm_ai_feature_bindings VALUES (1, 'auto_prospecting_parse', 7), (2, 'other_feature', 7)"))
    retire_ai_search_parse_binding(engine)
    retire_ai_search_parse_binding(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT name FROM crm_ai_model_configurations")).scalar_one() == "saved model"
        assert connection.execute(text("SELECT feature_key FROM crm_ai_feature_bindings")).scalars().all() == ["other_feature"]


def test_retirement_accepts_database_without_ai_tables():
    retire_ai_search_parse_binding(create_engine("sqlite://"))
