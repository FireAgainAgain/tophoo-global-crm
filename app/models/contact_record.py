"""Contact interaction history owned by CRM contacts."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ContactRecord(Base):
    __tablename__ = "crm_contact_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_customers.id"), index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    direction: Mapped[str] = mapped_column(String(20), default="outbound")
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    channel: Mapped[str] = mapped_column(String(40), default="email")
    subject: Mapped[str | None] = mapped_column(String(260), nullable=True)
    content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    content_translation: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT, "mysql"), nullable=True)
    content_html: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    source_outreach_json: Mapped[str | None] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
