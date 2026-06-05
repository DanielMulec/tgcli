from __future__ import annotations

import mimetypes
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from telethon.tl import types

from .dynamic import attribute
from .errors import CliError
from .types import JsonObject, JsonRows, JsonValue


@dataclass(frozen=True)
class ScalarParse:
    # `None` is valid JSON, so handled/unhandled must be tracked separately.
    handled: bool
    value: JsonValue = None


def story_config_from_app_config(app_config: object) -> JsonObject:
    data = telegram_json_value(attribute(app_config, "config", app_config))
    if not isinstance(data, Mapping):
        return {}
    return {key: data[key] for key in sorted(data) if key.startswith(("story_", "stories_"))}


def telegram_json_value(value: object) -> JsonValue:
    scalar = telegram_json_scalar(value)
    if scalar.handled:
        return scalar.value
    if isinstance(value, types.JsonArray):
        return [telegram_json_value(item) for item in value.value]
    if isinstance(value, types.JsonObject):
        return {item.key: telegram_json_value(item.value) for item in value.value}
    return str(value)


def telegram_json_scalar(value: object) -> ScalarParse:
    parsed = telegram_text_or_number(value)
    if parsed.handled:
        return parsed
    return telegram_bool_or_null(value)


def telegram_text_or_number(value: object) -> ScalarParse:
    if isinstance(value, types.JsonString):
        return ScalarParse(True, value.value)
    if isinstance(value, types.JsonNumber):
        return ScalarParse(True, json_number(value.value))
    return ScalarParse(False)


def telegram_bool_or_null(value: object) -> ScalarParse:
    if isinstance(value, types.JsonBool):
        return ScalarParse(True, value.value)
    if isinstance(value, types.JsonNull):
        return ScalarParse(True)
    return ScalarParse(False)


def json_number(number: float) -> int | float:
    return int(number) if float(number).is_integer() else number


def story_wait_seconds(error: str) -> int | None:
    match = re.search(r"STORY_SEND_FLOOD_(?:WEEKLY|MONTHLY)_(\d+)", error)
    return int(match.group(1)) if match else None


def public_story_list(stories: object) -> JsonRows:
    return [story_to_public(story) for story in object_sequence(stories)]


def story_to_public(story: object) -> JsonObject:
    return {
        "id": optional_int(story, "id"),
        "type": type(story).__name__,
        "date": optional_datetime_text(story, "date"),
        "expire_date": optional_datetime_text(story, "expire_date"),
        "caption": optional_text(story, "caption"),
        "out": optional_bool(story, "out"),
        "public": optional_bool(story, "public"),
        "contacts": optional_bool(story, "contacts"),
        "close_friends": optional_bool(story, "close_friends"),
        "pinned": optional_bool(story, "pinned"),
    }


def optional_count(value: object) -> int | None:
    count = attribute(value, "count_remains")
    return int(count) if isinstance(count, int) else None


def optional_int(source: object, attribute: str) -> int | None:
    value = attribute_value(source, attribute)
    return int(value) if isinstance(value, int) else None


def optional_bool(source: object, attribute: str) -> bool | None:
    value = attribute_value(source, attribute)
    return value if isinstance(value, bool) else None


def optional_text(source: object, attribute: str) -> str | None:
    value = attribute_value(source, attribute)
    return value if isinstance(value, str) else None


def optional_datetime_text(source: object, attribute: str) -> str | None:
    value = attribute_value(source, attribute)
    return value.isoformat() if isinstance(value, datetime) else None


def story_privacy_rules(privacy: str) -> list[object]:
    rules: dict[str, type[object]] = {
        "public": types.InputPrivacyValueAllowAll,
        "contacts": types.InputPrivacyValueAllowContacts,
        "close-friends": types.InputPrivacyValueAllowCloseFriends,
    }
    rule = rules.get(privacy)
    if rule is None:
        raise CliError("Story privacy must be one of: public, contacts, close-friends.")
    return [rule()]


def story_period_seconds(period_hours: int) -> int:
    periods = {6: 6 * 3600, 12: 12 * 3600, 24: 24 * 3600, 48: 48 * 3600}
    seconds = periods.get(period_hours)
    if seconds is None:
        raise CliError("Story period must be one of: 6, 12, 24, 48 hours.")
    return seconds


def story_id_from_updates(updates: object, *, random_id: int) -> int | None:
    matching = matching_story_update(updates, random_id=random_id)
    fallback = first_story_update(updates)
    update = matching or fallback
    return update.id if update is not None else None


def matching_story_update(updates: object, *, random_id: int) -> types.UpdateStoryID | None:
    for update in update_list(updates):
        if is_story_update(update, random_id=random_id):
            return cast(types.UpdateStoryID, update)
    return None


def first_story_update(updates: object) -> types.UpdateStoryID | None:
    return next((update for update in update_list(updates) if isinstance(update, types.UpdateStoryID)), None)


def update_list(updates: object) -> list[object]:
    return object_sequence(attribute(updates, "updates", []))


def is_story_update(update: object, *, random_id: int) -> bool:
    return isinstance(update, types.UpdateStoryID) and attribute(update, "random_id") == random_id


def sequence_attr(source: object, name: str) -> list[object]:
    return object_sequence(attribute(source, name, []))


def object_sequence(value: object) -> list[object]:
    if isinstance(value, (str, bytes)):
        return []
    return list(value) if isinstance(value, Sequence) else []


def attribute_value(source: object, name: str) -> object:
    return attribute(source, name)


def validate_story_photo(file_path: Path) -> None:
    if not file_path.exists():
        raise CliError(f"File does not exist: {file_path}")
    if not file_path.is_file():
        raise CliError(f"Not a regular file: {file_path}")
    validate_story_photo_size(file_path)
    validate_story_photo_mime(file_path)


def validate_story_photo_size(file_path: Path) -> None:
    if file_path.stat().st_size > 30 * 1024 * 1024:
        raise CliError("Telegram story media must be 30 MB or smaller.")


def validate_story_photo_mime(file_path: Path) -> None:
    mime_type, unused_encoding = mimetypes.guess_type(str(file_path))
    if unused_encoding:
        return
    if mime_type is not None and not mime_type.startswith("image/"):
        raise CliError(f"Story photo must be an image file, got {mime_type}.")
