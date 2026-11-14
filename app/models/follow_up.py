"""Project-scoped customer follow-up tasks. Times are stored as naive UTC."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FollowUpPlan(Base):
    __tablename__ = 'crm_follow_up_plans'
    __table_args__ = (Index('ix_followup_project_status_due', 'site_project_id', 'status', 'due_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('crm_customers.id'), index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey('crm_customer_people.id', ondelete='SET NULL'), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(260))
    due_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey('crm_contact_records.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
