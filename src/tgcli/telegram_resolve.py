from __future__ import annotations

from typing import Protocol

from .errors import CliError
from .store import Store
from .types import SQLiteValue


class EntityResolver(Protocol):
    async def get_entity(self, value: object) -> object: ...

    async def get_input_entity(self, value: object) -> object: ...


async def resolve_input_peer(client: EntityResolver, store: Store | None, value: str) -> object:
    raw = value.strip()
    if raw in {"me", "self"}:
        return await client.get_input_entity("me")
    entity = await resolve_entity(client, store, raw)
    return await client.get_input_entity(entity)


async def resolve_entity(client: EntityResolver, store: Store | None, value: str | None) -> object:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        raise CliError("Empty Telegram entity.")
    entity = await entity_from_telegram(client, raw)
    if entity is not None:
        return entity
    return await entity_from_store(client, store, raw)


async def entity_from_telegram(client: EntityResolver, raw: str) -> object | None:
    entity = await try_get_entity(client, raw)
    if entity is not None:
        return entity
    return await try_get_entity(client, int(raw)) if raw.lstrip("-").isdigit() else None


async def try_get_entity(client: EntityResolver, value: str | int) -> object | None:
    try:
        return await client.get_entity(value)
    except Exception:
        return None


async def entity_from_store(client: EntityResolver, store: Store | None, raw: str) -> object:
    matches = store.find_chats(raw, limit=10) if store is not None and store.path.exists() else []
    if len(matches) == 1:
        return await single_store_match(client, raw, chat_id_from_row(matches[0]["chat_id"]))
    if len(matches) > 1:
        hints = ", ".join(
            f"{display_value(match['title'])} ({display_value(match['chat_id'])})" for match in matches[:5]
        )
        raise CliError(f"Ambiguous chat `{raw}`. Use a numeric chat_id. Matches: {hints}")
    raise CliError(
        f"Could not resolve Telegram chat/user `{raw}`. "
        "Try a @username, phone number, chat_id, or run `tgcli sync`."
    )


async def single_store_match(client: EntityResolver, raw: str, chat_id: int) -> object:
    try:
        return await client.get_entity(chat_id)
    except Exception as exc:
        raise CliError(
            f"Found `{raw}` in the local store, but Telegram could not resolve it. "
            "Run `tgcli sync` and try again."
        ) from exc


def chat_id_from_row(value: SQLiteValue) -> int:
    if not isinstance(value, (str, int)):
        raise CliError("Stored chat_id is not usable.")
    return int(value)


def display_value(value: SQLiteValue) -> str:
    return value.decode(errors="replace") if isinstance(value, bytes) else str(value)
