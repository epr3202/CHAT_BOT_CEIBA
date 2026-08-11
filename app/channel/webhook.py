from __future__ import annotations

import hashlib
import hmac
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse

from app.channel.inbound import (
    process_webhook_event,
    record_invalid_signature_attempt,
    store_webhook_event,
)
from app.config.settings import Settings

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    request: Request,
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> PlainTextResponse:
    settings: Settings = request.app.state.settings
    if hub_mode == "subscribe" and hub_verify_token == settings.meta_verify_token:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    content_length: str | None = Header(default=None, alias="Content-Length"),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> JSONResponse:
    settings: Settings = request.app.state.settings
    if is_body_too_large_from_header(content_length, settings.webhook_max_body_bytes):
        logger.warning(
            "whatsapp_webhook_rejected_body_too_large",
            request_id=x_request_id,
            content_length=content_length,
            max_body_bytes=settings.webhook_max_body_bytes,
        )
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    body = await request.body()
    if len(body) > settings.webhook_max_body_bytes:
        logger.warning(
            "whatsapp_webhook_rejected_body_too_large",
            request_id=x_request_id,
            body_bytes=len(body),
            max_body_bytes=settings.webhook_max_body_bytes,
        )
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE)

    if not is_valid_signature(body, x_hub_signature_256, settings.meta_app_secret):
        await record_invalid_signature_attempt(
            request.app.state.db_sessionmaker,
            request_id=x_request_id,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    payload: dict[str, Any] = await request.json()
    webhook_event_id = await store_webhook_event(
        payload,
        request.app.state.db_sessionmaker,
        request_id=x_request_id,
    )
    background_tasks.add_task(
        process_webhook_event,
        webhook_event_id,
        request.app.state.db_sessionmaker,
    )
    logger.info(
        "whatsapp_webhook_accepted",
        request_id=x_request_id,
        webhook_event_id=webhook_event_id,
    )
    return JSONResponse({"status": "accepted"})


def is_valid_signature(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not signature_header:
        return False

    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False

    expected_signature = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    provided_signature = signature_header[len(prefix) :]
    return hmac.compare_digest(provided_signature, expected_signature)


def is_body_too_large_from_header(
    content_length: str | None,
    max_body_bytes: int,
) -> bool:
    if content_length is None:
        return False
    try:
        return int(content_length) > max_body_bytes
    except (TypeError, ValueError):
        return False
