from __future__ import annotations

import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset
from app.config.settings import Settings


class MediaUploadSender(Protocol):
    async def upload_media(self, file_path: Path, mime_type: str) -> str:
        pass


class PermanentCatalogMediaError(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogDocument:
    asset_id: UUID
    media_id: str
    filename: str


class MediaService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        settings: Settings,
        sender: MediaUploadSender,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._sender = sender

    async def resolve_document(self, asset_id: UUID) -> CatalogDocument:
        snapshot = await self._asset_snapshot(asset_id)
        if snapshot is None:
            raise PermanentCatalogMediaError(f"Catalog asset {asset_id} does not exist")
        if self._cached_media_is_valid(snapshot):
            return CatalogDocument(
                asset_id=asset_id,
                media_id=snapshot.media_id or "",
                filename=normalized_pdf_filename(snapshot.name),
            )

        file_path = self._resolve_file_path(snapshot.file_path)
        validate_catalog_file(file_path, snapshot.file_hash)
        media_id = await self._sender.upload_media(file_path, snapshot.mime_type)
        uploaded_at = datetime.now(UTC)
        async with self._sessionmaker() as session:
            async with session.begin():
                asset = await session.get(CatalogAsset, asset_id, with_for_update=True)
                if asset is None:
                    raise PermanentCatalogMediaError(f"Catalog asset {asset_id} disappeared")
                asset.media_id = media_id
                asset.media_uploaded_at = uploaded_at
                session.add(
                    AuditEvent(
                        actor="INTEGRATION",
                        action="CATALOG_MEDIA_UPLOADED",
                        entity="catalog_asset",
                        old_value={"media_id": snapshot.media_id},
                        new_value={"catalog_asset_id": str(asset_id), "media_id": media_id},
                        reason="Catalog media cache refreshed",
                        request_id=None,
                    )
                )
        return CatalogDocument(
            asset_id=asset_id,
            media_id=media_id,
            filename=normalized_pdf_filename(snapshot.name),
        )

    async def invalidate_media_cache(self, asset_id: UUID, reason: str) -> None:
        async with self._sessionmaker() as session:
            async with session.begin():
                asset = await session.get(CatalogAsset, asset_id, with_for_update=True)
                if asset is None:
                    return
                old_media_id = asset.media_id
                asset.media_id = None
                asset.media_uploaded_at = None
                session.add(
                    AuditEvent(
                        actor="INTEGRATION",
                        action="CATALOG_MEDIA_CACHE_INVALIDATED",
                        entity="catalog_asset",
                        old_value={"media_id": old_media_id},
                        new_value={"catalog_asset_id": str(asset_id), "media_id": None},
                        reason=reason,
                        request_id=None,
                    )
                )

    async def _asset_snapshot(self, asset_id: UUID) -> CatalogAsset | None:
        async with self._sessionmaker() as session:
            return await session.get(CatalogAsset, asset_id)

    def _cached_media_is_valid(self, asset: CatalogAsset) -> bool:
        if not asset.media_id or asset.media_uploaded_at is None:
            return False
        expires_before = datetime.now(UTC) - timedelta(days=self._settings.catalog_media_ttl_days)
        uploaded_at = asset.media_uploaded_at
        if uploaded_at.tzinfo is None:
            uploaded_at = uploaded_at.replace(tzinfo=UTC)
        return uploaded_at > expires_before

    def _resolve_file_path(self, file_path: str) -> Path:
        path = Path(file_path)
        if path.is_absolute():
            return path
        return Path(self._settings.catalog_storage_dir) / path


def validate_catalog_file(file_path: Path, expected_sha256: str) -> None:
    if not file_path.exists() or not file_path.is_file():
        raise PermanentCatalogMediaError(f"Catalog file is missing: {file_path}")
    if sha256_file(file_path) != expected_sha256:
        raise PermanentCatalogMediaError("Catalog file hash does not match registered asset")


def sha256_file(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_pdf_filename(name: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", name.strip().casefold()).strip("-")
    if not stem:
        stem = "catalogo"
    if stem.endswith("-pdf"):
        stem = stem.removesuffix("-pdf")
    return f"{stem}.pdf"


def detect_pdf_mime_type(file_path: Path) -> str:
    guessed, _encoding = mimetypes.guess_type(file_path.name)
    return guessed or "application/octet-stream"
