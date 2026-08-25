from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import AuditEvent
from app.catalog.models import CatalogAsset
from app.config.settings import Settings


class MediaUploadSender(Protocol):
    async def upload_media(self, file_path: Path, mime_type: str) -> str:
        pass


class PermanentCatalogMediaError(RuntimeError):
    pass


class InboundMediaDownloadError(RuntimeError):
    pass


class InboundMediaHashMismatch(InboundMediaDownloadError):
    pass


class InboundMediaTooLarge(InboundMediaDownloadError):
    pass


@dataclass(frozen=True)
class CatalogDocument:
    asset_id: UUID
    media_id: str
    filename: str


@dataclass(frozen=True)
class InboundMediaFile:
    bytes: bytes
    mime_type: str
    sha256: str
    size_bytes: int


async def download_inbound_media(
    media_id: str,
    *,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> InboundMediaFile:
    """Download one inbound object from a freshly resolved Meta media URL."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=15.0)
    headers = {"Authorization": f"Bearer {settings.meta_access_token}"}
    try:
        metadata_response = await client.get(
            inbound_media_metadata_url(settings, media_id),
            headers=headers,
        )
        _raise_for_inbound_media_status(metadata_response)
        metadata = metadata_response.json()
        if not isinstance(metadata, dict):
            raise InboundMediaDownloadError("Inbound media metadata must be an object")

        fresh_url = metadata.get("url")
        if not isinstance(fresh_url, str) or not fresh_url:
            raise InboundMediaDownloadError("Inbound media metadata did not include a URL")
        declared_hash = metadata.get("sha256")
        if not isinstance(declared_hash, str) or not declared_hash:
            raise InboundMediaDownloadError("Inbound media metadata did not include sha256")

        max_bytes = settings.inbound_media_max_mb * 1024 * 1024
        declared_size = metadata.get("file_size")
        if isinstance(declared_size, int) and declared_size > max_bytes:
            raise InboundMediaTooLarge("Inbound media exceeds the configured size limit")

        chunks: list[bytes] = []
        size_bytes = 0
        mime_type = str(metadata.get("mime_type") or "application/octet-stream")
        async with client.stream("GET", fresh_url, headers=headers) as media_response:
            _raise_for_inbound_media_status(media_response)
            mime_type = metadata.get("mime_type") or media_response.headers.get(
                "Content-Type", mime_type
            )
            async for chunk in media_response.aiter_bytes():
                size_bytes += len(chunk)
                if size_bytes > max_bytes:
                    raise InboundMediaTooLarge(
                        "Inbound media exceeds the configured size limit"
                    )
                chunks.append(chunk)

        content = b"".join(chunks)
        calculated_hash = base64.b64encode(hashlib.sha256(content).digest()).decode()
        if not _hashes_match(declared_hash, calculated_hash, content):
            raise InboundMediaHashMismatch("Inbound media sha256 verification failed")
        return InboundMediaFile(
            bytes=content,
            mime_type=str(mime_type),
            sha256=declared_hash,
            size_bytes=size_bytes,
        )
    except (httpx.HTTPError, ValueError) as error:
        if isinstance(error, InboundMediaDownloadError):
            raise
        raise InboundMediaDownloadError("Inbound media download failed") from error
    finally:
        if owns_client:
            await client.aclose()


def inbound_media_metadata_url(settings: Settings, media_id: str) -> str:
    return (
        f"{settings.whatsapp_api_base_url.rstrip('/')}/"
        f"{settings.meta_graph_api_version}/{media_id}"
    )


def _raise_for_inbound_media_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        raise InboundMediaDownloadError("Meta rejected an inbound media request") from error


def _hashes_match(declared_hash: str, calculated_base64: str, content: bytes) -> bool:
    calculated_hex = hashlib.sha256(content).hexdigest()
    return declared_hash in {calculated_base64, calculated_hex}


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
