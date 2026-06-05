from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from .dynamic import json_loads
from .errors import CliError
from .types import JsonObject, JsonValue, SQLiteValue


def json_dumps(value: JsonObject | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def required_row_id(row_id: int | None) -> int:
    if row_id is None:
        raise CliError("SQLite did not return a row id for the inserted message.")
    return row_id


def raw_json_value(raw: SQLiteValue) -> object:
    # Old rows may contain invalid JSON or non-text SQLite values; keep output stable either way.
    if not isinstance(raw, (str, bytes)):
        return raw
    try:
        return json_loads(raw)
    except json.JSONDecodeError:
        return raw


def json_value(value: object) -> JsonValue:
    handled, scalar = scalar_json_value(value)
    if handled:
        return scalar
    return composite_json_value(value)


def scalar_json_value(value: object) -> tuple[bool, JsonValue]:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True, value
    if isinstance(value, bytes):
        return True, value.decode(errors="replace")
    return False, None


def composite_json_value(value: object) -> JsonValue:
    if isinstance(value, Mapping):
        return {str(key): json_value(child) for key, child in value.items()}
    if isinstance(value, Sequence):
        return [json_value(child) for child in value]
    return str(value)
