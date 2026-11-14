"""Multi-model AI configuration, testing and feature bindings."""

from datetime import datetime
import json
import hashlib
import hmac
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import JWT_SECRET_KEY
from app.dependencies.auth import get_current_user, require_project_access, project_write_permissions
from app.models import AiFeatureBinding, AiModelConfiguration, User


router = APIRouter(prefix="/api/ai-config", tags=["AI configuration"])
_TEST_SIGNING_KEY = hashlib.sha256(("ai-connection-test:" + JWT_SECRET_KEY).encode()).digest()

PROVIDER_PRESETS = {
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "apply_url": "https://platform.deepseek.com/api_keys"},
    "zhipu": {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash-250414", "apply_url": "https://open.bigmodel.cn/usercenter/apikeys"},
    "qwen": {"name": "通义千问", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus", "apply_url": "https://bailian.console.aliyun.com/"},
    "moonshot": {"name": "Moonshot Kimi", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k", "apply_url": "https://platform.moonshot.cn/console/api-keys"},
    "openai": {"name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "apply_url": "https://platform.openai.com/api-keys"},
    "custom": {"name": "自定义兼容接口", "base_url": "", "model": "", "apply_url": ""},
}

FEATURES = {"mic_social": {"name": "MIC 产品社媒文案", "description": "每个产品独立维护一组四平台文案，根据产品资料生成英文介绍及中文翻译。"}}


class ModelPayload(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    provider: str = Field(default="custom", max_length=60)
    protocol: str = Field(default="openai-compatible", pattern=r"^openai-compatible$")
    model: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl
    api_key: str | None = Field(default=None, max_length=1000)
    enabled: bool = False
    temperature: float = Field(default=0.1, ge=0, le=2)
    max_tokens: int = Field(default=1024, ge=32, le=32000)
    request_timeout_seconds: int = Field(default=60, ge=5, le=120)
    notes: str | None = Field(default=None, max_length=2000)
    verification_token: str | None = None


class DraftTestPayload(ModelPayload):
    model_configuration_id: int | None = None


def connection_signature(project_id: int, item: AiModelConfiguration) -> str:
    values = [project_id, item.owner_user_id, item.model, item.base_url, item.api_key, item.temperature_tenths, item.max_tokens, item.request_timeout_seconds]
    return hmac.new(_TEST_SIGNING_KEY, json.dumps(values).encode(), hashlib.sha256).hexdigest()


class FeatureBindingPayload(BaseModel):
    model_configuration_id: int | None = None


def mask_key(value: str | None) -> str:
    return "••••••••" + value[-4:] if value else ""


def can_manage(project_id: int, user: User, db: Session) -> bool:
    return 'ai_configuration' in project_write_permissions(project_id, user, db)


def get_model(project_id: int, model_id: int, db: Session, user_id: int) -> AiModelConfiguration:
    item = db.scalar(select(AiModelConfiguration).where(AiModelConfiguration.id == model_id, AiModelConfiguration.site_project_id == project_id, AiModelConfiguration.owner_user_id == user_id))
    if not item:raise HTTPException(404, "模型配置不存在。")
    return item


def model_data(item: AiModelConfiguration, bindings: dict[int, list[str]] | None = None) -> dict:
    return {
        "id": item.id, "name": item.name, "provider": item.provider, "protocol": item.protocol,
        "model": item.model, "base_url": item.base_url, "api_key_masked": mask_key(item.api_key),
        "enabled": item.enabled, "temperature": item.temperature_tenths / 10,
        "max_tokens": item.max_tokens, "request_timeout_seconds": item.request_timeout_seconds,
        "notes": item.notes or "",
        "features": (bindings or {}).get(item.id, []), "last_test_status": item.last_test_status or "",
        "last_test_message": item.last_test_message or "", "last_tested_at": item.last_tested_at.isoformat() if item.last_tested_at else None,
    }


def completion_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    return url if url.endswith("/chat/completions") else url + "/chat/completions"


def chat(item: AiModelConfiguration, messages: list[dict], max_tokens: int | None = None) -> str:
    if not item.api_key:
        raise HTTPException(422, "该模型尚未保存 API Key。")
    body = json.dumps({"model": item.model, "messages": messages, "temperature": item.temperature_tenths / 10, "max_tokens": min(max_tokens or item.max_tokens, item.max_tokens)}).encode()
    request = Request(completion_url(item.base_url), data=body, method="POST", headers={"Authorization": f"Bearer {item.api_key}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=item.request_timeout_seconds) as response:
            data = json.load(response)
    except HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:300]
        raise HTTPException(422, f"模型服务返回 {error.code}：{detail}") from error
    except URLError as error:
        raise HTTPException(422, f"无法连接模型服务：{str(error.reason)[:180]}") from error
    except Exception as error:
        raise HTTPException(422, f"模型请求失败：{str(error)[:180]}") from error
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        raise HTTPException(422, "模型服务没有返回有效内容。")
    return content.strip()


def apply_payload(item: AiModelConfiguration, payload: ModelPayload) -> None:
    old_connection = (item.model, item.base_url, item.api_key, item.temperature_tenths, item.max_tokens, item.request_timeout_seconds)
    item.name = payload.name.strip()
    item.notes = (payload.notes or "").strip() or None
    item.provider = payload.provider.strip().lower() or "custom"
    item.protocol = payload.protocol
    item.model = payload.model.strip()
    item.base_url = str(payload.base_url).rstrip("/")
    if payload.api_key and payload.api_key.strip():
        item.api_key = payload.api_key.strip()
    if not item.name or not item.model:
        raise HTTPException(422, "配置名称和模型名称不能为空。")
    if not item.api_key:
        raise HTTPException(422, "请填写 API Key。")
    item.enabled = payload.enabled
    item.temperature_tenths = round(payload.temperature * 10)
    item.max_tokens = payload.max_tokens
    item.request_timeout_seconds = payload.request_timeout_seconds
    new_connection = (item.model, item.base_url, item.api_key, item.temperature_tenths, item.max_tokens, item.request_timeout_seconds)
    if old_connection != new_connection:
        item.last_test_status = None
        item.last_test_message = None
        item.last_tested_at = None
    if payload.verification_token and hmac.compare_digest(payload.verification_token, connection_signature(item.site_project_id, item)):
        item.last_test_status = "success"
        item.last_test_message = "当前连接参数已通过测试"
        item.last_tested_at = datetime.now()


def binding_map(project_id: int, db: Session, user_id: int) -> tuple[dict[int, list[str]], dict[str, int | None]]:
    rows = db.scalars(select(AiFeatureBinding).where(AiFeatureBinding.site_project_id == project_id, AiFeatureBinding.owner_user_id == user_id)).all()
    mapped: dict[int, list[str]] = {}
    selected: dict[str, int | None] = {}
    for row in rows:
        if row.feature_key not in FEATURES:
            continue
        selected[row.feature_key] = row.model_configuration_id
        if row.model_configuration_id:
            mapped.setdefault(row.model_configuration_id, []).append(row.feature_key)
    return mapped, selected


@router.get("/providers")
def list_providers(user: User = Depends(get_current_user)):
    return {"items": [{"id": key, **value} for key, value in PROVIDER_PRESETS.items()]}


@router.get("/projects/{project_id}")
def list_configuration(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    bindings, selected = binding_map(project_id, db, user.id)
    models = db.scalars(select(AiModelConfiguration).where(AiModelConfiguration.site_project_id == project_id, AiModelConfiguration.owner_user_id == user.id).order_by(AiModelConfiguration.updated_at.desc(), AiModelConfiguration.id.desc())).all()
    feature_rows = [{"key": key, **definition, "model_configuration_id": selected.get(key)} for key, definition in FEATURES.items()]
    return {"can_manage": can_manage(project_id, user, db), "models": [model_data(item, bindings) for item in models], "features": feature_rows}


@router.post("/projects/{project_id}/models", status_code=201)
def create_model(project_id: int, payload: ModelPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    item = AiModelConfiguration(site_project_id=project_id, owner_user_id=user.id, name=payload.name.strip(), model=payload.model.strip(), base_url=str(payload.base_url).rstrip("/"))
    apply_payload(item, payload)
    db.add(item)
    db.commit()
    db.refresh(item)
    return model_data(item)


@router.post("/projects/{project_id}/test-draft")
def test_draft(project_id: int, payload: DraftTestPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    existing = get_model(project_id, payload.model_configuration_id, db, user.id) if payload.model_configuration_id else None
    draft = AiModelConfiguration(site_project_id=project_id, owner_user_id=user.id, api_key=existing.api_key if existing else None)
    apply_payload(draft, payload)
    reply = chat(draft, [{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=min(64, draft.max_tokens))
    return {"status": "success", "message": "连接成功：" + reply[:120], "verification_token": connection_signature(project_id, draft)}


@router.put("/projects/{project_id}/models/{model_id}")
def update_model(project_id: int, model_id: int, payload: ModelPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    item = get_model(project_id, model_id, db, user.id)
    apply_payload(item, payload)
    db.commit()
    db.refresh(item)
    bindings, _ = binding_map(project_id, db, user.id)
    return model_data(item, bindings)


@router.delete("/projects/{project_id}/models/{model_id}")
def delete_model(project_id: int, model_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    item = get_model(project_id, model_id, db, user.id)
    bound = db.scalar(select(AiFeatureBinding).where(AiFeatureBinding.site_project_id == project_id, AiFeatureBinding.owner_user_id == user.id, AiFeatureBinding.model_configuration_id == model_id, AiFeatureBinding.feature_key.in_(FEATURES)))
    if bound:
        raise HTTPException(422, "该模型已绑定功能，请先解除功能绑定后再删除。")
    # Retired, invisible feature bindings must not trap the model in the UI.
    db.execute(delete(AiFeatureBinding).where(AiFeatureBinding.site_project_id == project_id, AiFeatureBinding.owner_user_id == user.id, AiFeatureBinding.model_configuration_id == model_id))
    db.delete(item)
    db.commit()
    return {"deleted": True}


@router.post("/projects/{project_id}/models/{model_id}/test")
def test_model(project_id: int, model_id: int, payload: ModelPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    item = get_model(project_id, model_id, db, user.id)
    apply_payload(item, payload)
    try:
        reply = chat(item, [{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=8)
        item.last_test_status = "success"
        item.last_test_message = f"连接成功：{reply[:120]}"
    except HTTPException as error:
        item.last_test_status = "failed"
        item.last_test_message = str(error.detail)[:1000]
    item.last_tested_at = datetime.now()
    db.commit()
    db.refresh(item)
    if item.last_test_status != "success":
        raise HTTPException(422, item.last_test_message)
    return {"status": "success", "message": item.last_test_message}


@router.put("/projects/{project_id}/features/{feature_key}")
def bind_feature(project_id: int, feature_key: str, payload: FeatureBindingPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    require_project_access(project_id, user, db)
    if feature_key not in FEATURES:
        raise HTTPException(404, "AI 功能不存在。")
    if payload.model_configuration_id is not None:
        model = get_model(project_id, payload.model_configuration_id, db, user.id)
        if not model.enabled:
            raise HTTPException(422, "只能绑定已启用的模型。")
        if model.last_test_status != "success":
            raise HTTPException(422, "请先测试模型连接成功，再绑定功能。")
    item = db.scalar(select(AiFeatureBinding).where(AiFeatureBinding.site_project_id == project_id, AiFeatureBinding.owner_user_id == user.id, AiFeatureBinding.feature_key == feature_key))
    if not item:
        item = AiFeatureBinding(site_project_id=project_id, owner_user_id=user.id, feature_key=feature_key)
        db.add(item)
    item.model_configuration_id = payload.model_configuration_id
    db.commit()
    return {"feature_key": feature_key, "model_configuration_id": payload.model_configuration_id}
