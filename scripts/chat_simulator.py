from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.models_registry  # noqa: F401
from app.channel.models import Message
from app.config.database import create_engine, create_sessionmaker
from app.config.settings import Settings, get_settings
from app.conversation.models import Conversation
from app.customer.models import Customer
from app.handoff.models import Handoff
from scripts import simulate_webhook as webhook_helper

REQUIRED_SETTING_ALIASES = {
    "DATABASE_URL": "database_url",
    "META_APP_SECRET": "meta_app_secret",
}


@dataclass
class LastPayload:
    body: bytes
    headers: dict[str, str]


def prepare_signed_webhook_request(
    phone: str,
    text: str,
    message_id: str,
    app_secret: str,
) -> tuple[bytes, dict[str, str]]:
    payload = webhook_helper.build_payload(phone, text, message_id)
    body = json.dumps(payload, separators=(",", ":")).encode()
    return body, {
        "Content-Type": "application/json",
        "X-Hub-Signature-256": webhook_helper.sign_body(body, app_secret),
    }


def load_chat_simulator_settings() -> Settings:
    try:
        settings = get_settings()
    except ValidationError as error:
        missing = sorted(
            str(issue["loc"][0])
            for issue in error.errors()
            if issue.get("type") == "missing" and issue.get("loc")
        )
        detail = ", ".join(missing) if missing else str(error)
        raise SystemExit(f"Missing required settings for chat_simulator: {detail}") from error

    blank = sorted(
        alias
        for alias, attribute in REQUIRED_SETTING_ALIASES.items()
        if not str(getattr(settings, attribute)).strip()
    )
    if blank:
        raise SystemExit(f"Missing required settings for chat_simulator: {', '.join(blank)}")

    return settings


async def post_webhook(
    client: httpx.AsyncClient,
    webhook_url: str,
    body: bytes,
    headers: dict[str, str],
) -> None:
    response = await client.post(webhook_url, content=body, headers=headers)
    print(f"WEBHOOK: {response.status_code}")
    response.raise_for_status()


async def latest_conversation_for_phone(
    session: AsyncSession,
    phone: str,
) -> Conversation | None:
    return await session.scalar(
        select(Conversation)
        .join(Customer, Customer.id == Conversation.customer_id)
        .where(Customer.phone_number == phone)
        .order_by(desc(Conversation.id))
        .limit(1)
    )


async def latest_outbound_message_id(
    sessionmaker: async_sessionmaker[AsyncSession],
    phone: str,
) -> int:
    async with sessionmaker() as session:
        conversation = await latest_conversation_for_phone(session, phone)
        if conversation is None:
            return 0
        return (
            await session.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.direction == "OUTBOUND",
                )
                .order_by(desc(Message.id))
                .limit(1)
            )
            or 0
        )


async def poll_bot_responses(
    sessionmaker: async_sessionmaker[AsyncSession],
    phone: str,
    after_message_id: int,
    timeout_seconds: float,
) -> int:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_seen_id = after_message_id
    printed_any = False

    while asyncio.get_running_loop().time() < deadline:
        async with sessionmaker() as session:
            conversation = await latest_conversation_for_phone(session, phone)
            if conversation is not None:
                result = await session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation.id,
                        Message.direction == "OUTBOUND",
                        Message.id > last_seen_id,
                    )
                    .order_by(Message.id)
                )
                for message in result.all():
                    body = extract_text_body(message.content)
                    print(f"BOT: {body}")
                    last_seen_id = message.id
                    printed_any = True

        if printed_any:
            return last_seen_id
        await asyncio.sleep(0.5)

    print("BOT: (sin respuesta dentro del timeout)")
    return last_seen_id


def extract_text_body(content: dict[str, Any]) -> str:
    text = content.get("text")
    if isinstance(text, dict) and isinstance(text.get("body"), str):
        return text["body"]
    return json.dumps(content, ensure_ascii=False)


async def print_state(sessionmaker: async_sessionmaker[AsyncSession], phone: str) -> None:
    async with sessionmaker() as session:
        conversation = await latest_conversation_for_phone(session, phone)
        if conversation is None:
            print("STATE: no existe conversación para este teléfono")
            return
        print(
            "STATE: "
            f"state={conversation.state} "
            f"pending_action={conversation.pending_action} "
            f"pending_confirmation={conversation.pending_confirmation} "
            f"failed_understanding_count={conversation.failed_understanding_count} "
            f"bot_enabled={conversation.bot_enabled}"
        )


async def print_handoffs(sessionmaker: async_sessionmaker[AsyncSession], phone: str) -> None:
    async with sessionmaker() as session:
        conversation = await latest_conversation_for_phone(session, phone)
        if conversation is None:
            print("HANDOFFS: no existe conversación para este teléfono")
            return
        handoffs = (
            await session.scalars(
                select(Handoff)
                .where(Handoff.conversation_id == conversation.id)
                .order_by(Handoff.id)
            )
        ).all()

    if not handoffs:
        print("HANDOFFS: ninguno")
        return

    for handoff in handoffs:
        print(
            f"HANDOFF {handoff.id}: status={handoff.status} "
            f"reason={handoff.reason} priority={handoff.priority} summary={handoff.summary}"
        )


def random_phone() -> str:
    return f"+57300{random.randint(1000000, 9999999)}"


async def run_repl(args: argparse.Namespace) -> None:
    settings = load_chat_simulator_settings()
    engine = create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    sessionmaker = create_sessionmaker(engine)
    phone = args.phone
    last_payload: LastPayload | None = None
    last_seen_outbound_id = 0

    print(f"CHAT SIM listo. Teléfono actual: {phone}")
    print("Comandos: /state, /handoffs, /dup, /new, /quit")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            while True:
                line = (await asyncio.to_thread(input, "YOU: ")).strip()
                if not line:
                    continue
                if line == "/quit":
                    return
                if line == "/state":
                    await print_state(sessionmaker, phone)
                    continue
                if line == "/handoffs":
                    await print_handoffs(sessionmaker, phone)
                    continue
                if line == "/new":
                    phone = random_phone()
                    last_payload = None
                    last_seen_outbound_id = 0
                    print(f"Nuevo teléfono: {phone}")
                    continue
                if line == "/dup":
                    if last_payload is None:
                        print("DUP: no hay payload previo")
                        continue
                    await post_webhook(
                        client,
                        args.webhook_url,
                        last_payload.body,
                        last_payload.headers,
                    )
                    last_seen_outbound_id = await poll_bot_responses(
                        sessionmaker,
                        phone,
                        last_seen_outbound_id,
                        args.timeout,
                    )
                    continue

                last_seen_outbound_id = await latest_outbound_message_id(sessionmaker, phone)
                message_id = f"wamid.local.{uuid.uuid4()}"
                body, headers = prepare_signed_webhook_request(
                    phone,
                    line,
                    message_id,
                    settings.meta_app_secret,
                )
                last_payload = LastPayload(body=body, headers=headers)
                await post_webhook(client, args.webhook_url, body, headers)
                last_seen_outbound_id = await poll_bot_responses(
                    sessionmaker,
                    phone,
                    last_seen_outbound_id,
                    args.timeout,
                )
    finally:
        await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Terminal WhatsApp simulator for local flows.")
    parser.add_argument("--phone", default="+573001112233", help="Sender phone number.")
    parser.add_argument("--webhook-url", default="http://localhost:8000/webhook")
    parser.add_argument("--timeout", type=float, default=25.0, help="Bot response polling timeout.")
    return parser.parse_args()


def main() -> None:
    asyncio.run(run_repl(parse_args()))


if __name__ == "__main__":
    main()
