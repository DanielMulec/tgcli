from __future__ import annotations

import asyncio
import getpass
import mimetypes
import platform
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from telethon import TelegramClient, events
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.tl import functions, types
from telethon.utils import get_display_name, get_peer_id

from . import __version__
from .config import RuntimeConfig, api_credentials, chmod_private_file, ensure_private_dir
from .errors import CliError
from .store import ChatRecord, MessageRecord, Store


def make_client(runtime: RuntimeConfig, *, api_id: int, api_hash: str) -> TelegramClient:
    if runtime.read_only:
        if not runtime.account_dir.exists():
            raise CliError(f"Account directory does not exist in read-only mode: {runtime.account_dir}")
    else:
        ensure_private_dir(runtime.account_dir)
    return TelegramClient(
        str(runtime.session_path),
        api_id,
        api_hash,
        device_model="tgcli",
        system_version=platform.platform(),
        app_version=__version__,
    )


@asynccontextmanager
async def connected_client(runtime: RuntimeConfig) -> AsyncIterator[TelegramClient]:
    api_id, api_hash = api_credentials(runtime)
    if runtime.read_only and not runtime.session_path.exists():
        raise CliError(f"Session file does not exist in read-only mode: {runtime.session_path}")
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise CliError("Not authenticated. Run `tgcli auth qr-login` or `tgcli auth login` first.")
        yield client
    except FloodWaitError as exc:
        raise CliError(f"Telegram rate-limited this request. Retry after {exc.seconds} seconds.") from exc
    except RPCError as exc:
        raise CliError(f"Telegram API error: {exc}") from exc
    finally:
        await client.disconnect()
        if not runtime.read_only:
            chmod_private_file(Path(str(runtime.session_path)))


async def login(
    runtime: RuntimeConfig,
    *,
    api_id: int,
    api_hash: str,
    phone: str | None,
    code: str | None,
) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            return me_to_dict(me)
        phone = phone or input("Telegram phone number (international format): ").strip()
        if not phone:
            raise CliError("Phone number is required.")
        await client.send_code_request(phone)
        code = code or input("Login code from Telegram: ").strip()
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = getpass.getpass("Two-step verification password: ")
            try:
                await client.sign_in(password=password)
            except PasswordHashInvalidError as exc:
                raise CliError("Invalid two-step verification password.") from exc
        except PhoneCodeInvalidError as exc:
            raise CliError("Invalid Telegram login code.") from exc
        except PhoneCodeExpiredError as exc:
            raise CliError("Telegram login code expired. Run `tgcli auth login` again.") from exc
        me = await client.get_me()
        return me_to_dict(me)
    finally:
        await client.disconnect()
        chmod_private_file(Path(str(runtime.session_path)))


async def qr_login(
    runtime: RuntimeConfig,
    *,
    api_id: int,
    api_hash: str,
    timeout: int,
    on_qr: Callable[[str, datetime, int], None],
) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    if timeout <= 0:
        raise CliError("QR login timeout must be greater than zero seconds.")

    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            me = await client.get_me()
            result = me_to_dict(me)
            result["login_method"] = "existing_session"
            return result

        qr = await client.qr_login()
        deadline = datetime.now(timezone.utc).timestamp() + timeout
        attempt = 1

        while True:
            now = datetime.now(timezone.utc)
            remaining_total = deadline - now.timestamp()
            if remaining_total <= 0:
                raise CliError("QR login timed out before Telegram approved the session.")

            remaining_token = max((qr.expires - now).total_seconds(), 1)
            wait_timeout = min(remaining_total, remaining_token)
            wait_task = asyncio.create_task(qr.wait(timeout=wait_timeout))
            await asyncio.sleep(0)
            on_qr(qr.url, qr.expires, attempt)

            try:
                me = await wait_task
                result = me_to_dict(me)
                result["login_method"] = "qr"
                return result
            except SessionPasswordNeededError:
                password = getpass.getpass("Two-step verification password: ")
                try:
                    await client.sign_in(password=password)
                except PasswordHashInvalidError as exc:
                    raise CliError("Invalid two-step verification password.") from exc
                me = await client.get_me()
                result = me_to_dict(me)
                result["login_method"] = "qr"
                return result
            except asyncio.TimeoutError:
                if datetime.now(timezone.utc).timestamp() >= deadline:
                    raise CliError("QR login timed out before Telegram approved the session.")
                attempt += 1
                await qr.recreate()
    finally:
        await client.disconnect()
        chmod_private_file(Path(str(runtime.session_path)))


async def auth_status(runtime: RuntimeConfig) -> dict[str, Any]:
    api_id, api_hash = api_credentials(runtime)
    if not runtime.session_path.exists():
        return {"authorized": False, "session": str(runtime.session_path)}
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        data: dict[str, Any] = {"authorized": authorized, "session": str(runtime.session_path)}
        if authorized:
            data.update(me_to_dict(await client.get_me()))
        return data
    finally:
        await client.disconnect()


async def logout(runtime: RuntimeConfig) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to logout in read-only mode.")
    async with connected_client(runtime) as client:
        await client.log_out()
    return {"authorized": False, "session": str(runtime.session_path)}


async def sync_dialogs(
    runtime: RuntimeConfig,
    *,
    limit: int,
    per_chat: int,
    chat: str | None,
    follow: bool,
) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to sync local state in read-only mode.")
    total_chats = 0
    total_messages = 0
    async with connected_client(runtime) as client:
        with Store(runtime.db_path) as store:
            if chat:
                entity = await resolve_entity(client, store, chat)
                dialogs = [dialog_like_for_entity(entity)]
            else:
                dialogs = []
                async for dialog in client.iter_dialogs(limit=limit):
                    dialogs.append(dialog)

            for dialog in dialogs:
                entity = dialog.entity
                chat_record = chat_record_from_entity(entity, dialog=dialog)
                store.upsert_chat(chat_record)
                total_chats += 1
                min_id = store.max_message_id(chat_record.chat_id)
                fetched = 0
                if min_id:
                    iterator = client.iter_messages(entity, min_id=min_id, reverse=True, limit=per_chat)
                else:
                    iterator = client.iter_messages(entity, limit=per_chat)
                async for message in iterator:
                    msg = await message_record_from_message(client, message, chat_record)
                    if msg:
                        store.upsert_message(msg)
                        fetched += 1
                total_messages += fetched
                store.commit()

            if follow:
                @client.on(events.NewMessage)
                async def handle_new_message(event: events.NewMessage.Event) -> None:
                    nonlocal total_messages, total_chats
                    msg = event.message
                    chat_entity = await event.get_chat()
                    dialog_record = chat_record_from_entity(chat_entity)
                    store.upsert_chat(dialog_record)
                    record = await message_record_from_message(client, msg, dialog_record)
                    if record:
                        store.upsert_message(record)
                        store.commit()
                        total_messages += 1
                        total_chats += 1

                await client.run_until_disconnected()

    return {"chats": total_chats, "messages": total_messages, "store": str(runtime.db_path)}


async def list_live_chats(runtime: RuntimeConfig, *, limit: int, query: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with connected_client(runtime) as client:
        async for dialog in client.iter_dialogs(limit=limit):
            row = chat_record_from_entity(dialog.entity, dialog=dialog).__dict__
            if query and query.lower() not in row.get("title", "").lower() and query.lower() not in (row.get("username") or "").lower():
                continue
            rows.append(normalize_public_chat_row(row))
    return rows


async def list_live_messages(
    runtime: RuntimeConfig,
    *,
    chat: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            entity = await resolve_entity(client, store, chat)
            chat_record = chat_record_from_entity(entity)
            async for message in client.iter_messages(entity, limit=limit):
                record = await message_record_from_message(client, message, chat_record)
                if record:
                    rows.append(message_record_to_public(record))
        finally:
            if store:
                store.close()
    return rows


async def search_live_messages(
    runtime: RuntimeConfig,
    *,
    query: str,
    chat: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            entity = await resolve_entity(client, store, chat) if chat else None
            chat_record = chat_record_from_entity(entity) if entity is not None else None
            async for message in client.iter_messages(entity, search=query, limit=limit):
                if chat_record is None:
                    message_chat = await message.get_chat()
                    current_chat = chat_record_from_entity(message_chat)
                else:
                    current_chat = chat_record
                record = await message_record_from_message(client, message, current_chat)
                if record:
                    rows.append(message_record_to_public(record))
        finally:
            if store:
                store.close()
    return rows


async def send_text(runtime: RuntimeConfig, *, to: str, message: str, reply_to: int | None) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to send a Telegram message in read-only mode.")
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            entity = await resolve_entity(client, store, to)
            sent = await client.send_message(entity, message, reply_to=reply_to)
            peer_id = get_peer_id(entity)
            return {
                "chat_id": peer_id,
                "message_id": sent.id,
                "date": sent.date.isoformat() if sent.date else None,
                "text": sent.raw_text,
            }
        finally:
            if store:
                store.close()


async def send_file(
    runtime: RuntimeConfig,
    *,
    to: str,
    file_path: Path,
    caption: str | None,
    reply_to: int | None,
) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to send a Telegram file in read-only mode.")
    if not file_path.exists():
        raise CliError(f"File does not exist: {file_path}")
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            entity = await resolve_entity(client, store, to)
            sent = await client.send_file(entity, file=str(file_path), caption=caption, reply_to=reply_to)
            peer_id = get_peer_id(entity)
            return {
                "chat_id": peer_id,
                "message_id": sent.id,
                "date": sent.date.isoformat() if sent.date else None,
                "file": str(file_path),
                "caption": caption,
            }
        finally:
            if store:
                store.close()


async def can_post_story(runtime: RuntimeConfig, *, as_peer: str) -> dict[str, Any]:
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            peer = await resolve_input_peer(client, store, as_peer)
            try:
                result = await client(functions.stories.CanSendStoryRequest(peer=peer))
            except RPCError as exc:
                return {
                    "can_post": False,
                    "as": as_peer,
                    "error": str(exc),
                }
            return {
                "can_post": True,
                "as": as_peer,
                "remaining": getattr(result, "count_remains", None),
            }
        finally:
            if store:
                store.close()


async def post_story_photo(
    runtime: RuntimeConfig,
    *,
    as_peer: str,
    file_path: Path,
    caption: str | None,
    privacy: str,
    period_hours: int,
    pinned: bool,
    noforwards: bool,
) -> dict[str, Any]:
    if runtime.read_only:
        raise CliError("Refusing to post a Telegram story in read-only mode.")
    validate_story_photo(file_path)
    period_seconds = story_period_seconds(period_hours)
    random_id = secrets.randbits(63)
    async with connected_client(runtime) as client:
        store = Store(runtime.db_path, read_only=True) if runtime.db_path.exists() else None
        try:
            peer = await resolve_input_peer(client, store, as_peer)
            uploaded = await client.upload_file(str(file_path))
            media = types.InputMediaUploadedPhoto(file=uploaded)
            updates = await client(
                functions.stories.SendStoryRequest(
                    peer=peer,
                    media=media,
                    privacy_rules=story_privacy_rules(privacy),
                    caption=caption,
                    random_id=random_id,
                    period=period_seconds,
                    pinned=pinned or None,
                    noforwards=noforwards or None,
                )
            )
            return {
                "story_id": story_id_from_updates(updates, random_id=random_id),
                "random_id": random_id,
                "as": as_peer,
                "file": str(file_path),
                "caption": caption,
                "privacy": privacy,
                "period_hours": period_hours,
                "pinned": pinned,
                "noforwards": noforwards,
            }
        finally:
            if store:
                store.close()


async def list_contacts(runtime: RuntimeConfig, *, limit: int) -> list[dict[str, Any]]:
    async with connected_client(runtime) as client:
        result = await client(functions.contacts.GetContactsRequest(hash=0))
        contacts = result.users
        rows = []
        for contact in contacts[:limit]:
            rows.append(entity_to_public(contact))
        return rows


async def resolve_input_peer(client: TelegramClient, store: Store | None, value: str) -> Any:
    raw = value.strip()
    if raw in {"me", "self"}:
        return await client.get_input_entity("me")
    entity = await resolve_entity(client, store, raw)
    return await client.get_input_entity(entity)


async def resolve_entity(client: TelegramClient, store: Store | None, value: str | None) -> Any:
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        raise CliError("Empty Telegram entity.")
    try:
        return await client.get_entity(raw)
    except Exception:
        pass
    if raw.lstrip("-").isdigit():
        try:
            return await client.get_entity(int(raw))
        except Exception:
            pass
    matches = store.find_chats(raw, limit=10) if store is not None and store.path.exists() else []
    if len(matches) == 1:
        try:
            return await client.get_entity(int(matches[0]["chat_id"]))
        except Exception as exc:
            raise CliError(
                f"Found `{raw}` in the local store, but Telegram could not resolve it. "
                "Run `tgcli sync` and try again."
            ) from exc
    if len(matches) > 1:
        hints = ", ".join(f"{m['title']} ({m['chat_id']})" for m in matches[:5])
        raise CliError(f"Ambiguous chat `{raw}`. Use a numeric chat_id. Matches: {hints}")
    raise CliError(f"Could not resolve Telegram chat/user `{raw}`. Try a @username, phone number, chat_id, or run `tgcli sync`.")


def dialog_like_for_entity(entity: Any) -> Any:
    class DialogLike:
        def __init__(self, dialog_entity: Any):
            self.entity = dialog_entity
            self.unread_count = None
            self.pinned = None
            self.archived = None

    return DialogLike(entity)


def chat_record_from_entity(entity: Any, *, dialog: Any | None = None) -> ChatRecord:
    title = get_display_name(entity) or getattr(entity, "title", None) or getattr(entity, "username", None) or str(get_peer_id(entity))
    kind = entity_kind(entity)
    raw: dict[str, Any] = {
        "id": getattr(entity, "id", None),
        "access_hash": getattr(entity, "access_hash", None),
        "username": getattr(entity, "username", None),
        "phone": getattr(entity, "phone", None),
    }
    return ChatRecord(
        chat_id=int(get_peer_id(entity)),
        title=title,
        kind=kind,
        username=getattr(entity, "username", None),
        phone=getattr(entity, "phone", None),
        unread_count=getattr(dialog, "unread_count", None) if dialog is not None else None,
        pinned=getattr(dialog, "pinned", None) if dialog is not None else None,
        archived=getattr(dialog, "archived", None) if dialog is not None else None,
        raw=raw,
    )


async def message_record_from_message(
    client: TelegramClient,
    message: Any,
    chat_record: ChatRecord,
) -> MessageRecord | None:
    if not getattr(message, "id", None):
        return None
    text = getattr(message, "raw_text", None) or getattr(message, "message", None) or ""
    sender_id = getattr(message, "sender_id", None)
    sender_name = None
    try:
        sender = await message.get_sender()
        sender_name = get_display_name(sender) if sender else None
    except Exception:
        sender = None
    return MessageRecord(
        chat_id=chat_record.chat_id,
        message_id=int(message.id),
        date=message.date.isoformat() if getattr(message, "date", None) else None,
        sender_id=int(sender_id) if sender_id is not None else None,
        sender_name=sender_name,
        chat_title=chat_record.title,
        text=text,
        outgoing=getattr(message, "out", None),
        media_type=media_type_name(getattr(message, "media", None)),
        reply_to_msg_id=getattr(message, "reply_to_msg_id", None),
        raw={
            "mentioned": getattr(message, "mentioned", None),
            "post": getattr(message, "post", None),
            "edit_date": getattr(message, "edit_date", None),
        },
    )


def message_record_to_public(record: MessageRecord) -> dict[str, Any]:
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


def normalize_public_chat_row(row: dict[str, Any]) -> dict[str, Any]:
    raw = dict(row)
    raw.pop("raw", None)
    return raw


def entity_to_public(entity: Any) -> dict[str, Any]:
    return {
        "chat_id": get_peer_id(entity),
        "title": get_display_name(entity),
        "kind": entity_kind(entity),
        "username": getattr(entity, "username", None),
        "phone": getattr(entity, "phone", None),
    }


def me_to_dict(me: Any) -> dict[str, Any]:
    return {
        "authorized": True,
        "id": getattr(me, "id", None),
        "name": get_display_name(me),
        "username": getattr(me, "username", None),
        "phone": getattr(me, "phone", None),
        "bot": getattr(me, "bot", False),
    }


def entity_kind(entity: Any) -> str:
    if isinstance(entity, types.User):
        return "bot" if getattr(entity, "bot", False) else "user"
    if isinstance(entity, types.Chat):
        return "group"
    if isinstance(entity, types.Channel):
        if getattr(entity, "broadcast", False):
            return "channel"
        if getattr(entity, "megagroup", False):
            return "supergroup"
        return "channel"
    return type(entity).__name__.lower()


def media_type_name(media: Any | None) -> str | None:
    if media is None:
        return None
    if isinstance(media, types.MessageMediaPhoto):
        return "photo"
    if isinstance(media, types.MessageMediaDocument):
        document = getattr(media, "document", None)
        if document:
            for attr in getattr(document, "attributes", []) or []:
                if isinstance(attr, types.DocumentAttributeAudio):
                    return "voice" if getattr(attr, "voice", False) else "audio"
                if isinstance(attr, types.DocumentAttributeVideo):
                    return "video"
                if isinstance(attr, types.DocumentAttributeSticker):
                    return "sticker"
        return "document"
    if isinstance(media, types.MessageMediaWebPage):
        return "webpage"
    if isinstance(media, types.MessageMediaGeo):
        return "geo"
    if isinstance(media, types.MessageMediaContact):
        return "contact"
    if isinstance(media, types.MessageMediaPoll):
        return "poll"
    return type(media).__name__


def story_privacy_rules(privacy: str) -> list[Any]:
    if privacy == "public":
        return [types.InputPrivacyValueAllowAll()]
    if privacy == "contacts":
        return [types.InputPrivacyValueAllowContacts()]
    if privacy == "close-friends":
        return [types.InputPrivacyValueAllowCloseFriends()]
    raise CliError("Story privacy must be one of: public, contacts, close-friends.")


def story_period_seconds(period_hours: int) -> int:
    periods = {6: 6 * 3600, 12: 12 * 3600, 24: 24 * 3600, 48: 48 * 3600}
    if period_hours not in periods:
        raise CliError("Story period must be one of: 6, 12, 24, 48 hours.")
    return periods[period_hours]


def story_id_from_updates(updates: Any, *, random_id: int) -> int | None:
    for update in getattr(updates, "updates", []) or []:
        if isinstance(update, types.UpdateStoryID) and getattr(update, "random_id", None) == random_id:
            return int(update.id)
    for update in getattr(updates, "updates", []) or []:
        if isinstance(update, types.UpdateStoryID):
            return int(update.id)
    return None


def validate_story_photo(file_path: Path) -> None:
    if not file_path.exists():
        raise CliError(f"File does not exist: {file_path}")
    if not file_path.is_file():
        raise CliError(f"Not a regular file: {file_path}")
    max_bytes = 30 * 1024 * 1024
    size = file_path.stat().st_size
    if size > max_bytes:
        raise CliError("Telegram story media must be 30 MB or smaller.")
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is not None and not mime_type.startswith("image/"):
        raise CliError(f"Story photo must be an image file, got {mime_type}.")


def run(coro: Any) -> Any:
    return asyncio.run(coro)
