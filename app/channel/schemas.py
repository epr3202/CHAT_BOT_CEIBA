from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPPORTED_MESSAGE_TYPES = frozenset(
    {
        "text",
        "image",
        "document",
        "audio",
        "video",
        "sticker",
        "location",
        "contacts",
        "reaction",
        "interactive",
        "button",
        "unsupported",
    }
)


class InboundContent(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TextContent(InboundContent):
    body: str = ""


class MediaContent(InboundContent):
    media_id: str = Field(alias="id")
    mime_type: str | None = None
    sha256: str | None = None
    caption: str | None = None
    filename: str | None = None
    voice: bool | None = None
    duration_s: int | None = None


class ReactionContent(InboundContent):
    message_id: str | None = None
    emoji: str | None = None


class SelectionContent(InboundContent):
    kind: str
    id: str
    title: str


class LocationContent(InboundContent):
    latitude: float | None = None
    longitude: float | None = None
    name: str | None = None
    address: str | None = None


class ContactsContent(InboundContent):
    contacts: list[dict[str, Any]] = Field(default_factory=list)


class UnsupportedContent(InboundContent):
    raw_type: str = "unsupported"
    errors: list[dict[str, Any]] = Field(default_factory=list)


class UnknownContent(InboundContent):
    raw_type: str
    raw: Any


InboundMessageContent = (
    TextContent
    | MediaContent
    | ReactionContent
    | SelectionContent
    | LocationContent
    | ContactsContent
    | UnsupportedContent
    | UnknownContent
)


class InboundWhatsAppMessage(BaseModel):
    """Validated, provider-facing representation of one inbound message."""

    model_config = ConfigDict(populate_by_name=True)

    external_message_id: str = Field(alias="id", min_length=1)
    phone_number: str = Field(alias="from", min_length=1)
    message_type: Literal[
        "text",
        "image",
        "document",
        "audio",
        "video",
        "sticker",
        "location",
        "contacts",
        "reaction",
        "interactive",
        "button",
        "unsupported",
        "unknown",
    ] = Field(alias="type")
    content: InboundMessageContent
    provider_timestamp: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_provider_shape(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        message = dict(value)
        raw_type = message.get("type")
        if not isinstance(raw_type, str):
            return message

        message["provider_timestamp"] = _parse_timestamp(message.get("timestamp"))
        if raw_type not in SUPPORTED_MESSAGE_TYPES:
            message["type"] = "unknown"
            message["content"] = {
                "raw_type": raw_type,
                "raw": message.get(raw_type),
            }
            return message

        raw_content = message.get(raw_type)
        if raw_type in {"image", "document", "audio", "video", "sticker"}:
            content = dict(raw_content) if isinstance(raw_content, dict) else {}
            if "id" in content:
                content["media_id"] = content.pop("id")
            message["content"] = content
        elif raw_type in {"interactive", "button"}:
            message["content"] = _selection_content(raw_type, raw_content)
        elif raw_type == "contacts":
            message["content"] = {
                "contacts": raw_content if isinstance(raw_content, list) else []
            }
        elif raw_type == "unsupported":
            content = dict(raw_content) if isinstance(raw_content, dict) else {}
            content["raw_type"] = content.get("raw_type") or content.get("type") or raw_type
            content["errors"] = message.get("errors") or content.get("errors") or []
            message["content"] = content
        else:
            message["content"] = dict(raw_content) if isinstance(raw_content, dict) else {}
        return message

    def storage_content(self) -> dict[str, Any]:
        if isinstance(self.content, SelectionContent):
            selection = self.content.model_dump()
            return {"selection": selection, "text": {"body": self.content.title}}
        if isinstance(self.content, UnknownContent):
            return {"unknown": {"raw": self.content.raw}}
        if isinstance(self.content, ContactsContent):
            return {"contacts": self.content.contacts}
        return {
            self.message_type: self.content.model_dump(
                exclude_none=True,
                by_alias=False,
            )
        }


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), UTC)
    except (TypeError, ValueError, OSError):
        return None


def _selection_content(message_type: str, raw_content: Any) -> dict[str, str]:
    content = raw_content if isinstance(raw_content, dict) else {}
    if message_type == "interactive":
        kind = content.get("type")
        reply = content.get(kind) if isinstance(kind, str) else None
        reply = reply if isinstance(reply, dict) else {}
        return {
            "kind": kind or "interactive",
            "id": str(reply.get("id") or ""),
            "title": str(reply.get("title") or ""),
        }
    return {
        "kind": "button",
        "id": str(content.get("payload") or content.get("id") or ""),
        "title": str(content.get("text") or content.get("title") or ""),
    }
