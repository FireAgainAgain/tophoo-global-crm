"""Personal SMTP connections and durable, idempotent delivery attempts."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MailConfiguration(Base):
    __tablename__ = 'user_mail_configurations'
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    sender_name: Mapped[str] = mapped_column(String(160), default='')
    email: Mapped[str] = mapped_column(String(260))
    host: Mapped[str] = mapped_column(String(260))
    port: Mapped[int]
    encryption: Mapped[str] = mapped_column(String(20), default='ssl')
    username: Mapped[str] = mapped_column(String(260))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'), default='')
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

class MailAccount(Base):
    """Additional private sender accounts; the original configuration remains intact."""
    __tablename__ = 'user_mail_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    sender_name: Mapped[str] = mapped_column(String(160), default='')
    email: Mapped[str] = mapped_column(String(260))
    host: Mapped[str] = mapped_column(String(260))
    port: Mapped[int]
    encryption: Mapped[str] = mapped_column(String(20), default='ssl')
    username: Mapped[str] = mapped_column(String(260))
    secret_encrypted: Mapped[str] = mapped_column(Text)
    signature: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'), default='')
    last_test_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class MailDelivery(Base):
    __tablename__ = 'user_mail_deliveries'
    __table_args__ = (UniqueConstraint('owner_user_id', 'request_key', name='uq_mail_owner_request'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    site_project_id: Mapped[int | None] = mapped_column(ForeignKey('site_projects.id', ondelete='SET NULL'), nullable=True, index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey('crm_leads.id', ondelete='SET NULL'), nullable=True, index=True)
    request_key: Mapped[str] = mapped_column(String(36))
    payload_hash: Mapped[str] = mapped_column(String(64))
    message_id: Mapped[str] = mapped_column(String(260))
    sender: Mapped[str] = mapped_column(String(260))
    recipient: Mapped[str] = mapped_column(String(260))
    subject: Mapped[str] = mapped_column(String(260))
    content: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'))
    content_html: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), 'mysql'), default='')
    attachments_json: Mapped[str] = mapped_column(Text, default='[]')
    status: Mapped[str] = mapped_column(String(30), default='pending')
    message: Mapped[str] = mapped_column(String(500), default='正在发送，请勿重复提交')
    interaction_id: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
