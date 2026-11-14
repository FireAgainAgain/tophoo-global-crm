"""Customer sales contracts and archived signed copies."""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGBLOB, LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SalesContract(Base):
    __tablename__ = "crm_sales_contracts"
    __table_args__ = (UniqueConstraint("site_project_id", "number", name="uq_sales_contract_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_quote_id: Mapped[int | None] = mapped_column(Integer)
    source_quote_number: Mapped[str | None] = mapped_column(String(80))
    number: Mapped[str] = mapped_column(String(80))
    contract_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="草稿")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    document_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class SignedContractFile(Base):
    __tablename__ = "crm_signed_contract_files"

    contract_id: Mapped[int] = mapped_column(ForeignKey("crm_sales_contracts.id"), primary_key=True)
    filename: Mapped[str] = mapped_column(String(260))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), "mysql"))
