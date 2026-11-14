"""Lead contact records and immutable conversion snapshots."""
from datetime import date, datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base

class LeadOutreachDraft(Base):
    __tablename__='crm_lead_outreach_drafts'
    lead_id: Mapped[int]=mapped_column(ForeignKey('crm_leads.id',ondelete='CASCADE'),primary_key=True)
    recipient_name: Mapped[str]=mapped_column(String(160),default='')
    recipient_email: Mapped[str]=mapped_column(String(260),default='')
    subject: Mapped[str]=mapped_column(String(260),default='')
    content: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),default='')
    content_html: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),default='')
    content_translation: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),default='')
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now,onupdate=datetime.now)

class LeadInteraction(Base):
    __tablename__='crm_lead_interactions'
    id: Mapped[int]=mapped_column(primary_key=True)
    site_project_id: Mapped[int]=mapped_column(ForeignKey('site_projects.id'),index=True)
    lead_id: Mapped[int]=mapped_column(ForeignKey('crm_leads.id',ondelete='CASCADE'),index=True)
    created_by_user_id: Mapped[int | None]=mapped_column(ForeignKey('users.id'),nullable=True)
    occurred_at: Mapped[datetime]=mapped_column(DateTime,index=True)
    direction: Mapped[str]=mapped_column(String(20))
    contact_name: Mapped[str | None]=mapped_column(String(160),nullable=True)
    channel: Mapped[str]=mapped_column(String(40))
    subject: Mapped[str | None]=mapped_column(String(260),nullable=True)
    content: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'))
    content_translation: Mapped[str | None]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),nullable=True)
    content_html: Mapped[str | None]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),nullable=True)
    source_outreach_json: Mapped[str | None]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now,onupdate=datetime.now)

class LeadConversionHistory(Base):
    __tablename__='crm_lead_conversion_history'
    id: Mapped[int]=mapped_column(primary_key=True)
    site_project_id: Mapped[int]=mapped_column(ForeignKey('site_projects.id'),index=True)
    customer_id: Mapped[int]=mapped_column(ForeignKey('crm_customers.id',ondelete='CASCADE'),index=True)
    source_lead_id: Mapped[int]=mapped_column(index=True)
    converted_by_user_id: Mapped[int | None]=mapped_column(ForeignKey('users.id'),nullable=True)
    converted_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now)
    mode: Mapped[str]=mapped_column(String(20))
    snapshot_json: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'))
