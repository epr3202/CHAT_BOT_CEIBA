from unittest.mock import AsyncMock

from app.config.settings import get_settings
from app.main import app
from app.notifications.service import intercept_staff_inbound
from app.notifications.worker import process_staff_outbox_once
from tests.staff_notifications.helpers import NOW, PHONE, outbox, recipient, rows


async def test_f2_reopen_clears_window_error_and_uses_text(client, monkeypatch):
    monkeypatch.setenv("STAFF_TEMPLATE_EVIDENCE_NAME", "")
    get_settings.cache_clear()
    target = await recipient()
    queued = await outbox(
        target, status="DEFERRED", last_error_code=131047, last_error="Ventana cerrada"
    )
    async with app.state.db_sessionmaker.begin() as session:
        result = await intercept_staff_inbound(
            session,
            phone_number=PHONE,
            provider_timestamp=NOW,
            external_message_id="f2.reopen",
            settings=get_settings(),
            request_id="f2",
        )
        assert result
    saved = (await rows(type(queued)))[0]
    assert saved.status == "PENDING"
    assert saved.last_error_code is None and saved.last_error is None
    sender = AsyncMock()
    sender.send_text.return_value = "f2.sent"
    await process_staff_outbox_once(app.state.db_sessionmaker, sender, get_settings(), now=NOW)
    sender.send_text.assert_awaited_once()
    sender.send_template.assert_not_called()
    assert (await rows(type(queued)))[0].status == "SENT"
