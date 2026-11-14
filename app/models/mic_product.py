"""Project-scoped MIC catalogue and private product images."""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, LargeBinary, Boolean, text
from sqlalchemy.dialects.mysql import LONGBLOB, MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base


class MicProduct(Base):
    __tablename__ = "mic_products"
    __table_args__ = (UniqueConstraint("site_project_id", "product_code", name="uq_mic_project_code"),
                      {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"})
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    product_code: Mapped[str] = mapped_column(String(80))
    record_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    published_through: Mapped[str | None] = mapped_column(String(80), nullable=True)
    product_name: Mapped[str] = mapped_column(String(500), default="", server_default=text("''"))
    english_title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True)
    parameters: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_group: Mapped[str] = mapped_column(String(500), default="")
    classification: Mapped[str | None] = mapped_column(String(500), nullable=True)
    social_json: Mapped[str | None] = mapped_column(Text().with_variant(MEDIUMTEXT(), "mysql"), nullable=True)
    titles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    title: Mapped[str] = mapped_column(String(1000))
    original_title: Mapped[str] = mapped_column(String(1000), default="")
    suggested_title: Mapped[str] = mapped_column(String(1000), default="")
    center_keyword: Mapped[str] = mapped_column(String(191), default="")
    keywords: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    source_script_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class MicProductImage(Base):
    __tablename__ = "mic_product_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    site_project_id: Mapped[int] = mapped_column(ForeignKey("site_projects.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("mic_products.id"), index=True)
    filename: Mapped[str] = mapped_column(String(260))
    content: Mapped[bytes] = mapped_column(LargeBinary().with_variant(LONGBLOB(), "mysql"))
    thumbnail: Mapped[bytes] = mapped_column(LargeBinary)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    is_cover: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
