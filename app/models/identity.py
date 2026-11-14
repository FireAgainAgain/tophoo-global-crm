"""User, workspace and site project models for multi-tenant data isolation."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    session_version: Mapped[str] = mapped_column(String(32), default="", server_default="")
    display_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    wechat_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    is_admin: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class RevokedAccessToken(Base):
    __tablename__ = "revoked_access_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    jti: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # Commercial access belongs to the shared workspace, never to an
    # individual member.  Project roles still decide what each member can do.
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")


class SiteProject(Base):
    __tablename__ = "site_projects"
    __table_args__ = (UniqueConstraint("workspace_id", "site_url", name="uq_site_project_workspace_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    site_url: Mapped[str] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ProjectMember(Base):
    """A user's explicit access and role within one project."""
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("site_project_id", "user_id", name="uq_project_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="sales")
    permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    write_permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    project_role_id: Mapped[int | None] = mapped_column(ForeignKey("project_roles.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ProjectRole(Base):
    """A reusable module-permission role defined by one project's top administrator."""

    __tablename__ = "project_roles"
    __table_args__ = (UniqueConstraint("site_project_id", "name", name="uq_project_role_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    write_permissions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ProjectLink(Base):
    """A useful external link saved under one website project."""

    __tablename__ = "project_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    url: Mapped[str] = mapped_column(String(1000))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
