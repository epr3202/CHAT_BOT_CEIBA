"""Presentation fixtures for the disposable frontend database."""

import os
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.models import CatalogAsset, CatalogEventTypeMap
from app.channel.models import Message, Outbox
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from app.payment.models import PaymentEvidence
from tests.integration.helpers import assert_safe_test_database_url, bootstrap_agent


async def seed_spanish_labels() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    assert_safe_test_database_url(database_url)
    agent = await bootstrap_agent(
        name="Asesora de prueba", document_id="90000001", role="AGENT", active=False
    )
    engine = create_async_engine(database_url)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    timestamp = datetime(2026, 9, 24, 16, 10, tzinfo=UTC)
    try:
        async with sessionmaker.begin() as session:
            for index, state in enumerate(("HUMAN_ACTIVE", "WAITING_FOR_HUMAN")):
                customer = Customer(
                    phone_number=f"57300000010{index}",
                    full_name=("Ana Lucía", "María del Carmen")[index],
                )
                session.add(customer)
                await session.flush()
                conversation = Conversation(
                    customer_id=customer.id,
                    channel="WHATSAPP",
                    state=state,
                    bot_enabled=False,
                    last_intent="PAYMENT_MESSAGE",
                    last_message_at=timestamp,
                    assigned_agent_id=agent.id if index == 0 else None,
                )
                session.add(conversation)
                await session.flush()
                message = Message(
                    external_message_id=f"wamid.frontend.spanish.{index}",
                    conversation_id=conversation.id,
                    customer_id=customer.id,
                    channel="WHATSAPP",
                    direction="INBOUND",
                    message_type="text",
                    content={"text": {"body": "Adjunto el comprobante."}},
                    created_at=timestamp,
                )
                session.add(message)
                await session.flush()
                if index == 1:
                    session.add(
                        Handoff(
                            conversation_id=conversation.id,
                            status="PENDING",
                            reason="PAYMENT_REVIEW",
                            priority="URGENT",
                            created_at=timestamp,
                            summary=(
                                f"Cliente: {customer.full_name}\nMotivo: PAYMENT_REVIEW\n"
                                "Ultimos mensajes:\n- INBOUND: Adjunto el comprobante.\n"
                                "- OUTBOUND: Un asesor revisará tu pago."
                            ),
                        )
                    )
                    session.add(
                        Outbox(
                            conversation_id=conversation.id,
                            message_id=message.id,
                            channel="WHATSAPP",
                            recipient_phone_number=customer.phone_number,
                            payload={"type": "text", "text": {"body": "Revisión en curso."}},
                            status="SUPPRESSED",
                            created_at=timestamp,
                        )
                    )
                    session.add(
                        PaymentEvidence(
                            conversation_id=conversation.id,
                            customer_id=customer.id,
                            message_id=message.id,
                            media_id="frontend-spanish-evidence",
                            mime_type="application/pdf",
                            declared_sha256="0" * 64,
                            review_status="PENDING_REVIEW",
                            download_status="FAILED_RETRYABLE",
                            created_at=timestamp,
                        )
                    )
            catalog = CatalogAsset(
                name="Planes románticos — etiquetas",
                file_path="spanish-labels.pdf",
                file_hash="1" * 64,
                file_size=32,
                active=True,
            )
            session.add(catalog)
            await session.flush()
            session.add(
                CatalogEventTypeMap(
                    catalog_asset_id=catalog.catalog_asset_id,
                    event_type="ROMANTIC_DINNER",
                    send_mode="ON_REQUEST",
                )
            )
    finally:
        await engine.dispose()
