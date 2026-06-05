from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from telethon import TelegramClient
from telethon.tl import types
from telethon.utils import get_display_name, get_peer_id

from .dynamic import attribute
from .store import ChatRecord, MessageRecord
from .types import JsonObject


@dataclass(frozen=True)
class DialogLike:
    entity: object
    unread_count: int | None = None
    pinned: bool | None = None
    archived: bool | None = None


class SenderMessage(Protocol):
    async def get_sender(self) -> object: ...


def dialog_like_for_entity(entity: object) -> DialogLike:
    return DialogLike(entity=entity)


def chat_record_from_entity(entity: object, *, dialog: object | None = None) -> ChatRecord:
    title = entity_title(entity)
    return ChatRecord(
        chat_id=int(get_peer_id(entity)),
        title=title,
        kind=entity_kind(entity),
        username=optional_text(entity, "username"),
        phone=optional_text(entity, "phone"),
        unread_count=optional_int(dialog, "unread_count"),
        pinned=optional_bool(dialog, "pinned"),
        archived=optional_bool(dialog, "archived"),
        raw=entity_raw(entity),
    )


def entity_title(entity: object) -> str:
    display_name = get_display_name(entity)
    fallback = optional_text(entity, "title") or optional_text(entity, "username") or str(get_peer_id(entity))
    return display_name or fallback


def entity_raw(entity: object) -> JsonObject:
    return {
        "id": optional_int(entity, "id"),
        "access_hash": optional_int(entity, "access_hash"),
        "username": optional_text(entity, "username"),
        "phone": optional_text(entity, "phone"),
    }


async def message_record_from_message(
    client: TelegramClient,
    message: object,
    chat_record: ChatRecord,
) -> MessageRecord | None:
    message_id = optional_int(message, "id")
    if message_id is None:
        return None
    sender_name = await sender_display_name(message)
    return MessageRecord(
        chat_id=chat_record.chat_id,
        message_id=message_id,
        date=optional_datetime_text(message, "date"),
        sender_id=optional_int(message, "sender_id"),
        sender_name=sender_name,
        chat_title=chat_record.title,
        text=message_text(message),
        outgoing=optional_bool(message, "out"),
        media_type=media_type_name(attribute(message, "media")),
        reply_to_msg_id=optional_int(message, "reply_to_msg_id"),
        raw=message_raw(message),
    )


async def sender_display_name(message: object) -> str | None:
    try:
        sender = await cast(SenderMessage, message).get_sender()
    except (AttributeError, TypeError):
        return None
    return get_display_name(sender) if sender else None


def message_text(message: object) -> str:
    raw_text = optional_text(message, "raw_text")
    fallback = optional_text(message, "message")
    return raw_text or fallback or ""


def message_raw(message: object) -> JsonObject:
    return {
        "mentioned": optional_bool(message, "mentioned"),
        "post": optional_bool(message, "post"),
        "edit_date": optional_datetime_text(message, "edit_date"),
    }


def message_record_to_public(record: MessageRecord) -> JsonObject:
    return {
        "chat_id": record.chat_id,
        "message_id": record.message_id,
        "date": record.date,
        "sender_id": record.sender_id,
        "sender_name": record.sender_name,
        "chat_title": record.chat_title,
        "text": record.text,
        "outgoing": record.outgoing,
        "media_type": record.media_type,
        "reply_to_msg_id": record.reply_to_msg_id,
    }


def normalize_public_chat_record(record: ChatRecord) -> JsonObject:
    return {
        "chat_id": record.chat_id,
        "title": record.title,
        "kind": record.kind,
        "username": record.username,
        "phone": record.phone,
        "unread_count": record.unread_count,
        "pinned": record.pinned,
        "archived": record.archived,
    }


def entity_to_public(entity: object) -> JsonObject:
    return {
        "chat_id": int(get_peer_id(entity)),
        "title": get_display_name(entity),
        "kind": entity_kind(entity),
        "username": optional_text(entity, "username"),
        "phone": optional_text(entity, "phone"),
    }


def me_to_dict(me: object) -> JsonObject:
    return {
        "authorized": True,
        "id": optional_int(me, "id"),
        "name": get_display_name(me),
        "username": optional_text(me, "username"),
        "phone": optional_text(me, "phone"),
        "bot": optional_bool(me, "bot") or False,
    }


def entity_kind(entity: object) -> str:
    if isinstance(entity, types.User):
        return "bot" if bool(attribute(entity, "bot", False)) else "user"
    if isinstance(entity, types.Chat):
        return "group"
    if isinstance(entity, types.Channel):
        return channel_kind(entity)
    return type(entity).__name__.lower()


def channel_kind(channel: types.Channel) -> str:
    if bool(attribute(channel, "megagroup", False)):
        return "supergroup"
    return "channel"


def media_type_name(media: object | None) -> str | None:
    if media is None:
        return None
    if isinstance(media, types.MessageMediaPhoto):
        return "photo"
    if isinstance(media, types.MessageMediaDocument):
        return document_media_type(media)
    return simple_media_type(media)


def document_media_type(media: types.MessageMediaDocument) -> str:
    document = attribute(media, "document")
    if document is None:
        return "document"
    return document_attribute_media_type(attribute(document, "attributes", []) or [])


def document_attribute_media_type(attributes: object) -> str:
    if not isinstance(attributes, Iterable):
        return "document"
    for media_attribute in attributes:
        detected = media_type_from_attribute(media_attribute)
        if detected is not None:
            return detected
    return "document"


def media_type_from_attribute(attribute: object) -> str | None:
    if isinstance(attribute, types.DocumentAttributeAudio):
        return "voice" if bool(attribute_value(attribute, "voice", False)) else "audio"
    if isinstance(attribute, types.DocumentAttributeVideo):
        return "video"
    if isinstance(attribute, types.DocumentAttributeSticker):
        return "sticker"
    return None


def simple_media_type(media: object) -> str:
    mapping = {
        types.MessageMediaWebPage: "webpage",
        types.MessageMediaGeo: "geo",
        types.MessageMediaContact: "contact",
        types.MessageMediaPoll: "poll",
    }
    return next((name for media_type, name in mapping.items() if isinstance(media, media_type)), type(media).__name__)


def optional_text(source: object | None, attribute: str) -> str | None:
    value = attribute_value(source, attribute)
    return value if isinstance(value, str) else None


def optional_int(source: object | None, attribute: str) -> int | None:
    value = attribute_value(source, attribute)
    return int(value) if isinstance(value, int) else None


def optional_bool(source: object | None, attribute: str) -> bool | None:
    value = attribute_value(source, attribute)
    return value if isinstance(value, bool) else None


def optional_datetime_text(source: object | None, attribute: str) -> str | None:
    value = attribute_value(source, attribute)
    return value.isoformat() if isinstance(value, datetime) else None


def attribute_value(source: object | None, name: str, default: object = None) -> object:
    return attribute(source, name, default) if source is not None else default
