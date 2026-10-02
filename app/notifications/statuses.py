from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel.models import MessageProviderStatus
from app.config.settings import get_settings
from app.notifications.models import StaffOutbox
from app.notifications.service import staff_audit
from app.notifications.staff_texts import template_for


async def record_staff_provider_status(
    session: AsyncSession, payload: dict[str, Any], *, request_id: UUID | str | None
) -> bool:
    from app.channel.inbound import parse_provider_timestamp

    row = await session.scalar(
        select(StaffOutbox)
        .where(
            StaffOutbox.provider_message_id == payload["id"],
        )
        .with_for_update()
    )
    if row is None:
        return False
    session.add(
        MessageProviderStatus(
            provider_message_id=payload["id"],
            message_id=None,
            status=payload["status"],
            recipient_id=payload.get("recipient_id"),
            provider_timestamp=parse_provider_timestamp(payload.get("timestamp")),
            payload=payload,
        )
    )
    # Flush inside the inbound savepoint before state/audit changes. Duplicate statuses
    # roll back only this savepoint using the existing uq_provider_status handler.
    await session.flush()
    old = row.status
    rank = {"SENT": 0, "DELIVERED": 1, "READ": 2}
    incoming = payload["status"].upper()
    if incoming in {"DELIVERED", "READ"} and rank.get(incoming, -1) > rank.get(old, -1):
        row.status = incoming
    elif incoming == "FAILED" and old not in {"DELIVERED", "READ"}:
        errors = payload.get("errors")
        first = (
            errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
        )
        code = first.get("code")
        row.last_error_code = code if type(code) is int else None
        row.last_error = str(first.get("message") or first.get("title") or "Envío fallido")[:4000]
        if code == 131047 and row.message_kind == "TEXT":
            row.status = "PENDING" if template_for(row.event_kind, get_settings()) else "DEFERRED"
            row.next_attempt_at = datetime.now(UTC)
        else:
            row.status = "FAILED"
        row.claim_token, row.claimed_at = None, None
    if row.status != old:
        row.updated_at = datetime.now(UTC)
        action = "REQUEUED" if row.status == "PENDING" else row.status
        staff_audit(
            session, f"STAFF_NOTIFICATION_{action}", row, old_status=old, request_id=request_id
        )
    return True
