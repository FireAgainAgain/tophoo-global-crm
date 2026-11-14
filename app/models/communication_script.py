"""Reusable sales communication scripts and their folder tree."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CommunicationScriptCategory(Base):
    __tablename__ = "crm_communication_script_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("crm_communication_script_categories.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CommunicationScript(Base):
    __tablename__ = "crm_communication_scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("crm_communication_script_categories.id"), index=True)
    title: Mapped[str] = mapped_column(String(260))
    content: Mapped[str] = mapped_column(Text)
    content_format: Mapped[str] = mapped_column(String(20),default="markdown",server_default="markdown")
    content_html: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(),"mysql"),default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
