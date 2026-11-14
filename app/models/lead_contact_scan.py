"""Source-backed contact scan results, separate from approved CRM contacts."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class LeadContactScan(Base):
    __tablename__ = 'crm_lead_contact_scans'
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey('crm_leads.id', ondelete='CASCADE'), index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    website: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    progress_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'), default='{}')
    result_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'), default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
