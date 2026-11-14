"""Project-owned external acquisition connections."""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class LegacyAcquisitionConnection(Base):
    __tablename__ = 'crm_acquisition_connections'
    __table_args__ = (UniqueConstraint('site_project_id', 'provider', name='uq_acquisition_connection'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class LegacyAcquisitionConnectionTest(Base):
    """Test outcomes bound to a key fingerprint, without storing draft credentials."""
    __tablename__ = 'crm_acquisition_connection_tests'
    __table_args__ = (UniqueConstraint('site_project_id', 'provider', 'key_fingerprint', name='uq_acquisition_connection_test'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    key_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    tested_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(DateTime)


# Personal connections never inherit the retired project-shared credentials.
class AcquisitionConnection(Base):
    __tablename__ = 'crm_user_acquisition_connections'
    __table_args__ = (UniqueConstraint('site_project_id', 'owner_user_id', 'provider', name='uq_user_acquisition_connection'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class AcquisitionConnectionTest(Base):
    """Test outcomes bound to a key fingerprint, without storing draft credentials."""
    __tablename__ = 'crm_user_acquisition_connection_tests'
    __table_args__ = (UniqueConstraint('site_project_id', 'owner_user_id', 'provider', 'key_fingerprint', name='uq_user_acquisition_connection_test'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey('site_projects.id'), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    key_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(String(500))
    tested_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime] = mapped_column(DateTime)
