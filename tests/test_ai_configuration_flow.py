"""Verify draft tests and saved connection verification are separate."""

from datetime import datetime
from unittest.mock import Mock

from app.models import AiModelConfiguration
from app.routers import ai_config


def payload(**changes):
    values = dict(name="解析模型", model="test-chat", base_url="https://example.com/v1",
                  api_key="test-only-key", enabled=True, temperature=0.1,
                  max_tokens=500, request_timeout_seconds=20)
    values.update(changes)
    return ai_config.ModelPayload(**values)


def test_connection_change_invalidates_success_and_retains_blank_key():
    item = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(item, payload())
    item.last_test_status = "success"
    item.last_tested_at = datetime.now()
    ai_config.apply_payload(item, payload(api_key=None, model="changed-chat"))
    assert item.api_key == "test-only-key"
    assert item.last_test_status is None
    assert item.last_tested_at is None


def test_verification_is_bound_to_exact_parameters_and_project():
    draft = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(draft, payload())
    token = ai_config.connection_signature(1, draft)
    saved = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(saved, payload(verification_token=token))
    assert saved.last_test_status == "success"
    changed = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(changed, payload(model="another", verification_token=token))
    assert changed.last_test_status is None
    another_project = AiModelConfiguration(owner_user_id=1, site_project_id=2)
    ai_config.apply_payload(another_project, payload(verification_token=token))
    assert another_project.last_test_status is None


def test_draft_testing_never_commits_or_modifies_saved_configuration(monkeypatch):
    saved = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(saved, payload())
    monkeypatch.setattr(ai_config, "require_project_access", lambda *args: None)
    monkeypatch.setattr(ai_config, "get_model", lambda *args: saved)
    monkeypatch.setattr(ai_config, "chat", lambda *args, **kwargs: "OK")
    db = Mock()
    draft = ai_config.DraftTestPayload(**payload(model="draft-chat", api_key=None).model_dump(),
                                      model_configuration_id=7)
    result = ai_config.test_draft(1, draft, Mock(id=1), db)
    assert result["status"] == "success"
    assert saved.model == "test-chat"
    db.commit.assert_not_called()
    db.add.assert_not_called()


def test_full_endpoint_does_not_get_appended_twice():
    assert ai_config.completion_url("https://example.com/v1/chat/completions/") == "https://example.com/v1/chat/completions"


def test_new_configuration_defaults():
    config = ai_config.ModelPayload(name="百炼", model="qwen-plus", base_url="https://example.com/v1")
    assert (config.temperature, config.max_tokens, config.request_timeout_seconds) == (0.1, 1024, 60)
    assert config.provider == "custom"


def test_selected_provider_is_saved_and_drafts_remain_disabled():
    item = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(item, payload(provider="qwen", enabled=False))
    assert ai_config.model_data(item)['provider'] == 'qwen'
    assert not item.enabled
    assert item.last_test_status is None
    token = ai_config.connection_signature(1, item)
    ai_config.apply_payload(item, payload(provider="qwen", verification_token=token, enabled=True))
    assert item.enabled and item.last_test_status == 'success'


def test_notes_round_trip_does_not_invalidate_connection():
    item = AiModelConfiguration(owner_user_id=1, site_project_id=1)
    ai_config.apply_payload(item, payload(notes=" 初始备注 "))
    item.last_test_status = "success"
    ai_config.apply_payload(item, payload(name="新名称", notes=" 免费额度用途\n到期时间待记录 "))
    assert ai_config.model_data(item)["notes"] == "免费额度用途\n到期时间待记录"
    assert item.last_test_status == "success"
    ai_config.apply_payload(item, payload(notes=""))
    assert ai_config.model_data(item)["notes"] == ""


def test_notes_schema_upgrade_is_additive_and_repeatable():
    from sqlalchemy import create_engine, inspect, text
    from app.services.project_service import ensure_ai_model_notes_schema

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE crm_ai_model_configurations (id INTEGER PRIMARY KEY, max_tokens INTEGER)"))
        connection.execute(text("INSERT INTO crm_ai_model_configurations (id, max_tokens) VALUES (1, 500)"))
    ensure_ai_model_notes_schema(engine)
    ensure_ai_model_notes_schema(engine)
    assert "notes" in {column["name"] for column in inspect(engine).get_columns("crm_ai_model_configurations")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT max_tokens, notes FROM crm_ai_model_configurations")).one() == (500, None)
