"""Reference schedules and personal watchlists; no customer/lead statistics events."""
from datetime import datetime, timezone
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.mysql import LONGTEXT
from app.models.base import Base


class CommunicationPreference(Base):
    __tablename__ = 'crm_communication_preferences'
    __table_args__ = (UniqueConstraint('site_project_id', 'user_id', name='uq_communication_preferences'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    settings_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT,'mysql'), default='{}')


class CommunicationSetting(Base):
    __tablename__ = 'crm_communication_settings'
    __table_args__ = (UniqueConstraint('site_project_id', 'target_key', name='uq_communication_target'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    target_key: Mapped[str] = mapped_column(String(120))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('crm_leads.id', ondelete='CASCADE'), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('crm_customers.id', ondelete='CASCADE'), nullable=True, index=True)
    person_id: Mapped[int | None] = mapped_column(ForeignKey('crm_customer_people.id', ondelete='CASCADE'), nullable=True)
    settings_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


# Explicit cleanup also covers local/test databases where FK cascades are disabled.
from sqlalchemy import event, delete
from app.models.customer import CustomerPerson, ProjectContact


@event.listens_for(ProjectContact, 'before_delete')
def remove_project_contact_settings(mapper, connection, target):
    connection.execute(delete(CommunicationSetting).where(CommunicationSetting.site_project_id==target.site_project_id,CommunicationSetting.customer_id==target.contact_id))


@event.listens_for(CustomerPerson, 'before_delete')
def remove_person_settings(mapper, connection, target):
    connection.execute(delete(CommunicationSetting).where(CommunicationSetting.person_id==target.id))
