from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | Sequence["JsonValue"] | Mapping[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
JsonRows: TypeAlias = list[JsonObject]
TableColumn: TypeAlias = tuple[str, str, int]
SQLiteValue: TypeAlias = str | int | float | bytes | None
