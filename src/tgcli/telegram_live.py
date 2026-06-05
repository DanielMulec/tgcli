from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Protocol, cast

from telethon import TelegramClient, events
from telethon.utils import get_peer_id

from .config import RuntimeConfig
from .errors import CliError
from .store import ChatRecord, MessageRecord, Store
from .telegram_client import connected_client
from .telegram_mapping import (
    chat_record_from_entity,
    dialog_like_for_entity,
    message_record_from_message,
    message_record_to_public,
    normalize_public_chat_record,
)
from .telegram_resolve import resolve_entity
from .types import JsonObject, JsonRows


class DialogWithEntity(Protocol):
    # Dialogs are created by Telethon at runtime, so only the fields used here are modeled.
    entity: object


class MessageWithChat(Protocol):
    async def get_chat(self) -> object: ...


class NewMessageEvent(Protocol):
    message: object

    async def get_chat(self) -> object: ...


class SentMessage(Protocol):
    id: int
    date: datetime | None


async def sync_dialogs(
    runtime: RuntimeConfig,
    *,
    limit: int,
    per_chat: int,
    chat: str | None,
    follow: bool,
) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to sync local state in read-only mode.")
    async with connected_client(runtime) as client:
        with Store(runtime.db_path) as store:
            totals = {"chats": 0, "messages": 0}
            for dialog in await sync_dialog_sources(client, store, chat, limit):
                totals["messages"] += await sync_dialog_messages(client, store, dialog, per_chat)
                totals["chats"] += 1
            if follow:
                await follow_new_messages(client, store, totals)
    return {"chats": totals["chats"], "messages": totals["messages"], "store": str(runtime.db_path)}


async def sync_dialog_sources(client: TelegramClient, store: Store, chat: str | None, limit: int) -> list[object]:
    if chat:
        return [dialog_like_for_entity(await resolve_entity(client, store, chat))]
    dialogs: list[object] = []
    async for dialog in client.iter_dialogs(limit=limit):
        dialogs.append(dialog)
    return dialogs


async def sync_dialog_messages(client: TelegramClient, store: Store, dialog: object, per_chat: int) -> int:
    typed_dialog = cast(DialogWithEntity, dialog)
    chat_record = chat_record_from_entity(typed_dialog.entity, dialog=dialog)
    store.upsert_chat(chat_record)
    fetched = await fetch_new_messages(client, store, chat_record, typed_dialog.entity, per_chat)
    store.commit()
    return fetched


async def fetch_new_messages(
    client: TelegramClient,
    store: Store,
    chat_record: ChatRecord,
    entity: object,
    per_chat: int,
) -> int:
    fetched = 0
    message_iterator = incremental_message_iterator(client, store, chat_record, entity, per_chat)
    async for message in message_iterator:
        record = await message_record_from_message(client, message, chat_record)
        if record is not None:
            store.upsert_message(record)
            fetched += 1
    return fetched


def incremental_message_iterator(
    client: TelegramClient,
    store: Store,
    chat_record: ChatRecord,
    entity: object,
    per_chat: int,
) -> AsyncIterator[object]:
    min_id = store.max_message_id(chat_record.chat_id)
    if min_id:
        return client.iter_messages(entity, min_id=min_id, reverse=True, limit=per_chat)
    return client.iter_messages(entity, limit=per_chat)


async def follow_new_messages(client: TelegramClient, store: Store, totals: dict[str, int]) -> None:
    @client.on(events.NewMessage)
    async def handle_new_message(event: object) -> None:
        record = await event_message_record(client, event)
        store.upsert_chat(record[0])
        if record[1] is not None:
            store.upsert_message(record[1])
            store.commit()
            totals["messages"] += 1
            totals["chats"] += 1

    await client.run_until_disconnected()


async def event_message_record(
    client: TelegramClient,
    event: object,
) -> tuple[ChatRecord, MessageRecord | None]:
    typed_event = cast(NewMessageEvent, event)
    chat_entity = await typed_event.get_chat()
    chat_record = chat_record_from_entity(chat_entity)
    message_record = await message_record_from_message(client, typed_event.message, chat_record)
    return chat_record, message_record


async def list_live_chats(runtime: RuntimeConfig, *, limit: int, query: str | None) -> JsonRows:
    rows: JsonRows = []
    async with connected_client(runtime) as client:
        async for dialog in client.iter_dialogs(limit=limit):
            typed_dialog = cast(DialogWithEntity, dialog)
            row = normalize_public_chat_record(chat_record_from_entity(typed_dialog.entity, dialog=dialog))
            if chat_matches_query(row, query):
                rows.append(row)
    return rows


def chat_matches_query(row: JsonObject, query: str | None) -> bool:
    if not query:
        return True
    normalized_query = query.lower()
    title = str(row.get("title") or "").lower()
    username = str(row.get("username") or "").lower()
    return normalized_query in title or normalized_query in username


async def list_live_messages(runtime: RuntimeConfig, *, chat: str, limit: int) -> JsonRows:
    async with connected_client(runtime) as client:
        store = open_optional_store(runtime)
        try:
            return await live_messages_for_chat(client, store, chat, limit)
        finally:
            close_optional_store(store)


async def live_messages_for_chat(client: TelegramClient, store: Store | None, chat: str, limit: int) -> JsonRows:
    rows: JsonRows = []
    entity = await resolve_entity(client, store, chat)
    chat_record = chat_record_from_entity(entity)
    async for message in client.iter_messages(entity, limit=limit):
        record = await message_record_from_message(client, message, chat_record)
        if record is not None:
            rows.append(message_record_to_public(record))
    return rows


async def search_live_messages(runtime: RuntimeConfig, *, query: str, chat: str | None, limit: int) -> JsonRows:
    async with connected_client(runtime) as client:
        store = open_optional_store(runtime)
        try:
            return await live_search_rows(client, store, query, chat, limit)
        finally:
            close_optional_store(store)


async def live_search_rows(
    client: TelegramClient,
    store: Store | None,
    query: str,
    chat: str | None,
    limit: int,
) -> JsonRows:
    rows: JsonRows = []
    entity = await resolve_entity(client, store, chat) if chat else None
    chat_record = chat_record_from_entity(entity) if entity is not None else None
    async for message in client.iter_messages(entity, search=query, limit=limit):
        current_chat = chat_record or chat_record_from_entity(await cast(MessageWithChat, message).get_chat())
        record = await message_record_from_message(client, message, current_chat)
        if record is not None:
            rows.append(message_record_to_public(record))
    return rows


async def send_text(runtime: RuntimeConfig, *, to: str, message: str, reply_to: int | None) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to send a Telegram message in read-only mode.")
    async with connected_client(runtime) as client:
        return await send_message_with_store(runtime, client, to, message, reply_to)


async def send_message_with_store(
    runtime: RuntimeConfig,
    client: TelegramClient,
    to: str,
    message: str,
    reply_to: int | None,
) -> JsonObject:
    store = open_optional_store(runtime)
    try:
        entity = await resolve_entity(client, store, to)
        sent = await client.send_message(entity, message, reply_to=reply_to)
        return sent_message_result(entity, sent, "text", message)
    finally:
        close_optional_store(store)


async def send_file(
    runtime: RuntimeConfig,
    *,
    to: str,
    file_path: Path,
    caption: str | None,
    reply_to: int | None,
) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to send a Telegram file in read-only mode.")
    if not file_path.exists():
        raise CliError(f"File does not exist: {file_path}")
    async with connected_client(runtime) as client:
        return await send_file_with_store(runtime, client, to, file_path, caption, reply_to)


async def send_file_with_store(
    runtime: RuntimeConfig,
    client: TelegramClient,
    to: str,
    file_path: Path,
    caption: str | None,
    reply_to: int | None,
) -> JsonObject:
    store = open_optional_store(runtime)
    try:
        entity = await resolve_entity(client, store, to)
        sent = await client.send_file(entity, file=str(file_path), caption=caption, reply_to=reply_to)
        return sent_message_result(entity, sent, "file", str(file_path), caption=caption)
    finally:
        close_optional_store(store)


def sent_message_result(
    entity: object,
    sent: object,
    payload_key: str,
    payload: str,
    *,
    caption: str | None = None,
) -> JsonObject:
    typed_message = cast(SentMessage, sent)
    result: JsonObject = {
        "chat_id": int(get_peer_id(entity)),
        "message_id": int(typed_message.id),
        "date": typed_message.date.isoformat() if typed_message.date else None,
        payload_key: payload,
    }
    if caption is not None:
        result["caption"] = caption
    return result


def open_optional_store(runtime: RuntimeConfig) -> Store | None:
    return Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None


def close_optional_store(store: Store | None) -> None:
    if store is not None:
        store.close()
