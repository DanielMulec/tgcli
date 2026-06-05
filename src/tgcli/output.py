from __future__ import annotations

import json
import sys
from datetime import date, datetime
from io import StringIO
from typing import Any, Iterable


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def emit_json(payload: Any) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, default=json_default)
    sys.stdout.write("\n")


def truncate(value: Any, width: int, full: bool) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ")
    if full or len(text) <= width:
        return text
    if width <= 3:
        return "." * max(width, 0)
    return text[: width - 3] + "..."


def emit_table(rows: Iterable[dict[str, Any]], columns: list[tuple[str, str, int]], *, full: bool) -> None:
    materialized = list(rows)
    if not materialized:
        return
    widths: list[int] = []
    for key, header, max_width in columns:
        width = len(header)
        for row in materialized:
            width = max(width, len(truncate(row.get(key), max_width, full)))
        widths.append(width if full else min(width, max_width))

    header_line = "  ".join(header.ljust(widths[i]) for i, (_, header, _) in enumerate(columns))
    sep_line = "  ".join("-" * widths[i] for i in range(len(columns)))
    print(header_line)
    print(sep_line)
    for row in materialized:
        parts = []
        for i, (key, _, max_width) in enumerate(columns):
            parts.append(truncate(row.get(key), max_width, full).ljust(widths[i]))
        print("  ".join(parts))


def emit_rows(
    rows: Iterable[dict[str, Any]],
    columns: list[tuple[str, str, int]],
    *,
    json_output: bool,
    full: bool,
    meta: dict[str, Any] | None = None,
) -> None:
    materialized = list(rows)
    if json_output:
        payload: dict[str, Any] = {"data": materialized}
        if meta:
            payload["meta"] = meta
        emit_json(payload)
        return
    emit_table(materialized, columns, full=full)


def emit_object(data: dict[str, Any], *, json_output: bool) -> None:
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
