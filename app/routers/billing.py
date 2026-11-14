"""Read-only subscription APIs; payment confirmation will update subscriptions later."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.modules import MODULE_CATALOG
from app.dependencies.auth import get_current_user, get_optional_current_user
from app.models import Plan, User
from app.schemas.identity import TestCheckoutComplete
from app.services.billing_service import ensure_default_plans, plan_modules, subscription_for_user, subscription_payload
from app.core.config import TEST_CHECKOUT_ENABLED


router = APIRouter(prefix="/api/billing", tags=["Billing"])


@router.get("/pricing", include_in_schema=False)
def pricing_page(request: Request, user: User | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    if not user:
        return RedirectResponse(url="/login?next=/api/billing/pricing", status_code=status.HTTP_303_SEE_OTHER)
    ensure_default_plans(db)
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_price_cents)).all()
    plan_cards = [{
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "monthly_price_cents": plan.monthly_price_cents,
        "currency": plan.currency,
        "project_limit": plan.project_limit,
        "module_names": [MODULE_CATALOG.get(key, key) for key in plan_modules(plan)],
        "is_upgrade_available": plan.is_upgrade_available,
    } for plan in plans]
    return request.app.state.templates.TemplateResponse(request=request, name="pricing.html", context={"plans": plan_cards, "subscription": subscription_payload(db, user), "test_checkout_enabled": TEST_CHECKOUT_ENABLED})


@router.get("/checkout", include_in_schema=False)
def test_checkout_page(request: Request, plan: str = "professional", user: User | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    """Render a clearly labelled test-only checkout page; it never calls a payment provider."""
    if not user:
        return RedirectResponse(url=f"/login?next=/api/billing/checkout?plan={plan}", status_code=status.HTTP_303_SEE_OTHER)
    if not TEST_CHECKOUT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线上模拟支付已关闭。")
    target_plan = db.scalar(select(Plan).where(Plan.code == plan, Plan.is_active.is_(True), Plan.is_upgrade_available.is_(True)))
    if not target_plan or target_plan.code == "free":
        raise HTTPException(status_code=404, detail="套餐不存在或暂不可购买。")
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="test_checkout.html",
        context={"plan": target_plan, "subscription": subscription_payload(db, user)},
    )


@router.get("/plans")
def list_plans(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    ensure_default_plans(db)
    plans = db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.monthly_price_cents)).all()
    return [{
        "code": plan.code,
        "name": plan.name,
        "description": plan.description,
        "monthly_price_cents": plan.monthly_price_cents,
        "currency": plan.currency,
        "project_limit": plan.project_limit,
        "module_keys": plan_modules(plan),
    } for plan in plans]


@router.get("/me")
def current_subscription(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    return subscription_payload(db, user)


@router.post("/test-checkout/complete")
def complete_test_checkout(payload: TestCheckoutComplete, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    """Test-only payment confirmation. Replace with verified payment webhooks before launch."""
    if not TEST_CHECKOUT_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="线上模拟支付已关闭。")
    target_plan = db.scalar(select(Plan).where(Plan.code == payload.plan_code, Plan.is_active.is_(True), Plan.is_upgrade_available.is_(True)))
    if not target_plan or target_plan.code == "free":
        raise HTTPException(status_code=400, detail="测试支付套餐无效。")
    subscription, _ = subscription_for_user(db, user)
    subscription.plan_id = target_plan.id
    subscription.status = "active"
    db.commit()
    provider = "Stripe" if payload.payment_method == "stripe" else "支付宝"
    return {
        "message": f"测试支付成功：已通过{provider}模拟开通{target_plan.name}。未发生真实扣款。",
        "subscription": subscription_payload(db, user),
    }
