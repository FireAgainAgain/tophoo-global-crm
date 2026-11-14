"""Workspace customer masters and their project relationships."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base


class Company(Base):
    __tablename__ = "crm_companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(260))
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    last_contact_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Customer(Base):
    """Customer/contact master. Company facts live on the customer record."""
    __tablename__ = "crm_customers"
    is_manually_researched: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)

    company_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    company_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_facebook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_instagram: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    people_initialized: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    company: Mapped[str] = mapped_column(String(260), default="")
    company_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Kept only for a safe one-time migration from the retired company module.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("crm_companies.id"), nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(260), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    job_title: Mapped[str | None] = mapped_column(String(160), nullable=True)
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    customer_type: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    other_channels: Mapped[str | None] = mapped_column(Text, nullable=True)
    inquiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    product_category: Mapped[str | None] = mapped_column(String(160), nullable=True)
    product_match: Mapped[str | None] = mapped_column(String(20), nullable=True)
    legacy_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    classification_version: Mapped[int] = mapped_column(Integer, default=2, server_default='2')
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    last_contact_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    next_follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CustomerPerson(Base):
    """People belonging to a shared customer master; one primary per customer."""

    __tablename__ = "crm_customer_people"
    __table_args__ = (UniqueConstraint("customer_id", "primary_slot", name="uq_customer_primary_person"),)

    linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    facebook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instagram: Mapped[str | None] = mapped_column(String(500), nullable=True)
    youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("crm_customers.id", ondelete="CASCADE"), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(260), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL permits multiple secondary contacts, while 1 is unique per customer.
    primary_slot: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProjectCompany(Base):
    """A company's commercial relationship with one CRM project."""

    __tablename__ = "crm_project_companies"
    __table_args__ = (UniqueConstraint("site_project_id", "company_id", name="uq_project_company"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("crm_companies.id"), index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProjectContact(Base):
    """A contact's commercial relationship with one CRM project."""

    __tablename__ = "crm_project_contacts"
    __table_args__ = (UniqueConstraint("site_project_id", "contact_id", name="uq_project_contact"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_customers.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    workflow_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    released_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    inquiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class CustomerPoolAudit(Base):
    """Immutable history for releases to and restorations from the public pool."""

    __tablename__ = "crm_customer_pool_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("crm_customers.id"), index=True)
    original_owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    released_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    release_reason: Mapped[str] = mapped_column(Text)
    released_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    restored_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    restored_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    restored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)


class ProspectingEntry(Base):
    """Self-sourced companies awaiting qualification into a lead."""

    __tablename__ = "crm_prospecting_entries"

    company_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    company_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_facebook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_instagram: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str] = mapped_column(String(260))
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    company_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_source: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="自主开发")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(260), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    other_channels: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProspectingJob(Base):
    """One automatic-acquisition import and its filtering outcome."""

    __tablename__ = "crm_prospecting_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str] = mapped_column(String(80), default="名单导入")
    keyword: Mapped[str | None] = mapped_column(String(260), nullable=True)
    target_countries: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_types: Mapped[str | None] = mapped_column(String(500), nullable=True)
    min_score: Mapped[int] = mapped_column(default=40)
    criteria_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="done", index=True)
    found_count: Mapped[int] = mapped_column(default=0)
    shortlisted_count: Mapped[int] = mapped_column(default=0)
    filtered_count: Mapped[int] = mapped_column(default=0)
    duplicate_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ProspectingCandidate(Base):
    """Source record retained for audit, whether or not it entered the list."""

    __tablename__ = "crm_prospecting_candidates"
    __table_args__ = (UniqueConstraint("job_id", "fingerprint", name="uq_prospecting_job_fingerprint"),)

    company_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_facebook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_instagram: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("crm_prospecting_jobs.id"), index=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True, index=True)
    prospecting_entry_id: Mapped[int | None] = mapped_column(ForeignKey("crm_prospecting_entries.id"), nullable=True, index=True)
    contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_name: Mapped[str] = mapped_column(String(260))
    country: Mapped[str | None] = mapped_column(String(120), nullable=True)
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(260), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    score: Mapped[int] = mapped_column(default=0, index=True)
    grade: Mapped[str] = mapped_column(String(4), default="C", index=True)
    status: Mapped[str] = mapped_column(String(40), default="filtered", index=True)
    filter_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class Lead(Base):
    """Qualified prospect ready to be converted to a project customer."""

    __tablename__ = "crm_leads"

    @validates('country')
    def normalize_country(self, key, value):
        from app.services.country_names import chinese_country
        return chinese_country(value)

    is_manually_researched: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    is_contacted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0", nullable=False)
    workflow_status: Mapped[str] = mapped_column(String(30), default="unviewed", server_default="unviewed", nullable=False)
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    development_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status_schema_version: Mapped[int] = mapped_column(Integer, default=2, server_default="2", nullable=False)

    company_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    company_linkedin: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_facebook: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_instagram: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_youtube: Mapped[str | None] = mapped_column(String(500), nullable=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    contacts_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_name: Mapped[str] = mapped_column(String(260))
    country: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    company_website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    company_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    customer_source: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(40), default="自主开发")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    email: Mapped[str | None] = mapped_column(String(260), nullable=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(80), nullable=True)
    other_channels: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
