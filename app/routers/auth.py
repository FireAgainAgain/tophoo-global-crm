"""Account, workspace and site project APIs."""

import json
from datetime import date, datetime, timezone
from urllib.parse import quote
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, AUTH_COOKIE_NAME, AUTH_COOKIE_SECURE
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.dependencies.auth import ROLE_PERMISSIONS, bearer_scheme, get_current_user, get_optional_current_user, member_permissions, member_write_permissions, module_write_permissions, project_write_permissions, require_admin, require_project_access, require_project_manager, require_project_write, require_workspace_member
from app.core.modules import MODULE_CATALOG, PROJECT_MODULES, module_catalog_payload, normalize_module_keys
from app.models import Company, Customer, Plan, ProjectCompany, ProjectContact, ProjectLink, ProjectMember, ProjectRole, RevokedAccessToken, Rfq, SiteProject, Subscription, User, Workspace, WorkspaceMember
from app.schemas.identity import AdminCreateUserRequest, AdminPlanCreateRequest, AdminPlanUpdateRequest, AdminUpdateUserRequest, LoginRequest, ProfileUpdateRequest, ProjectLinkMoveRequest, ProjectLinkRequest, ProjectMemberRequest, ProjectMemberRoleRequest, ProjectRoleRequest, SiteProjectDeleteRequest, SiteProjectMoveRequest, SiteProjectRequest, SiteProjectUpdateRequest, WorkspaceMemberRequest, WorkspaceRequest
from app.services.billing_service import plan_modules
from app.services.project_service import delete_project_cascade
from app.services.project_link_pdf import export_project_links_pdf
from app.schemas.identity import AdminUserPasswordRequest


router = APIRouter(tags=["Identity"])


def user_payload(user: User) -> dict[str, object]:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "phone": user.phone, "wechat_id": user.wechat_id, "is_admin": user.is_admin, "is_active": user.is_active}


def project_payload(project: SiteProject, role: str | None = None, permissions: list[str] | None = None) -> dict[str, object]:
    payload = {
        "id": project.id,
        "name": project.name,
        "site_url": project.site_url,
        "sort_order": project.sort_order,
    }
    if role:
        payload["role"] = role
        payload["permissions"] = sorted(permissions if permissions is not None else (PROJECT_MODULES if role == "top_admin" else ROLE_PERMISSIONS.get(role, frozenset())))
    return payload


def project_link_payload(link: ProjectLink) -> dict[str, object]:
    return {"id": link.id, "name": link.name, "url": link.url, "sort_order": link.sort_order}


def project_markdown(project: SiteProject) -> str:
    return "\n".join([
        f"# {project.name}",
        "",
        f"导出日期：{date.today():%Y-%m-%d}",
        "",
        "## 项目资料",
        "",
        f"- 网站地址：{project.site_url}",
        "",
    ])


def workspace_projects(db: Session, workspace_id: int) -> list[SiteProject]:
    return list(db.scalars(select(SiteProject).where(SiteProject.workspace_id == workspace_id).order_by(SiteProject.sort_order.asc(), SiteProject.created_at.asc(), SiteProject.id.asc())))


def project_member_payload(member: ProjectMember, user: User) -> dict[str, object]:
    return {"id": member.id, "user_id": user.id, "display_name": user.display_name, "email": user.email, "role": member.role, "project_role_id": member.project_role_id, "permissions": sorted(member_permissions(member)), "write_permissions": sorted(member_write_permissions(member)), "last_accessed_at": member.last_accessed_at.replace(tzinfo=timezone.utc).isoformat() if member.last_accessed_at else None, "is_active": member.is_active}


def workspace_member_payload(member: WorkspaceMember, user: User) -> dict[str, object]:
    return {"user_id": user.id, "display_name": user.display_name, "email": user.email, "role": member.role}


def requested_permissions(role: str, permissions: list[str]) -> list[str]:
    values = permissions if permissions or role == "custom" else list(ROLE_PERMISSIONS.get(role, frozenset()))
    return normalize_module_keys(values)


def project_role_payload(role: ProjectRole) -> dict[str, object]:
    try:
        permissions = normalize_module_keys(json.loads(role.permissions_json or "[]"))
    except json.JSONDecodeError:
        permissions = []
    return {"id": role.id, "name": role.name, "permissions": permissions, "write_permissions": sorted(module_write_permissions(permissions, role.write_permissions_json))}


def role_assignment(db: Session, project_id: int, role_id: int | None, fallback_role: str, fallback_permissions: list[str]) -> tuple[int | None, str, list[str]]:
    if role_id is None:
        if fallback_role not in {"top_admin", "sales", "custom"}:
            raise HTTPException(status_code=400, detail="请选择项目角色。")
        return None, fallback_role, requested_permissions(fallback_role, fallback_permissions)
    role = db.scalar(select(ProjectRole).where(ProjectRole.id == role_id, ProjectRole.site_project_id == project_id))
    if not role:
        raise HTTPException(status_code=400, detail="所选项目角色不存在。")
    if fallback_role == "top_admin":
        raise HTTPException(status_code=400, detail="顶级管理员不能同时指定自定义角色。")
    return role.id, "custom", project_role_payload(role)["permissions"]



def write_assignment(payload, permissions, *, existing=None, db=None, project_id=None):
    if getattr(payload, "project_role_id", None) is not None:
        role = db.scalar(select(ProjectRole).where(ProjectRole.id == payload.project_role_id, ProjectRole.site_project_id == project_id))
        return role.write_permissions_json
    if getattr(payload, "role", None) == "viewer":
        return "[]"
    if payload.write_permissions is None:
        return json.dumps(sorted(module_write_permissions(permissions, existing)), ensure_ascii=False) if existing is not None else None
    writes = normalize_module_keys(payload.write_permissions)
    if not set(writes).issubset(permissions):
        raise HTTPException(422, "可编辑权限必须同时具有该模块的查看权限。")
    return json.dumps(writes, ensure_ascii=False)


def accessible_projects(db: Session, workspace_id: int, user: User) -> list[tuple[SiteProject, str, list[str]]]:
    membership = require_workspace_member(workspace_id, user, db)
    workspace = db.get(Workspace, workspace_id)
    plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    available_modules = set(plan_modules(plan)) if plan else set(PROJECT_MODULES)
    if user.is_admin or membership.role in {"owner", "admin"}:
        return [(project, "top_admin", sorted(set(PROJECT_MODULES) & available_modules)) for project in workspace_projects(db, workspace_id)]
    rows = db.execute(
        select(SiteProject, ProjectMember)
        .join(ProjectMember, ProjectMember.site_project_id == SiteProject.id)
        .where(SiteProject.workspace_id == workspace_id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True))
        .order_by(SiteProject.sort_order.asc(), SiteProject.created_at.asc(), SiteProject.id.asc())
    ).all()
    return [(project, member.role, sorted(member_permissions(member) & available_modules)) for project, member in rows]


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    """Render the CRM sign-in page."""
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="login.html",
    )


@router.get("/account", include_in_schema=False)
def account_page(request: Request, user: User | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    """Render the protected account settings page."""
    if not user:
        return RedirectResponse(url="/login?next=/account", status_code=status.HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        request=request,
        name="account.html",
        context={"user": user_payload(user)},
    )


@router.get("/admin/users", include_in_schema=False)
def admin_users_page(request: Request, user: User = Depends(require_admin)):
    """Render the administrator-only test user management page."""
    return request.app.state.templates.TemplateResponse(request=request, name="admin_users.html", context={"user": user_payload(user)})


@router.get("/admin/plans", include_in_schema=False)
def admin_plans_page(request: Request, user: User = Depends(require_admin)):
    return request.app.state.templates.TemplateResponse(request=request, name="admin_plans.html", context={"user": user_payload(user)})


@router.post("/api/auth/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict[str, object]:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码不正确。")
    access_token = issue_session(response, user)
    return {"user": user_payload(user), "access_token": access_token, "token_type": "bearer"}


def issue_session(response: Response, user: User) -> str:
    access_token = create_access_token(user.id, user.session_version)
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )
    return access_token


@router.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    raw_token = credentials.credentials if credentials else request.cookies.get(AUTH_COOKIE_NAME)
    payload = decode_access_token(raw_token) if raw_token else None
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效。")
    if not db.scalar(select(RevokedAccessToken).where(RevokedAccessToken.jti == payload["jti"])):
        expires_at = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc).replace(tzinfo=None)
        db.add(RevokedAccessToken(jti=str(payload["jti"]), expires_at=expires_at))
        db.commit()
    response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")
    return {"message": "已安全退出登录。"}


@router.get("/api/auth/me")
def me(user: User = Depends(get_current_user)) -> dict[str, object]:
    return user_payload(user)


@router.patch("/api/auth/me")
def update_me(payload: ProfileUpdateRequest, response: Response, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    if payload.new_password:
        if not payload.current_password or not verify_password(payload.current_password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确。")
        user.password_hash = hash_password(payload.new_password)
        user.session_version = uuid4().hex
    user.display_name = payload.display_name.strip()
    user.phone = payload.phone
    user.wechat_id = payload.wechat_id.strip() if payload.wechat_id else None
    db.commit()
    db.refresh(user)
    result = user_payload(user)
    if payload.new_password:
        result["access_token"] = issue_session(response, user)
    return result


def admin_user_payload(db: Session, user: User) -> dict[str, object]:
    workspace = db.scalar(select(Workspace).where(Workspace.owner_id == user.id).order_by(Workspace.id))
    plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    # “已参与项目”同时包括自己工作区内的项目和被其他项目邀请加入的项目。
    project_count = db.scalar(
        select(func.count(func.distinct(SiteProject.id)))
        .select_from(SiteProject)
        .outerjoin(Workspace, Workspace.id == SiteProject.workspace_id)
        .outerjoin(ProjectMember, ProjectMember.site_project_id == SiteProject.id)
        .where(
            (Workspace.owner_id == user.id)
            | ((ProjectMember.user_id == user.id) & ProjectMember.is_active.is_(True))
        )
    ) or 0
    return {**user_payload(user), "plan": admin_plan_payload(plan) if plan else None, "project_count": project_count}


@router.get("/api/admin/users")
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    users = db.scalars(select(User).order_by(User.created_at.desc(), User.id.desc())).all()
    return [admin_user_payload(db, user) for user in users]


def admin_plan_payload(plan: Plan) -> dict[str, object]:
    return {"id": plan.id, "code": plan.code, "name": plan.name, "description": plan.description, "monthly_price": plan.monthly_price_cents / 100, "currency": plan.currency, "project_limit": plan.project_limit, "module_keys": plan_modules(plan), "is_active": plan.is_active, "is_upgrade_available": plan.is_upgrade_available}


@router.get("/api/admin/plans")
def list_admin_plans(admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, object]:
    from app.services.billing_service import ensure_default_plans
    ensure_default_plans(db)
    plans = db.scalars(select(Plan).order_by(Plan.monthly_price_cents, Plan.id)).all()
    return {"plans": [admin_plan_payload(plan) for plan in plans], "modules": module_catalog_payload()}


@router.patch("/api/admin/plans/{plan_id}")
def update_admin_plan(plan_id: int, payload: AdminPlanUpdateRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, object]:
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="授权模板不存在。")
    invalid_keys = set(payload.module_keys) - set(MODULE_CATALOG)
    if invalid_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="包含无效功能模块。")
    if plan.code == "free" and not payload.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="基础授权不能停用，现有工作区需要保底授权。")
    if payload.code and payload.code != plan.code:
        if plan.code == "free":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="免费版的系统标识不能修改。")
        if db.scalar(select(Plan).where(Plan.code == payload.code)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="授权模板标识已存在，请换一个。")
        plan.code = payload.code
    plan.name = payload.name.strip()
    plan.description = payload.description.strip()
    plan.monthly_price_cents = round(payload.monthly_price * 100)
    plan.currency = payload.currency
    plan.project_limit = payload.project_limit
    plan.module_keys_json = json.dumps(normalize_module_keys(payload.module_keys, include_base=True), ensure_ascii=False)
    plan.is_active = payload.is_active
    plan.is_upgrade_available = payload.is_upgrade_available
    db.commit()
    db.refresh(plan)
    return {"message": "工作区授权模板已保存，新的功能范围立即生效。", "plan": admin_plan_payload(plan)}


@router.post("/api/admin/plans", status_code=status.HTTP_201_CREATED)
def create_admin_plan(payload: AdminPlanCreateRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, object]:
    if db.scalar(select(Plan).where(Plan.code == payload.code)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="授权模板标识已存在，请换一个英文标识。")
    invalid_keys = set(payload.module_keys) - set(MODULE_CATALOG)
    if invalid_keys:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="包含无效功能模块。")
    plan = Plan(code=payload.code, name=payload.name.strip(), description=payload.description.strip(), monthly_price_cents=round(payload.monthly_price * 100), currency=payload.currency, project_limit=payload.project_limit, module_keys_json=json.dumps(normalize_module_keys(payload.module_keys, include_base=True), ensure_ascii=False), is_active=payload.is_active, is_upgrade_available=payload.is_upgrade_available)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"message": "新工作区授权模板已创建。", "plan": admin_plan_payload(plan)}


@router.delete("/api/admin/plans/{plan_id}")
def delete_admin_plan(plan_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    plan = db.get(Plan, plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="授权模板不存在。")
    if plan.code == "free":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="基础授权是系统保底配置，不能删除。")
    default_plan = db.scalar(select(Plan).where(Plan.code == "free"))
    if not default_plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未找到基础授权，暂时不能删除。")
    assigned = db.scalar(select(func.count()).select_from(Subscription).where(Subscription.plan_id == plan.id)) or 0
    if assigned:
        db.query(Subscription).filter(Subscription.plan_id == plan.id).update({Subscription.plan_id: default_plan.id}, synchronize_session=False)
    workspace_assigned = db.scalar(select(func.count()).select_from(Workspace).where(Workspace.plan_id == plan.id)) or 0
    if workspace_assigned:
        db.query(Workspace).filter(Workspace.plan_id == plan.id).update({Workspace.plan_id: default_plan.id}, synchronize_session=False)
    db.delete(plan)
    db.commit()
    return {"message": f"授权模板已删除。{f' 已将 {workspace_assigned} 个工作区调整为基础授权。' if workspace_assigned else ''}"}


@router.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def create_test_user(payload: AdminCreateUserRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, object]:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已经存在。")
    plan = db.scalar(select(Plan).where(Plan.code == payload.plan_code, Plan.is_active.is_(True)))
    if not plan:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="工作区授权不存在或已停用。")
    user = User(email=email, password_hash=hash_password(payload.password), display_name=payload.display_name.strip(), phone=payload.phone, wechat_id=payload.wechat_id.strip() if payload.wechat_id else None)
    db.add(user)
    db.flush()
    workspace = Workspace(name=f"{user.display_name} 的工作区", owner_id=user.id, plan_id=plan.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    return admin_user_payload(db, user)


@router.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, payload: AdminUpdateUserRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, object]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")
    if payload.is_active is False and user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用当前管理员账号。")
    if payload.email is not None:
        email = str(payload.email).lower()
        if db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != user.id)):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已经存在。")
    plan = None
    if payload.plan_code is not None:
        plan = db.scalar(select(Plan).where(Plan.code == payload.plan_code, Plan.is_active.is_(True)))
        if not plan:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="工作区授权不存在或已停用。")
    if payload.email is not None:
        user.email = email
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
    if "phone" in payload.model_fields_set:
        user.phone = payload.phone
    if "wechat_id" in payload.model_fields_set:
        user.wechat_id = payload.wechat_id.strip() if payload.wechat_id else None
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if plan is not None:
        db.query(Workspace).filter(Workspace.owner_id == user.id).update({Workspace.plan_id: plan.id}, synchronize_session=False)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该邮箱已经存在。")
    db.refresh(user)
    return admin_user_payload(db, user)


@router.patch("/api/admin/users/{user_id}/password")
def reset_admin_user_password(user_id: int, payload: AdminUserPasswordRequest, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")
    user.password_hash = hash_password(payload.new_password)
    user.session_version = uuid4().hex
    db.commit()
    return {"message": "密码已修改，下次登录请使用新密码。"}


@router.delete("/api/admin/users/{user_id}")
def delete_admin_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict[str, str]:
    """Permanently remove a user and the workspace data owned by that user."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在。")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除当前管理员账号。")

    owned_workspaces = db.scalars(select(Workspace).where(Workspace.owner_id == user.id)).all()
    workspace_ids = [workspace.id for workspace in owned_workspaces]
    deleted_projects = 0
    for workspace in owned_workspaces:
        projects = db.scalars(select(SiteProject).where(SiteProject.workspace_id == workspace.id)).all()
        for project in projects:
            delete_project_cascade(db, project.id)
            deleted_projects += 1

    if workspace_ids:
        from app.models import CustomerPerson
        db.execute(delete(CustomerPerson).where(CustomerPerson.customer_id.in_(select(Customer.id).where(Customer.workspace_id.in_(workspace_ids)))))
        db.execute(delete(Customer).where(Customer.workspace_id.in_(workspace_ids)))
        db.execute(delete(Company).where(Company.workspace_id.in_(workspace_ids)))
        db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id.in_(workspace_ids)))
        db.execute(delete(Workspace).where(Workspace.id.in_(workspace_ids)))

    from app.models.follow_up import FollowUpPlan
    db.execute(update(FollowUpPlan).where(FollowUpPlan.owner_user_id==user.id,FollowUpPlan.status=='pending').values(status='cancelled',cancellation_reason='负责人账号已删除'))
    db.execute(update(FollowUpPlan).where(FollowUpPlan.owner_user_id==user.id).values(owner_user_id=None))
    # Memberships in other users' workspaces are removed without touching their data.
    db.execute(delete(ProjectMember).where(ProjectMember.user_id == user.id))
    db.execute(delete(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
    db.execute(update(ProjectCompany).where(ProjectCompany.owner_user_id == user.id).values(owner_user_id=None))
    db.execute(update(ProjectContact).where(ProjectContact.owner_user_id == user.id).values(owner_user_id=None))
    db.execute(update(Rfq).where(Rfq.owner_user_id == user.id).values(owner_user_id=None))
    from app.models.communication import CommunicationPreference
    db.execute(delete(CommunicationPreference).where(CommunicationPreference.user_id == user.id))
    from app.models import UserLink, UserLinkCategory, UserLinkMigration
    db.execute(delete(UserLink).where(UserLink.owner_user_id == user.id))
    db.execute(delete(UserLinkCategory).where(UserLinkCategory.owner_user_id == user.id))
    db.execute(delete(UserLinkMigration).where(UserLinkMigration.owner_user_id == user.id))
    db.execute(delete(Subscription).where(Subscription.user_id == user.id))
    from app.models.mail import MailConfiguration, MailDelivery, MailAccount
    db.execute(delete(MailDelivery).where(MailDelivery.owner_user_id == user.id))
    db.execute(delete(MailAccount).where(MailAccount.owner_user_id == user.id))
    db.execute(delete(MailConfiguration).where(MailConfiguration.owner_user_id == user.id))
    db.delete(user)
    db.commit()
    return {"message": f"用户已删除。已同时清理 {len(workspace_ids)} 个工作区和 {deleted_projects} 个项目。"}


@router.get("/api/workspaces")
def list_workspaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    memberships = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)).all()
    workspaces = []
    for membership in memberships:
        workspace = db.get(Workspace, membership.workspace_id)
        if workspace:
            workspaces.append({"id": workspace.id, "name": workspace.name, "role": membership.role})
    return workspaces


@router.post("/api/workspaces", status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    default_plan = db.scalar(select(Plan).where(Plan.code == "free"))
    workspace = Workspace(name=payload.name.strip(), owner_id=user.id, plan_id=default_plan.id if default_plan else None)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    return {"id": workspace.id, "name": workspace.name, "role": "owner"}


@router.get("/api/workspaces/{workspace_id}/projects")
def list_projects(workspace_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [{**project_payload(project, role, permissions), "write_permissions": sorted(project_write_permissions(project.id, user, db) & set(permissions))} for project, role, permissions in accessible_projects(db, workspace_id, user)]


@router.post("/api/projects/{project_id}/visit")
def record_project_visit(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Only foreground project visits call this; background data reads do not."""
    from datetime import timedelta
    require_project_access(project_id, user, db)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(seconds=60)
    db.execute(update(ProjectMember).where(
        ProjectMember.site_project_id == project_id, ProjectMember.user_id == user.id,
        ProjectMember.is_active.is_(True),
        (ProjectMember.last_accessed_at.is_(None)) | (ProjectMember.last_accessed_at < cutoff),
    ).values(last_accessed_at=now))
    db.commit()
    return {"recorded": True}


@router.get("/api/workspaces/{workspace_id}/members")
def list_workspace_members(workspace_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    require_workspace_member(workspace_id, user, db)
    rows = db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id).order_by(User.display_name, User.id)).all()
    return [workspace_member_payload(member, member_user) for member, member_user in rows]


@router.post("/api/workspaces/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
def add_workspace_member(workspace_id: int, payload: WorkspaceMemberRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    requester = require_workspace_member(workspace_id, user, db)
    if not user.is_admin and requester.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅工作区管理员可以添加工作区成员。")
    invited = db.scalar(select(User).where(User.email == payload.email.lower(), User.is_active.is_(True)))
    if not invited:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到已启用的用户，请先创建或邀请该账号。")
    member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == invited.id))
    if member:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该用户已经是工作区成员。")
    member = WorkspaceMember(workspace_id=workspace_id, user_id=invited.id, role=payload.role)
    db.add(member); db.commit(); db.refresh(member)
    return workspace_member_payload(member, invited)


@router.get("/api/workspaces/{workspace_id}/projects/{project_id}/members")
def list_project_members(workspace_id: int, project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    rows = db.execute(select(ProjectMember, User).join(User, User.id == ProjectMember.user_id).where(ProjectMember.site_project_id == project_id).order_by(ProjectMember.created_at, ProjectMember.id)).all()
    workspace_rows = db.execute(select(WorkspaceMember, User).join(User, User.id == WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id).order_by(User.display_name, User.id)).all()
    workspace = db.get(Workspace, workspace_id)
    plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    available = set(plan_modules(plan)) if plan else set(PROJECT_MODULES)
    workspace_roles = {member.user_id:member.role for member, _ in workspace_rows}
    members = []
    for member, member_user in rows:
        elevated = member_user.is_admin or workspace_roles.get(member.user_id) in {"owner", "admin"}
        data = project_member_payload(member, member_user)
        data["access_source"] = "系统管理员" if member_user.is_admin else "工作区管理员" if elevated else "项目角色"
        data["effective_permissions"] = sorted((set(PROJECT_MODULES) if elevated else member_permissions(member)) & available) if member.is_active or elevated else []
        members.append(data)
        data["effective_write_permissions"] = sorted((set(PROJECT_MODULES) if elevated else member_write_permissions(member)) & available) if member.is_active or elevated else []
    return {"members":members, "workspace_members":[workspace_member_payload(member, member_user) for member, member_user in workspace_rows], "modules":[{**item, "available":item["key"] in available} for item in module_catalog_payload() if not item["is_base"]]}


@router.get("/api/workspaces/{workspace_id}/projects/{project_id}/roles")
def list_project_roles(workspace_id: int, project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    return [project_role_payload(role) for role in db.scalars(select(ProjectRole).where(ProjectRole.site_project_id == project_id).order_by(ProjectRole.created_at, ProjectRole.id)).all()]


@router.post("/api/workspaces/{workspace_id}/projects/{project_id}/roles", status_code=status.HTTP_201_CREATED)
def create_project_role(workspace_id: int, project_id: int, payload: ProjectRoleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    role = ProjectRole(site_project_id=project_id, name=payload.name.strip(), permissions_json=json.dumps(normalize_module_keys(payload.permissions), ensure_ascii=False), write_permissions_json=write_assignment(payload, normalize_module_keys(payload.permissions)))
    db.add(role)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="项目内已有同名角色。")
    db.refresh(role)
    return project_role_payload(role)


@router.put("/api/workspaces/{workspace_id}/projects/{project_id}/roles/{role_id}")
def update_project_role(workspace_id: int, project_id: int, role_id: int, payload: ProjectRoleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    role = db.scalar(select(ProjectRole).where(ProjectRole.id == role_id, ProjectRole.site_project_id == project_id))
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目角色不存在。")
    permissions = normalize_module_keys(payload.permissions)
    role.write_permissions_json = write_assignment(payload, permissions, existing=role.write_permissions_json)
    role.name, role.permissions_json = payload.name.strip(), json.dumps(permissions, ensure_ascii=False)
    for member in db.scalars(select(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.project_role_id == role_id)).all():
        member.permissions_json = json.dumps(permissions, ensure_ascii=False)
        member.write_permissions_json = role.write_permissions_json
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="项目内已有同名角色。")
    db.refresh(role)
    return project_role_payload(role)


@router.delete("/api/workspaces/{workspace_id}/projects/{project_id}/roles/{role_id}")
def delete_project_role(workspace_id: int, project_id: int, role_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    role = db.scalar(select(ProjectRole).where(ProjectRole.id == role_id, ProjectRole.site_project_id == project_id))
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目角色不存在。")
    if db.scalar(select(ProjectMember.id).where(ProjectMember.site_project_id == project_id, ProjectMember.project_role_id == role_id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该角色仍分配给项目成员，不能删除。")
    db.delete(role); db.commit()
    return {"deleted": True}


@router.post("/api/workspaces/{workspace_id}/projects/{project_id}/members", status_code=status.HTTP_201_CREATED)
def add_project_member(workspace_id: int, project_id: int, payload: ProjectMemberRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    member_user = db.get(User, payload.user_id) if payload.user_id else db.scalar(select(User).where(func.lower(User.email) == payload.email.lower(), User.is_active.is_(True)))
    if member_user and not member_user.is_active:
        member_user = None
    if not member_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到已启用的用户，请先创建该账号。")
    workspace_member = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == member_user.id))
    if not workspace_member:
        workspace_member = WorkspaceMember(workspace_id=workspace_id, user_id=member_user.id, role="member")
        db.add(workspace_member)
    member = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.user_id == member_user.id))
    role_id, role_name, permissions = role_assignment(db, project_id, payload.project_role_id, payload.role, payload.permissions)
    writes = write_assignment(payload, permissions, db=db, project_id=project_id)
    if member:
        member.write_permissions_json = writes
        member.role = role_name; member.project_role_id = role_id; member.permissions_json = json.dumps(permissions, ensure_ascii=False); member.is_active = True
    else:
        member = ProjectMember(site_project_id=project_id, user_id=member_user.id, role=role_name, project_role_id=role_id, permissions_json=json.dumps(permissions, ensure_ascii=False), write_permissions_json=writes)
        db.add(member)
    db.commit(); db.refresh(member)
    return project_member_payload(member, member_user)


@router.patch("/api/workspaces/{workspace_id}/projects/{project_id}/members/{member_id}")
def update_project_member(workspace_id: int, project_id: int, member_id: int, payload: ProjectMemberRoleRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    member = db.scalar(select(ProjectMember).where(ProjectMember.id == member_id, ProjectMember.site_project_id == project_id))
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员不存在。")
    if member.role == "top_admin" and payload.role != "top_admin":
        admins = db.scalar(select(func.count()).select_from(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.role == "top_admin", ProjectMember.is_active.is_(True))) or 0
        if admins <= 1:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目至少需要保留一位顶级管理员。")
    role_id, role_name, permissions = role_assignment(db, project_id, payload.project_role_id, payload.role, payload.permissions)
    member.write_permissions_json = write_assignment(payload, permissions, db=db, project_id=project_id)
    member.role = role_name; member.project_role_id = role_id; member.permissions_json = json.dumps(permissions, ensure_ascii=False); db.commit(); db.refresh(member)
    return project_member_payload(member, db.get(User, member.user_id))


@router.delete("/api/workspaces/{workspace_id}/projects/{project_id}/members/{member_id}")
def remove_project_member(workspace_id: int, project_id: int, member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, bool]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    member = db.scalar(select(ProjectMember).where(ProjectMember.id == member_id, ProjectMember.site_project_id == project_id))
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目成员不存在。")
    admins = db.scalar(select(func.count()).select_from(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.role == "top_admin", ProjectMember.is_active.is_(True))) or 0
    if member.role == "top_admin" and admins <= 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="项目至少需要保留一位顶级管理员。")
    db.delete(member); db.commit()
    return {"deleted": True}


@router.get("/api/workspaces/{workspace_id}/projects/{project_id}/export/md")
def export_one_project_markdown(workspace_id: int, project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = require_project_access(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    today = date.today()
    filename = f"{project.name}_项目信息_{today.year}_{today.month}_{today.day}.md"
    return Response(project_markdown(project), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"})


@router.post("/api/workspaces/{workspace_id}/projects", status_code=status.HTTP_201_CREATED)
def create_project(workspace_id: int, payload: SiteProjectRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    workspace_member = require_workspace_member(workspace_id, user, db)
    if not user.is_admin and workspace_member.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅工作区管理员可以创建项目。")
    workspace = db.get(Workspace, workspace_id)
    plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    if not plan:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前工作区尚未配置授权。")
    if 'project_management' not in plan_modules(plan):
        raise HTTPException(403, '当前工作区授权未包含项目管理。')
    project_count = db.scalar(select(func.count()).select_from(SiteProject).where(SiteProject.workspace_id == workspace_id)) or 0
    if project_count >= plan.project_limit:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"当前工作区授权最多创建 {plan.project_limit} 个项目，请联系管理员调整授权。")
    project = SiteProject(
        workspace_id=workspace_id,
        name=payload.name.strip(),
        site_url=payload.site_url.strip(),
        sort_order=(db.scalar(select(func.max(func.coalesce(SiteProject.sort_order, 0))).where(SiteProject.workspace_id == workspace_id)) or 0) + 1,
    )
    db.add(project); db.flush()
    db.add(ProjectMember(site_project_id=project.id, user_id=user.id, role="top_admin", permissions_json=json.dumps(sorted(PROJECT_MODULES), ensure_ascii=False)))
    db.commit()
    db.refresh(project)
    return project_payload(project, "top_admin", sorted(PROJECT_MODULES))


@router.patch("/api/workspaces/{workspace_id}/projects/{project_id}")
def update_project(workspace_id: int, project_id: int, payload: SiteProjectUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_write(project_id, user, db, 'project_management')
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    for field in ("name", "site_url"):
        if field in payload.model_fields_set:
            value = getattr(payload, field)
            setattr(project, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(project)
    return project_payload(project)


@router.post("/api/workspaces/{workspace_id}/projects/{project_id}/move")
def move_project(workspace_id: int, project_id: int, payload: SiteProjectMoveRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, object]]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    projects = workspace_projects(db, workspace_id)
    index = next((position for position, candidate in enumerate(projects) if candidate.id == project.id), None)
    if index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    target_index = index - 1 if payload.direction == "up" else index + 1
    if 0 <= target_index < len(projects):
        other = projects[target_index]
        project.sort_order, other.sort_order = other.sort_order, project.sort_order
        db.commit()
    return [project_payload(item) for item in workspace_projects(db, workspace_id)]


@router.get("/api/workspaces/{workspace_id}/projects/{project_id}/links")
@router.get("/api/workspaces/{workspace_id}/projects/{project_id}/links/export/pdf")
@router.post("/api/workspaces/{workspace_id}/projects/{project_id}/links")
@router.post("/api/workspaces/{workspace_id}/projects/{project_id}/links/{link_id}/move")
@router.patch("/api/workspaces/{workspace_id}/projects/{project_id}/links/{link_id}")
@router.delete("/api/workspaces/{workspace_id}/projects/{project_id}/links/{link_id}")
def retired_project_links(user: User = Depends(get_current_user)):
    raise HTTPException(status_code=410, detail="项目共享网址已停用，请使用个人网址导航。")


@router.delete("/api/workspaces/{workspace_id}/projects/{project_id}", status_code=status.HTTP_200_OK)
def delete_project(workspace_id: int, project_id: int, payload: SiteProjectDeleteRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, object]:
    project = require_project_manager(project_id, user, db)
    if project.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    if payload.confirm_name.strip() != project.name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="输入的项目名称不匹配，未执行删除。")
    delete_project_cascade(db, project_id)
    db.commit()
    return {"message": "项目已删除。", "id": project_id}
