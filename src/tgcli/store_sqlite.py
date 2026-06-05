from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from .types import SQLiteValue

SQLParams = Sequence[SQLiteValue]


def execute(connection: sqlite3.Connection, sql: str, params: SQLParams = ()) -> sqlite3.Cursor:
    return connection.execute(sql, params)


def fetch_one(connection: sqlite3.Connection, sql: str, params: SQLParams = ()) -> sqlite3.Row | None:
    return execute(connection, sql, params).fetchone()  # type: ignore[misc,no-any-return]


def fetch_all(connection: sqlite3.Connection, sql: str, params: SQLParams = ()) -> list[sqlite3.Row]:
    return execute(connection, sql, params).fetchall()  # type: ignore[misc]


def row_value(row: sqlite3.Row, key: str) -> SQLiteValue:
    return row[key]  # type: ignore[misc,no-any-return]


def row_dict(row: sqlite3.Row) -> dict[str, SQLiteValue]:
    keys = list(row.keys())
    return {key: row_value(row, key) for key in keys}


def row_dicts(rows: list[sqlite3.Row]) -> list[dict[str, SQLiteValue]]:
    return [row_dict(row) for row in rows]


def optional_row_dict(row: sqlite3.Row | None) -> dict[str, SQLiteValue] | None:
    return row_dict(row) if row is not None else None


def required_row(row: sqlite3.Row | None) -> sqlite3.Row:
    if row is None:
        raise RuntimeError("Expected SQLite query to return one row.")
    return row


def row_int(row: sqlite3.Row, key: str, *, default: int = 0) -> int:
    value = row_value(row, key)
    return int(value) if value is not None else default
