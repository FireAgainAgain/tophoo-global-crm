"""Project quotations retain customer and seller snapshots for repeatable exports."""
from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class Quotation(Base):
    __tablename__='crm_quotations'
    __table_args__=(UniqueConstraint('site_project_id','number',name='uq_quotation_project_number'),)
    id: Mapped[int]=mapped_column(primary_key=True)
    site_project_id: Mapped[int]=mapped_column(ForeignKey('site_projects.id'),index=True)
    owner_user_id: Mapped[int]=mapped_column(ForeignKey('users.id'),index=True)
    customer_id: Mapped[int | None]=mapped_column(Integer,nullable=True)
    rfq_id: Mapped[int | None]=mapped_column(Integer,nullable=True)
    number: Mapped[str]=mapped_column(String(80))
    quote_date: Mapped[date]=mapped_column(Date,index=True)
    status: Mapped[str]=mapped_column(String(20),default='草稿',index=True)
    buyer_company: Mapped[str]=mapped_column(String(260))
    currency: Mapped[str]=mapped_column(String(3),default='USD')
    data_json: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'))
    revision: Mapped[int]=mapped_column(Integer,default=1)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now,onupdate=datetime.now)


class QuotationTemplate(Base):
    __tablename__='crm_quotation_templates'
    __table_args__=(UniqueConstraint('site_project_id','name',name='uq_quote_template_name'),
                   UniqueConstraint('site_project_id','default_slot',name='uq_quote_template_default'),
                   {'mysql_engine':'InnoDB'})
    id: Mapped[int]=mapped_column(primary_key=True)
    # Legacy project tables may use MyISAM; project scope is checked by the API.
    site_project_id: Mapped[int]=mapped_column(Integer,index=True)
    name: Mapped[str]=mapped_column(String(120))
    is_active: Mapped[bool]=mapped_column(Boolean,default=True)
    default_slot: Mapped[int | None]=mapped_column(Integer,nullable=True)
    revision: Mapped[int]=mapped_column(Integer,default=1)
    data_json: Mapped[str]=mapped_column(Text().with_variant(LONGTEXT(),'mysql'))
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.now,onupdate=datetime.now)
