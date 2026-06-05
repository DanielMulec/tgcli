from __future__ import annotations

import os
import sqlite3

from .config import RuntimeConfig, api_credentials
from .dynamic import attribute
from .errors import CliError
from .types import TableColumn

CHAT_COLUMNS: list[TableColumn] = [
    ("chat_id", "CHAT_ID", 20),
    ("kind", "KIND", 12),
    ("title", "TITLE", 36),
    ("username", "USERNAME", 24),
    ("unread_count", "UNREAD", 8),
]

MESSAGE_COLUMNS: list[TableColumn] = [
    ("date", "DATE", 24),
    ("chat_title", "CHAT", 28),
    ("sender_name", "SENDER", 24),
    ("message_id", "MSG_ID", 10),
    ("text", "TEXT", 80),
]

DOCTOR_COLUMNS: list[TableColumn] = [
    ("check", "CHECK", 24),
    ("ok", "OK", 8),
    ("detail", "DETAIL", 80),
]


def arg_bool(args: object, name: str) -> bool:
    return bool(attribute(args, name))


def arg_int(args: object, name: str) -> int:
    value = attribute(args, name)
    if isinstance(value, int):
        return value
    raise CliError(f"Internal parser error: {name} must be an integer.")


def arg_optional_int(args: object, name: str) -> int | None:
    value = attribute(args, name)
    if value is None or isinstance(value, int):
        return value
    raise CliError(f"Internal parser error: {name} must be an integer.")


def arg_optional_str(args: object, name: str) -> str | None:
    value = attribute(args, name)
    if value is None or isinstance(value, str):
        return value
    raise CliError(f"Internal parser error: {name} must be text.")


def arg_str(args: object, name: str) -> str:
    value = arg_optional_str(args, name)
    if value is None:
        raise CliError(f"Internal parser error: {name} is required.")
    return value


def credentials_for_login(runtime: RuntimeConfig, args: object) -> tuple[int, str]:
    api_id = arg_optional_str(args, "api_id")
    api_hash = arg_optional_str(args, "api_hash")
    if api_id and api_hash:
        return api_credentials(runtime, api_id=api_id, api_hash=api_hash)
    try:
        return api_credentials(runtime, api_id=api_id, api_hash=api_hash)
    except CliError:
        prompted_id = api_id or input("Telegram API ID (from my.telegram.org): ").strip()
        prompted_hash = api_hash or input("Telegram API hash: ").strip()
        return api_credentials(runtime, api_id=prompted_id, api_hash=prompted_hash)


def parse_int(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise CliError(f"{label} must be an integer for local-store commands. Use --live for names/usernames.") from exc


def api_env_present() -> bool:
    api_id = os.environ.get("TGCLI_API_ID") or os.environ.get("TELEGRAM_API_ID")
    api_hash = os.environ.get("TGCLI_API_HASH") or os.environ.get("TELEGRAM_API_HASH")
    return bool(api_id and api_hash)


def sqlite_has_fts5() -> bool:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE VIRTUAL TABLE f USING fts5(x)")
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return True
