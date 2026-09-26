"""BASE-compatible real producers and authenticated takeover; no future schema."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from app.catalog.models import CatalogAsset, CatalogEventTypeMap
from app.catalog.service import handle_explicit_catalog_request
from app.channel.models import Message, Outbox
from app.config.settings import get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.orchestrator.service import enqueue_template
from data.knowledge_seed import iter_seed_entries
from scripts.load_knowledge import load_knowledge_entries
from tests.remediation.r8.helpers import seed_case


async def enqueue(
    db: Any, kind: str = "TEXT", conversation_id: int | None = None,
) -> tuple[int, int]:
    await load_knowledge_entries(db, list(iter_seed_entries()))
    if conversation_id is None:
        conversation_id, _ = await seed_case(db, pending=False)
    async with db() as session, session.begin():
        conversation = await session.get(Conversation, conversation_id, with_for_update=True)
        customer = await session.get(Customer, conversation.customer_id)
        inbound = await session.scalar(select(Message).where(
            Message.conversation_id == conversation_id, Message.direction == "INBOUND",
        ).order_by(Message.id.desc()))
        if kind == "DOCUMENT":
            pdf = b"%PDF-1.4\n% Synthetic R9 catalog\n%%EOF\n"
            storage = Path(get_settings().catalog_storage_dir)
            storage.mkdir(parents=True, exist_ok=True)
            filename = "r9-" + uuid4().hex + ".pdf"
            (storage / filename).write_bytes(pdf)
            asset = CatalogAsset(name="R9 synthetic", file_path=filename,
                                 file_hash=hashlib.sha256(pdf).hexdigest(), file_size=len(pdf),
                                 media_id="r9-cached-media", media_uploaded_at=datetime.now(UTC))
            session.add(asset)
            await session.flush()
            session.add(CatalogEventTypeMap(catalog_asset_id=asset.catalog_asset_id,
                                           event_type="BIRTHDAY", send_mode="ON_REQUEST"))
            await session.flush()
            result = await handle_explicit_catalog_request(
                session, db, conversation, customer, inbound, None, "BIRTHDAY", None, "r9",
            )
            assert result.sent_count >= 1, "Real catalog producer precondition"
        else:
            await enqueue_template(session, db, conversation, customer, inbound,
                                   "RESP-CATALOG-002", {})
        await session.flush()
        row = await session.scalar(select(Outbox).where(
            Outbox.conversation_id == conversation_id,
        ).order_by(Outbox.id.desc()))
        assert row is not None and row.status == "PENDING"
        assert row.message_kind == kind and row.payload.get("agent") is not True
        return conversation_id, row.id


async def take(api: Any, conversation_id: int, actor: str = "A") -> int:
    client, actors = api
    response = await client.post(f"/admin/conversations/{conversation_id}/take",
                                 headers=actors[actor]["headers"])
    assert response.status_code == 200, "Real authenticated takeover precondition"
    assert response.json()["assigned_agent"]["id"] == actors[actor]["id"]
    return response.json()["id"]


class Sender:
    def __init__(self) -> None:
        self.sends: list[dict[str, str]] = []
        self.uploads: list[str] = []

    async def send_text(self, to: str, body: str) -> str:
        self.sends.append(dict(kind="TEXT", to=to, body=body))
        return "r9.sent." + uuid4().hex

    async def send_document(self, to: str, media_id: str, filename: str, caption: str) -> str:
        assert media_id.startswith("r9-") and filename.endswith(".pdf")
        self.sends.append(dict(kind="DOCUMENT", to=to, media_id=media_id, caption=caption))
        return "r9.sent." + uuid4().hex

    async def upload_media(self, file_path: Path, mime_type: str) -> str:
        assert mime_type == "application/pdf" and file_path.read_bytes().startswith(b"%PDF")
        self.uploads.append(file_path.name)
        return "r9-uploaded-media"
