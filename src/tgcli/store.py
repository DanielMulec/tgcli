from __future__ import annotations

import sqlite3
import types
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import chmod_private_file, ensure_parent
from .errors import CliError
from .store_json import json_dumps, json_value, raw_json_value, required_row_id, utc_now
from .store_sqlite import execute, fetch_all, fetch_one, optional_row_dict, required_row, row_dicts, row_int
from .types import JsonObject, SQLiteValue

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ChatRecord:
    chat_id: int
    title: str
    kind: str
    username: str | None = None
    phone: str | None = None
    unread_count: int | None = None
    pinned: bool | None = None
    archived: bool | None = None
    raw: JsonObject | None = None


@dataclass(frozen=True)
class MessageRecord:
    chat_id: int
    message_id: int
    date: str | None
    sender_id: int | None
    sender_name: str | None
    chat_title: str | None
    text: str
    outgoing: bool | None = None
    media_type: str | None = None
    reply_to_msg_id: int | None = None
    raw: JsonObject | None = None


class Store:
    def __init__(self, path: Path, *, read_only: bool = False) -> None:
        self.path = path
        self.read_only = read_only
        if read_only and not path.exists():
            raise CliError(f"Store does not exist: {path}")
        if not read_only:
            ensure_parent(path)
        uri = f"{path.expanduser().resolve().as_uri()}?mode=ro" if read_only else str(path)
        self.conn = sqlite3.connect(uri, uri=read_only)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        if not read_only:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.migrate()
            chmod_private_file(path)

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: types.TracebackType | None,
    ) -> None:
        self.close()

    def migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
              chat_id INTEGER PRIMARY KEY,
              title TEXT NOT NULL,
              kind TEXT NOT NULL,
              username TEXT,
              phone TEXT,
              unread_count INTEGER,
              pinned INTEGER,
              archived INTEGER,
              updated_at TEXT NOT NULL,
              raw_json TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              chat_id INTEGER NOT NULL,
              message_id INTEGER NOT NULL,
              date TEXT,
              sender_id INTEGER,
              sender_name TEXT,
              chat_title TEXT,
              text TEXT NOT NULL DEFAULT '',
              outgoing INTEGER,
              media_type TEXT,
              reply_to_msg_id INTEGER,
              raw_json TEXT,
              synced_at TEXT NOT NULL,
              UNIQUE(chat_id, message_id)
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat_date
              ON messages(chat_id, date DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_sender
              ON messages(sender_id);
            """
        )
        try:
            self.conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts "
                "USING fts5(text, sender_name, chat_title, tokenize='unicode61')"
            )
        except sqlite3.OperationalError as exc:
            raise CliError(f"SQLite FTS5 is not available: {exc}") from exc
        self.conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.conn.commit()

    def upsert_chat(self, record: ChatRecord) -> None:
        self._ensure_writable()
        now = utc_now()
        self.conn.execute(
            """
            INSERT INTO chats (
              chat_id, title, kind, username, phone, unread_count, pinned,
              archived, updated_at, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
              title=excluded.title,
              kind=excluded.kind,
              username=excluded.username,
              phone=excluded.phone,
              unread_count=excluded.unread_count,
              pinned=excluded.pinned,
              archived=excluded.archived,
              updated_at=excluded.updated_at,
              raw_json=excluded.raw_json
            """,
            (
                record.chat_id,
                record.title,
                record.kind,
                record.username,
                record.phone,
                record.unread_count,
                int(record.pinned) if record.pinned is not None else None,
                int(record.archived) if record.archived is not None else None,
                now,
                json_dumps(record.raw),
            ),
        )

    def upsert_message(self, record: MessageRecord) -> int:
        self._ensure_writable()
        now = utc_now()
        existing = fetch_one(
            self.conn,
            "SELECT id FROM messages WHERE chat_id=? AND message_id=?",
            (record.chat_id, record.message_id),
        )
        params = (
            record.chat_id,
            record.message_id,
            record.date,
            record.sender_id,
            record.sender_name,
            record.chat_title,
            record.text or "",
            int(record.outgoing) if record.outgoing is not None else None,
            record.media_type,
            record.reply_to_msg_id,
            json_dumps(record.raw),
            now,
        )
        if existing:
            row_id = row_int(existing, "id")
            execute(
                self.conn,
                """
                UPDATE messages SET
                  chat_id=?, message_id=?, date=?, sender_id=?, sender_name=?,
                  chat_title=?, text=?, outgoing=?, media_type=?, reply_to_msg_id=?,
                  raw_json=?, synced_at=?
                WHERE id=?
                """,
                (*params, row_id),
            )
        else:
            cur = execute(
                self.conn,
                """
                INSERT INTO messages (
                  chat_id, message_id, date, sender_id, sender_name, chat_title,
                  text, outgoing, media_type, reply_to_msg_id, raw_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params,
            )
            row_id = required_row_id(cur.lastrowid)
        execute(
            self.conn,
            "INSERT OR REPLACE INTO messages_fts(rowid, text, sender_name, chat_title) VALUES (?, ?, ?, ?)",
            (row_id, record.text or "", record.sender_name or "", record.chat_title or ""),
        )
        return row_id

    def commit(self) -> None:
        self.conn.commit()

    def chats(self, *, query: str | None = None, limit: int = 50) -> list[dict[str, SQLiteValue]]:
        sql = "SELECT * FROM chats"
        params: list[SQLiteValue] = []
        if query:
            sql += " WHERE title LIKE ? OR username LIKE ? OR phone LIKE ?"
            pattern = f"%{query}%"
            params.extend([pattern, pattern, pattern])
        sql += " ORDER BY updated_at DESC, title COLLATE NOCASE LIMIT ?"
        params.append(limit)
        return row_dicts(fetch_all(self.conn, sql, params))

    def chat(self, chat_id: int) -> dict[str, SQLiteValue] | None:
        row = fetch_one(self.conn, "SELECT * FROM chats WHERE chat_id=?", (chat_id,))
        return optional_row_dict(row)

    def find_chats(self, query: str, *, limit: int = 20) -> list[dict[str, SQLiteValue]]:
        exact = fetch_all(
            self.conn,
            """
            SELECT * FROM chats
            WHERE username = ? OR phone = ? OR title = ? OR CAST(chat_id AS TEXT) = ?
            ORDER BY title COLLATE NOCASE
            LIMIT ?
            """,
            (query.lstrip("@"), query, query, query, limit),
        )
        if exact:
            return row_dicts(exact)
        pattern = f"%{query.lstrip('@')}%"
        rows = fetch_all(
            self.conn,
            """
            SELECT * FROM chats
            WHERE title LIKE ? OR username LIKE ? OR phone LIKE ?
            ORDER BY title COLLATE NOCASE
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        )
        return row_dicts(rows)

    def max_message_id(self, chat_id: int) -> int:
        row = fetch_one(
            self.conn,
            "SELECT MAX(message_id) AS max_id FROM messages WHERE chat_id=?",
            (chat_id,),
        )
        return row_int(row, "max_id") if row is not None else 0

    def messages(
        self,
        *,
        chat_id: int | None = None,
        limit: int = 50,
        before: str | None = None,
    ) -> list[dict[str, SQLiteValue]]:
        sql = "SELECT * FROM messages"
        params: list[SQLiteValue] = []
        clauses: list[str] = []
        if chat_id is not None:
            clauses.append("chat_id=?")
            params.append(chat_id)
        if before:
            clauses.append("date < ?")
            params.append(before)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY date DESC, message_id DESC LIMIT ?"
        params.append(limit)
        return row_dicts(fetch_all(self.conn, sql, params))

    def message(self, chat_id: int, message_id: int) -> dict[str, SQLiteValue] | None:
        row = fetch_one(
            self.conn,
            "SELECT * FROM messages WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        )
        return optional_row_dict(row)

    def search_messages(
        self,
        query: str,
        *,
        chat_id: int | None = None,
        limit: int = 50,
        raw_fts: bool = False,
    ) -> list[dict[str, SQLiteValue]]:
        match = query if raw_fts else quote_fts_phrase(query)
        params: list[SQLiteValue] = [match]
        where = "messages_fts MATCH ?"
        if chat_id is not None:
            where += " AND m.chat_id=?"
            params.append(chat_id)
        params.append(limit)
        rows = fetch_all(
            self.conn,
            f"""
            SELECT
              m.*,
              c.title AS stored_chat_title,
              bm25(messages_fts) AS rank
            FROM messages_fts
            JOIN messages AS m ON m.id = messages_fts.rowid
            LEFT JOIN chats AS c ON c.chat_id = m.chat_id
            WHERE {where}
            ORDER BY rank, m.date DESC
            LIMIT ?
            """,
            params,
        )
        return row_dicts(rows)

    def stats(self) -> JsonObject:
        chat_count = row_int(required_row(fetch_one(self.conn, "SELECT COUNT(*) AS n FROM chats")), "n")
        message_count = row_int(required_row(fetch_one(self.conn, "SELECT COUNT(*) AS n FROM messages")), "n")
        oldest = optional_row_dict(fetch_one(self.conn, "SELECT MIN(date) AS d FROM messages")) or {}
        newest = optional_row_dict(fetch_one(self.conn, "SELECT MAX(date) AS d FROM messages")) or {}
        size = self.path.stat().st_size if self.path.exists() else 0
        return {
            "path": str(self.path),
            "size_bytes": size,
            "chats": chat_count,
            "messages": message_count,
            "oldest_message": oldest.get("d"),
            "newest_message": newest.get("d"),
        }

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise CliError("Store is open in read-only mode.")


def rows_to_public(rows: Iterable[dict[str, SQLiteValue]]) -> list[JsonObject]:
    return [public_row(row) for row in rows]


def public_row(row: dict[str, SQLiteValue]) -> JsonObject:
    cleaned = dict(row)
    raw = cleaned.pop("raw_json", None)
    public = {key: json_value(value) for key, value in cleaned.items()}
    if raw:
        public["raw"] = json_value(raw_json_value(raw))
    return public


def quote_fts_phrase(query: str) -> str:
    escaped = query.replace('"', '""').strip()
    return f'"{escaped}"'
