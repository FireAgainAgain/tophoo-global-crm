"""Current-user, project membership and module permission dependencies."""

import json

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import AUTH_COOKIE_NAME
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import Plan, ProjectMember, RevokedAccessToken, SiteProject, User, Workspace, WorkspaceMember
from app.services.billing_service import plan_modules
from app.core.modules import PROJECT_MODULES, CRM_CUSTOMER_MODULES, normalize_module_keys


bearer_scheme = HTTPBearer(auto_error=False)

ROLE_PERMISSIONS = {
    "top_admin": PROJECT_MODULES,
    "sales": frozenset((*CRM_CUSTOMER_MODULES, "rfq", "quotations")),
    "engineer": frozenset({"knowledge_base", "competitor_research", "rfq"}),
    "viewer": frozenset(),
}


def personal_module_dependency(module: str):
    """Authorize a personal feature without changing ownership of its records.

    The selected project is authoritative. Without context, use the union of
    accessible projects; omitting the header must never restore a revoked grant.
    Accounts without workspace memberships retain standalone personal tools.
    """
    def check(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        write = request.method not in {"GET", "HEAD", "OPTIONS"}
        selected = request.path_params.get('project_id') or request.headers.get('X-Project-ID')
        if selected is not None:
            try:
                project_id = int(selected)
            except (ValueError, TypeError):
                raise HTTPException(422, '项目编号无效。') from None
            (require_project_write if write else require_project_module)(project_id, user, db, module)
            return
        memberships = list(db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)))
        if not memberships:
            if module in {'url_navigation', 'mail_configuration'}:
                return
            raise HTTPException(403, '请先加入已授权项目。')
        projects = db.scalars(select(SiteProject).where(SiteProject.workspace_id.in_([m.workspace_id for m in memberships])))
        for project in projects:
            try:
                (require_project_write if write else require_project_module)(project.id, user, db, module)
            except HTTPException as error:
                if error.status_code != 403:
                    raise
            else:
                return
        # Owners may configure their personal tools before creating a first project.
        for member in memberships:
            if member.role not in {'owner', 'admin'} and not user.is_admin:
                continue
            if db.scalar(select(SiteProject.id).where(SiteProject.workspace_id == member.workspace_id).limit(1)):
                continue
            workspace = db.get(Workspace, member.workspace_id)
            plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
            if plan and module in plan_modules(plan):
                return
        raise HTTPException(403, '你没有该功能模块的' + ('编辑' if write else '查看') + '权限。')
    return check



def member_permissions(member: ProjectMember) -> set[str]:
    """Use explicit module assignments when present, otherwise retain role defaults."""
    if member.role == "top_admin":
        return set(PROJECT_MODULES)
    if member.permissions_json is not None:
        try:
            return set(normalize_module_keys(json.loads(member.permissions_json)))
        except (TypeError, json.JSONDecodeError):
            return set()
    return set(ROLE_PERMISSIONS.get(member.role, frozenset()))


def module_write_permissions(permissions, write_json, *, viewer=False) -> set[str]:
    """NULL retains legacy editor access; an explicit [] means read only."""
    if viewer:
        return set()
    if write_json is None:
        return set(permissions)
    try:
        return set(normalize_module_keys(json.loads(write_json))) & set(permissions)
    except (TypeError, ValueError):
        return set()


def member_write_permissions(member: ProjectMember) -> set[str]:
    if member.role == "top_admin":
        return set(PROJECT_MODULES)
    return module_write_permissions(member_permissions(member), member.write_permissions_json, viewer=member.role == "viewer")


def project_write_permissions(project_id: int, user: User, db: Session) -> set[str]:
    project = require_project_access(project_id, user, db)
    wm = require_workspace_member(project.workspace_id, user, db)
    workspace = db.get(Workspace, project.workspace_id)
    plan = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    available = set(plan_modules(plan)) if plan else set(PROJECT_MODULES)
    if user.is_admin or wm.role in {"owner", "admin"}:
        return available
    member = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project_id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    return (member_write_permissions(member) & available) if member else set()


def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    raw_token = credentials.credentials if credentials else request.cookies.get(AUTH_COOKIE_NAME)
    payload = decode_access_token(raw_token) if raw_token else None
    user_id = int(payload["sub"]) if payload else None
    user = db.get(User, user_id) if user_id else None
    token_revoked = bool(payload and db.scalar(select(RevokedAccessToken).where(RevokedAccessToken.jti == payload["jti"])))
    if not user or not user.is_active or token_revoked or payload.get("session_version", "") != user.session_version:
        return None
    return user


def get_current_user(user: User | None = Depends(get_optional_current_user)) -> User:
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅管理员可以访问此功能。")
    return user


def require_workspace_member(workspace_id: int, user: User, db: Session) -> WorkspaceMember:
    membership = db.scalar(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id))
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有该工作区的访问权限。")
    return membership


def require_project_access(project_id: int, user: User, db: Session) -> SiteProject:
    project = db.get(SiteProject, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="网站项目不存在。")
    workspace_member = require_workspace_member(project.workspace_id, user, db)
    if user.is_admin or workspace_member.role in {"owner", "admin"}:
        return project
    membership = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project.id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你尚未加入该项目。")
    return project


def require_project_manager(project_id: int, user: User, db: Session) -> SiteProject:
    project = require_project_access(project_id, user, db)
    workspace_member = require_workspace_member(project.workspace_id, user, db)
    if user.is_admin or workspace_member.role in {"owner", "admin"}:
        return project
    membership = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project.id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    if not membership or membership.role != "top_admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="仅项目顶级管理员可以管理项目成员和设置。")
    return project


def require_project_write(project_id: int, user: User, db: Session, module: str | None = None) -> SiteProject:
    if module is not None:
        project = require_project_module(project_id, user, db, module)
        if module not in project_write_permissions(project_id, user, db):
            raise HTTPException(status_code=403, detail="该模块为只读权限，无法新增、修改或删除数据。")
        return project
    project = require_project_access(project_id, user, db)
    workspace_member = require_workspace_member(project.workspace_id, user, db)
    if user.is_admin or workspace_member.role in {"owner", "admin"}:
        return project
    membership = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project.id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    if not membership or membership.role == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你在该项目中只有查看权限。")
    return project


def require_project_module(project_id: int, user: User, db: Session, module: str) -> SiteProject:
    if module not in PROJECT_MODULES:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="模块权限配置错误。")
    project = require_project_access(project_id, user, db)
    workspace = db.get(Workspace, project.workspace_id)
    access_profile = db.get(Plan, workspace.plan_id) if workspace and workspace.plan_id else None
    if access_profile and module not in plan_modules(access_profile):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前工作区授权未包含此功能。")
    workspace_member = require_workspace_member(project.workspace_id, user, db)
    if user.is_admin or workspace_member.role in {"owner", "admin"}:
        return project
    membership = db.scalar(select(ProjectMember).where(ProjectMember.site_project_id == project.id, ProjectMember.user_id == user.id, ProjectMember.is_active.is_(True)))
    if not membership or module not in member_permissions(membership):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="你没有当前项目的该功能模块权限。")
    return project


def crm_route_module(path: str) -> str:
    """Resolve shared CRM routers to the same leaf modules as the sidebar."""
    if path.startswith("/api/communication/"):
        return "communication_assistant"
    if path.startswith("/api/acquisition/") or "/auto-prospecting/" in path or "/prospecting" in path:
        return "auto_prospecting"
    if path.startswith("/api/customer-workflow/"):
        if "/leads" in path:
            return "leads"
        if "/pool" in path:
            return "customer_pool"
    return "customer_list"


def project_module_dependency(module: str):
    """Uniform HTTP guard, including routes that historically checked read access only."""
    def check(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
        project_id = request.path_params.get("project_id")
        if project_id is None:
            return
        path = request.url.path
        requested = crm_route_module(path) if module == "crm_workflow" else module
        require_project_module(int(project_id), user, db, requested)
        personal = (requested == "auto_prospecting" and "/connections/" in path) or (requested == "communication_assistant" and path.endswith("/preferences"))
        read_post = path.endswith(("/export/pdf", "/export/xlsx", "/weekly-report", "/imports/preview", "/conversion-preview")) or (requested == "communication_assistant" and path.endswith(("/preview", "/convert")))
        if path.endswith("/conversion-preview"):
            require_project_module(int(project_id), user, db, "customer_list")
        mutation = request.method in {"PUT", "PATCH", "DELETE"} or (request.method == "POST" and not read_post)
        if not personal and mutation:
            require_project_write(int(project_id), user, db, requested)
            # Moving data also writes the destination list.
            destination = "customer_list" if path.endswith(("/to-customers", "/restore")) else "leads" if path.endswith("/to-leads") else "customer_pool" if path.endswith("/release") else None
            if destination:
                require_project_write(int(project_id), user, db, destination)
    return check


def project_management_dependency(request: Request, user: User | None = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    project_id = request.path_params.get('project_id')
    if project_id is None or not request.url.path.startswith('/api/workspaces/') or '/links' in request.url.path:
        return
    if not user:
        raise HTTPException(401, '请先登录。')
    (require_project_module if request.method == 'GET' else require_project_write)(int(project_id), user, db, 'project_management')

