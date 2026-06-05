from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .cli_helpers import DOCTOR_COLUMNS, api_env_present, arg_bool, arg_int, arg_optional_str, sqlite_has_fts5
from .config import RuntimeConfig, check_private_permissions, load_account_config
from .errors import CliError
from .output import emit_object, emit_rows
from .store import Store, rows_to_public
from .telegram import auth_status, run, send_text, sync_dialogs
from .types import JsonObject, JsonRows


def dispatch_doctor(args: object, runtime: RuntimeConfig) -> int:
    rows = local_check_rows(runtime)
    add_permission_checks(rows, runtime)
    if arg_bool(args, "connect"):
        rows.append(telegram_connection_check(runtime))
    emit_rows(rows, DOCTOR_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def local_check_rows(runtime: RuntimeConfig) -> JsonRows:
    config = load_account_config(runtime)
    has_credentials = bool(config.get("api_id") and config.get("api_hash")) or api_env_present()
    return [
        {"check": "store_dir", "ok": runtime.store_dir.exists(), "detail": str(runtime.store_dir)},
        {"check": "account_dir", "ok": runtime.account_dir.exists(), "detail": str(runtime.account_dir)},
        {"check": "api_credentials", "ok": has_credentials, "detail": "config or TGCLI_API_ID/TGCLI_API_HASH"},
        {"check": "session_file", "ok": runtime.session_path.exists(), "detail": str(runtime.session_path)},
        {"check": "store_db", "ok": runtime.db_path.exists(), "detail": str(runtime.db_path)},
        {"check": "sqlite_fts5", "ok": sqlite_has_fts5(), "detail": "available"},
    ]


def add_permission_checks(rows: JsonRows, runtime: RuntimeConfig) -> None:
    add_permission_check(rows, "account_dir_perms", runtime.account_dir, 0o077)
    add_permission_check(rows, "config_file_perms", runtime.config_path, 0o177)
    add_permission_check(rows, "session_file_perms", runtime.session_path, 0o177)


def add_permission_check(rows: JsonRows, name: str, path: Path, mask: int) -> None:
    if not path.exists():
        return
    ok, detail = check_private_permissions(path, mask)
    rows.append({"check": name, "ok": ok, "detail": detail})


def telegram_connection_check(runtime: RuntimeConfig) -> JsonObject:
    try:
        status = run(auth_status(runtime))
    except CliError as exc:
        return {"check": "telegram_connect", "ok": False, "detail": str(exc)}
    detail = status.get("name") or str(status)
    return {"check": "telegram_connect", "ok": bool(status.get("authorized")), "detail": detail}


def dispatch_smoke_test(args: object, runtime: RuntimeConfig) -> int:
    if runtime.read_only:
        raise CliError("Refusing to run smoke test in read-only mode because it sends and syncs.")
    token = arg_optional_str(args, "token") or live_test_token()
    sent = run(send_text(runtime, to="me", message=f"tgcli live test {token}", reply_to=None))
    sync = run(sync_dialogs(runtime, limit=1, per_chat=arg_int(args, "per_chat"), chat="me", follow=False))
    matches = local_smoke_matches(runtime, token)
    ok = any(token in str(row.get("text", "")) for row in matches)
    emit_object(smoke_result(ok, token, sent, sync, matches), json_output=runtime.json_output)
    return 0 if ok else 2


def live_test_token() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"tgclilivetest{timestamp}"


def local_smoke_matches(runtime: RuntimeConfig, token: str) -> JsonRows:
    with Store(runtime.db_path, read_only=True) as store:
        return rows_to_public(store.search_messages(token, limit=5))


def smoke_result(ok: bool, token: str, sent: JsonObject, sync: JsonObject, matches: JsonRows) -> JsonObject:
    return {
        "ok": ok,
        "token": token,
        "sent_chat_id": sent.get("chat_id"),
        "sent_message_id": sent.get("message_id"),
        "synced_messages": sync.get("messages"),
        "matches": len(matches),
        "store": sync.get("store"),
    }
