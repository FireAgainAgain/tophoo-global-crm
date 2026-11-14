"""Project-scoped RFQ records."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Rfq(Base):
    __tablename__ = "crm_rfqs"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    number: Mapped[str] = mapped_column(String(40), index=True)
    inquiry_source: Mapped[str | None] = mapped_column(String(160), nullable=True)
    product_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    inquiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("crm_companies.id"), nullable=True, index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("crm_customers.id"), nullable=True, index=True)
    contact_person_id: Mapped[int | None] = mapped_column(nullable=True)
    contact_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    template_key: Mapped[str] = mapped_column(String(60), default="dry_cooler")
    status: Mapped[str] = mapped_column(String(40), default="待处理", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    application: Mapped[str | None] = mapped_column(String(260), nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(80), nullable=True)
    next_action_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters_json: Mapped[str] = mapped_column(Text, default="{}")
    parameter_notes_json: Mapped[str] = mapped_column(Text, default="{}")
    template_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class RfqTemplate(Base):
    __tablename__ = "crm_rfq_templates"
    __table_args__ = (UniqueConstraint("site_project_id", "code", name="uq_rfq_template_project_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name_en: Mapped[str] = mapped_column(String(160))
    name_zh: Mapped[str | None] = mapped_column(String(160), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fields_json: Mapped[str] = mapped_column(Text, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
