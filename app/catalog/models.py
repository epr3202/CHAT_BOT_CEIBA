from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.config.database import Base
from app.event.models import EVENT_TYPES

if TYPE_CHECKING:
    from app.channel.models import Outbox

CATALOG_SEND_TRIGGERS = ("PROACTIVE", "EXPLICIT_REQUEST")


class CatalogAsset(Base):
    __tablename__ = "catalog_asset"
    __table_args__ = (
        CheckConstraint("mime_type = 'application/pdf'", name="ck_catalog_asset_mime_type_pdf"),
        CheckConstraint("file_size > 0", name="ck_catalog_asset_file_size_positive"),
        CheckConstraint("version >= 1", name="ck_catalog_asset_version_positive"),
    )

    catalog_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False, default="application/pdf")
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    event_type_maps: Mapped[list[CatalogEventTypeMap]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
    sends: Mapped[list[CatalogSend]] = relationship(back_populates="asset")

    @validates("mime_type")
    def validate_mime_type(self, key: str, value: str) -> str:
        if value != "application/pdf":
            raise ValueError(f"Invalid catalog mime_type: {value}")
        return value


class CatalogEventTypeMap(Base):
    __tablename__ = "catalog_event_type_map"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'WEDDING', 'CIVIL_WEDDING', 'PROPOSAL', 'BIRTHDAY', 'GRADUATION', "
            "'ANNIVERSARY', 'ROMANTIC_DINNER', 'CORPORATE_EVENT', 'FAMILY_EVENT', "
            "'BAPTISM', 'FIRST_COMMUNION', 'BABY_SHOWER', 'WORKSHOP', 'POOL_DAY', "
            "'PRIVATE_DINNER', 'OTHER')",
            name="ck_catalog_event_type_map_event_type",
        ),
        UniqueConstraint("catalog_asset_id", "event_type", name="uq_catalog_asset_event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_asset.catalog_asset_id"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped[CatalogAsset] = relationship(back_populates="event_type_maps")

    @validates("event_type")
    def validate_event_type(self, key: str, value: str) -> str:
        if value not in EVENT_TYPES:
            raise ValueError(f"Invalid event_type: {value}")
        return value


class CatalogSend(Base):
    __tablename__ = "catalog_send"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('PROACTIVE', 'EXPLICIT_REQUEST')", name="ck_catalog_send_trigger"
        ),
        Index(
            "uq_catalog_send_proactive_lead_asset",
            "lead_id",
            "catalog_asset_id",
            unique=True,
            postgresql_where=text("trigger = 'PROACTIVE'"),
        ),
    )

    catalog_send_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lead.lead_id"), nullable=False, index=True
    )
    catalog_asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("catalog_asset.catalog_asset_id"), nullable=False, index=True
    )
    trigger: Mapped[str] = mapped_column(String(32), nullable=False)
    outbound_message_id: Mapped[int] = mapped_column(ForeignKey("outbox.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped[CatalogAsset] = relationship(back_populates="sends")
    outbound_message: Mapped[Outbox] = relationship()

    @validates("trigger")
    def validate_trigger(self, key: str, value: str) -> str:
        if value not in CATALOG_SEND_TRIGGERS:
            raise ValueError(f"Invalid catalog send trigger: {value}")
        return value
