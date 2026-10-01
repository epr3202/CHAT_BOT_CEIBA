import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.config.settings import get_settings
from app.conversation.models import KnowledgeEntry
from tests.booking_conversation.helpers import code, review_fixture
from tests.integration.helpers import login_headers
from tests.visit_booking_guard.helpers import Harness


@pytest.mark.parametrize("reason", ["draft", "disabled"])
async def test_g3_c2_skipped_notice_keeps_exactly_two_evidence_audits(
    harness: Harness, api: AsyncClient, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    evidence = await review_fixture(harness)
    if reason == "disabled":
        monkeypatch.setenv("SELF_SERVICE_BOOKING_ENABLED", "false")
        get_settings.cache_clear()
    else:
        async with harness.db.begin() as session:
            entry = await session.scalar(
                select(KnowledgeEntry)
                .where(KnowledgeEntry.code == code("CONFIRMED"))
                .order_by(KnowledgeEntry.version.desc())
                .limit(1)
            )
            entry.status = "DRAFT"
    response = await api.post(
        f"/admin/payment-evidence/{evidence.id}/accept",
        json={"amount_cop": 125000},
        headers=await login_headers(api, "90000000"),
    )
    assert response.status_code == 200
    assert response.json()["result"] == "RESERVED"
    assert response.json()["customer_notification"] == "DEFERRED"
    audits = await harness.rows(AuditEvent)
    evidence_audits = [audit for audit in audits if audit.entity == "payment_evidence"]
    assert [audit.action for audit in evidence_audits] == [
        "PAYMENT_EVIDENCE_ACCEPTED",
        "PAYMENT_EVIDENCE_REVIEWED",
    ]
    notices = [audit for audit in audits if audit.action == "NOTIFICATION_SKIPPED"]
    assert len(notices) == 1
    assert notices[0].entity == "conversation"
    assert notices[0].new_value["evidence_id"] == evidence.id
    assert notices[0].new_value["conversation_id"] == evidence.conversation_id
    assert notices[0].reason
    assert not await harness.bodies()
