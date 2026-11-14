"""Workspace access-profile bootstrap and entitlement checks."""

import json

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import Plan, Subscription
from app.models.identity import User, Workspace, WorkspaceMember
from app.core.modules import CRM_CUSTOMER_MODULES, normalize_module_keys


DEFAULT_PLANS = (
    {
        "code": "free",
        "name": "CRM 基础授权",
        "description": "适用于小型团队的基础客户、知识库与询盘协作。",
        "monthly_price_cents": 0,
        "currency": "USD",
        "module_keys": ["project_management", "url_navigation", "ai_configuration", "mail_configuration", "knowledge_base", "communication_phrases", "competitor_research", *CRM_CUSTOMER_MODULES, "rfq", "quotations"],
        "project_limit": 3,
    },
    {
        "code": "professional",
        "name": "CRM 完整授权",
        "description": "覆盖知识库、竞品调研、客户与询价单的完整业务协作。",
        "monthly_price_cents": 500,
        "currency": "USD",
        "module_keys": ["project_management", "url_navigation", "ai_configuration", "mail_configuration", "knowledge_base", "communication_phrases", "competitor_research", *CRM_CUSTOMER_MODULES, "rfq", "quotations"],
        "project_limit": 10,
    },
)

def ensure_default_plans(db: Session) -> None:
    """Insert built-in plan definitions once; never overwrite later pricing edits."""
    for plan_data in DEFAULT_PLANS:
        plan = db.scalar(select(Plan).where(Plan.code == plan_data["code"]))
        if plan:
            # Upgrade only the known SEO-era defaults; administrator-created
            # access profiles remain untouched.
            try:
                legacy_modules = json.loads(plan.module_keys_json)
            except json.JSONDecodeError:
                legacy_modules = []
            normalized_modules = normalize_module_keys(legacy_modules, include_base=True)
            if normalized_modules != legacy_modules:
                plan.module_keys_json = json.dumps(normalized_modules, ensure_ascii=False)
            continue
        db.add(Plan(
            code=plan_data["code"],
            name=plan_data["name"],
            description=plan_data["description"],
            monthly_price_cents=plan_data["monthly_price_cents"],
            currency=plan_data["currency"],
            module_keys_json=json.dumps(plan_data["module_keys"]),
            project_limit=plan_data["project_limit"],
        ))
    db.commit()


def subscription_for_user(db: Session, user: User) -> tuple[Subscription, Plan]:
    """Return an active subscription; existing users are safely placed on free."""
    ensure_default_plans(db)
    subscription = db.scalar(select(Subscription).where(Subscription.user_id == user.id))
    if not subscription:
        free_plan = db.scalar(select(Plan).where(Plan.code == "free"))
        subscription = Subscription(user_id=user.id, plan_id=free_plan.id, status="active")
        db.add(subscription)
        db.commit()
        db.refresh(subscription)
    plan = db.get(Plan, subscription.plan_id)
    return subscription, plan


def plan_modules(plan: Plan) -> list[str]:
    try:
        return normalize_module_keys(json.loads(plan.module_keys_json), include_base=True)
    except (TypeError, ValueError):
        return []


def subscription_payload(db: Session, user: User) -> dict[str, object]:
    subscription, plan = subscription_for_user(db, user)
    return {
        "plan": {
            "code": plan.code,
            "name": plan.name,
            "description": plan.description,
            "monthly_price_cents": plan.monthly_price_cents,
            "currency": plan.currency,
            "project_limit": plan.project_limit,
            "module_keys": plan_modules(plan),
        },
        "status": subscription.status,
        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
    }


def require_module_access(db: Session, user: User, module_key: str) -> None:
    # Project routes additionally check the exact project's role and profile.
    workspaces = db.scalars(select(Workspace).join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id).where(WorkspaceMember.user_id == user.id)).all()
    if not any(module_key in plan_modules(db.get(Plan, workspace.plan_id)) for workspace in workspaces if workspace.plan_id):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"当前授权未包含此功能：{module_key}。",
        )
