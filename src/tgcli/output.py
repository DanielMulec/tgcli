from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from datetime import date, datetime
from io import StringIO

from .types import JsonObject, JsonValue, TableColumn


def json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def emit_json(payload: JsonValue) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, default=json_default)
    sys.stdout.write("\n")


def truncate(value: object, width: int, full: bool) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    if full or len(text) <= width:
        return text
    if width <= 3:
        return "." * max(width, 0)
    return text[: width - 3] + "..."


def emit_table(rows: Iterable[JsonObject], columns: list[TableColumn], *, full: bool) -> None:
    materialized = list(rows)
    if not materialized:
        return
    widths = table_widths(materialized, columns, full=full)
    print(table_header(columns, widths))
    print(table_separator(widths))
    for row in materialized:
        print(table_row(row, columns, widths, full=full))


def table_widths(rows: list[JsonObject], columns: list[TableColumn], *, full: bool) -> list[int]:
    return [column_width(rows, column, full=full) for column in columns]


def column_width(rows: list[JsonObject], column: TableColumn, *, full: bool) -> int:
    key, header, max_width = column
    content_width = max(len(truncate(row.get(key), max_width, full)) for row in rows)
    width = max(len(header), content_width)
    return width if full else min(width, max_width)


def table_header(columns: list[TableColumn], widths: list[int]) -> str:
    return "  ".join(header.ljust(widths[index]) for index, (_, header, _) in enumerate(columns))


def table_separator(widths: list[int]) -> str:
    return "  ".join("-" * width for width in widths)


def table_row(row: JsonObject, columns: list[TableColumn], widths: list[int], *, full: bool) -> str:
    parts = [
        truncate(row.get(key), max_width, full).ljust(widths[index])
        for index, (key, _, max_width) in enumerate(columns)
    ]
    return "  ".join(parts)


def emit_rows(
    rows: Iterable[JsonObject],
    columns: list[TableColumn],
    *,
    json_output: bool,
    full: bool,
    meta: JsonObject | None = None,
) -> None:
    materialized = list(rows)
    if json_output:
        payload: JsonObject = {"data": materialized}
        if meta:
            payload["meta"] = meta
        emit_json(payload)
        return
    emit_table(materialized, columns, full=full)


def emit_object(data: JsonObject, *, json_output: bool) -> None:
    if json_output:
        emit_json({"data": data})
        return
    for key, value in data.items():
        print(f"{key}: {value}")


def eprint(message: str) -> None:
    print(message, file=sys.stderr)


def terminal_qr(data: str) -> str:
    import qrcode

    qr = qrcode.QRCode(border=1)
    qr.add_data(data)
    qr.make(fit=True)
    output = StringIO()
    qr.print_ascii(out=output, tty=False, invert=True)
    return output.getvalue()


def emit_qr_login(url: str, *, expires: datetime, attempt: int, show_url: bool) -> None:
    print()
    print(f"Telegram QR login attempt {attempt}")
    print(f"Expires: {expires.isoformat()}")
    print("Scan with Telegram: Settings > Devices > Link Desktop Device")
    print()
    print(terminal_qr(url))
    if show_url:
        print(url)
    print("Waiting for approval...")
