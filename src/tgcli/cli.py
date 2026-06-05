from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import (
    RuntimeConfig,
    api_credentials,
    build_runtime,
    check_private_permissions,
    default_store_dir,
    load_account_config,
    save_account_config,
)
from .errors import CliError
from .output import emit_object, emit_qr_login, emit_rows, eprint
from .store import Store, public_row, rows_to_public
from .telegram import (
    auth_status,
    can_post_story,
    list_contacts,
    list_live_chats,
    list_live_messages,
    login,
    logout,
    post_story_photo,
    qr_login,
    run,
    search_live_messages,
    send_file,
    send_text,
    story_targets,
    sync_dialogs,
)


CHAT_COLUMNS = [
    ("chat_id", "CHAT_ID", 20),
    ("kind", "KIND", 12),
    ("title", "TITLE", 36),
    ("username", "USERNAME", 24),
    ("unread_count", "UNREAD", 8),
]

MESSAGE_COLUMNS = [
    ("date", "DATE", 24),
    ("chat_title", "CHAT", 28),
    ("sender_name", "SENDER", 24),
    ("message_id", "MSG_ID", 10),
    ("text", "TEXT", 80),
]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = build_runtime(args)
    try:
        return dispatch(args, runtime)
    except KeyboardInterrupt:
        eprint("Interrupted.")
        return 130
    except CliError as exc:
        eprint(f"tgcli: {exc}")
        return 1


def dispatch(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    command = args.command
    if command == "auth":
        return dispatch_auth(args, runtime)
    if command == "sync":
        result = run(sync_dialogs(runtime, limit=args.limit, per_chat=args.per_chat, chat=args.chat, follow=args.follow))
        emit_object(result, json_output=runtime.json_output)
        return 0
    if command == "chats":
        return dispatch_chats(args, runtime)
    if command == "messages":
        return dispatch_messages(args, runtime)
    if command == "send":
        return dispatch_send(args, runtime)
    if command == "stories":
        return dispatch_stories(args, runtime)
    if command == "contacts":
        return dispatch_contacts(args, runtime)
    if command == "store":
        return dispatch_store(args, runtime)
    if command == "doctor":
        return dispatch_doctor(args, runtime)
    if command == "smoke-test":
        return dispatch_smoke_test(args, runtime)
    if command == "docs":
        print("https://github.com/openclaw/wacli")
        print("https://docs.telethon.dev/")
        print("https://core.telegram.org/api/obtaining_api_id")
        print("https://core.telegram.org/api/stories")
        print("https://core.telegram.org/method/stories.sendStory")
        return 0
    if command == "version":
        print(f"tgcli {__version__}")
        return 0
    raise CliError(f"Unknown command: {command}")


def dispatch_auth(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.auth_command
    if sub == "login":
        if should_use_qr_login(args):
            return dispatch_qr_login(args, runtime)
        if runtime.read_only:
            raise CliError("Refusing to authenticate in read-only mode.")
        config = load_account_config(runtime)
        api_id, api_hash = credentials_for_login(runtime, args)
        phone = args.phone or config.get("phone")
        save_account_config(runtime, {"api_id": api_id, "api_hash": api_hash, "phone": phone})
        result = run(login(runtime, api_id=api_id, api_hash=api_hash, phone=phone, code=args.code))
        if phone is None and result.get("phone"):
            config = load_account_config(runtime)
            config["phone"] = result["phone"]
            save_account_config(runtime, config)
        emit_object(result, json_output=runtime.json_output)
        return 0
    if sub == "qr-login":
        return dispatch_qr_login(args, runtime)
    if sub == "status":
        result = run(auth_status(runtime))
        emit_object(result, json_output=runtime.json_output)
        return 0
    if sub == "logout":
        result = run(logout(runtime))
        emit_object(result, json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown auth command: {sub}")


def dispatch_qr_login(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    if runtime.json_output:
        raise CliError("QR login is interactive and cannot render a QR code with --json.")
    api_id, api_hash = credentials_for_login(runtime, args)
    config = load_account_config(runtime)
    config.update({"api_id": api_id, "api_hash": api_hash})
    save_account_config(runtime, config)
    result = run(
        qr_login(
            runtime,
            api_id=api_id,
            api_hash=api_hash,
            timeout=args.timeout,
            on_qr=lambda url, expires, attempt: emit_qr_login(
                url,
                expires=expires,
                attempt=attempt,
                show_url=args.show_url,
            ),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def should_use_qr_login(args: argparse.Namespace) -> bool:
    return not args.phone and not args.code


def dispatch_chats(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.chats_command
    if sub == "list":
        if args.live:
            rows = run(list_live_chats(runtime, limit=args.limit, query=args.query))
        else:
            with Store(runtime.db_path, read_only=True) as store:
                rows = [public_row(row) for row in store.chats(query=args.query, limit=args.limit)]
        emit_rows(rows, CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
        return 0
    if sub == "show":
        chat_id = parse_int(args.chat_id, "chat_id")
        with Store(runtime.db_path, read_only=True) as store:
            row = store.chat(chat_id)
        if row is None:
            raise CliError(f"Unknown chat in local store: {chat_id}")
        emit_object(public_row(row), json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown chats command: {sub}")


def dispatch_messages(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.messages_command
    if sub == "list":
        if args.live:
            if not args.chat:
                raise CliError("`messages list --live` requires --chat.")
            rows = run(list_live_messages(runtime, chat=args.chat, limit=args.limit))
        else:
            chat_id = parse_int(args.chat, "chat") if args.chat else None
            with Store(runtime.db_path, read_only=True) as store:
                rows = rows_to_public(store.messages(chat_id=chat_id, limit=args.limit))
        emit_rows(rows, MESSAGE_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
        return 0
    if sub == "search":
        if args.live:
            rows = run(search_live_messages(runtime, query=args.query, chat=args.chat, limit=args.limit))
        else:
            chat_id = parse_int(args.chat, "chat") if args.chat else None
            with Store(runtime.db_path, read_only=True) as store:
                rows = rows_to_public(
                    store.search_messages(args.query, chat_id=chat_id, limit=args.limit, raw_fts=args.raw_fts)
                )
        emit_rows(rows, MESSAGE_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
        return 0
    if sub == "show":
        chat_id = parse_int(args.chat, "chat")
        message_id = parse_int(args.message_id, "message_id")
        with Store(runtime.db_path, read_only=True) as store:
            row = store.message(chat_id, message_id)
        if row is None:
            raise CliError(f"Unknown local message: chat={chat_id} message={message_id}")
        emit_object(public_row(row), json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown messages command: {sub}")


def dispatch_send(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.send_command
    if sub == "text":
        result = run(send_text(runtime, to=args.to, message=args.message, reply_to=args.reply_to))
        emit_object(result, json_output=runtime.json_output)
        return 0
    if sub == "file":
        result = run(
            send_file(
                runtime,
                to=args.to,
                file_path=Path(args.file).expanduser(),
                caption=args.caption,
                reply_to=args.reply_to,
            )
        )
        emit_object(result, json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown send command: {sub}")


def dispatch_stories(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.stories_command
    if sub == "can-post":
        result = run(can_post_story(runtime, as_peer=args.as_peer))
        emit_object(result, json_output=runtime.json_output)
        return 0 if result.get("can_post") else 2
    if sub == "targets":
        rows = run(story_targets(runtime))
        emit_rows(rows, CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
        return 0
    if sub == "post":
        result = run(
            post_story_photo(
                runtime,
                as_peer=args.as_peer,
                file_path=Path(args.file).expanduser(),
                caption=args.caption,
                privacy=args.privacy,
                period_hours=args.period_hours,
                pinned=args.pinned,
                noforwards=args.no_forwards,
            )
        )
        emit_object(result, json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown stories command: {sub}")


def dispatch_contacts(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.contacts_command
    if sub == "list":
        rows = run(list_contacts(runtime, limit=args.limit))
        emit_rows(rows, CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
        return 0
    raise CliError(f"Unknown contacts command: {sub}")


def dispatch_store(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    sub = args.store_command
    if sub == "stats":
        with Store(runtime.db_path, read_only=True) as store:
            emit_object(store.stats(), json_output=runtime.json_output)
        return 0
    raise CliError(f"Unknown store command: {sub}")


def dispatch_doctor(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    rows: list[dict[str, Any]] = []
    rows.append({"check": "store_dir", "ok": runtime.store_dir.exists(), "detail": str(runtime.store_dir)})
    rows.append({"check": "account_dir", "ok": runtime.account_dir.exists(), "detail": str(runtime.account_dir)})
    config = load_account_config(runtime)
    has_creds = bool(config.get("api_id") and config.get("api_hash")) or api_env_present()
    rows.append({"check": "api_credentials", "ok": has_creds, "detail": "config or TGCLI_API_ID/TGCLI_API_HASH"})
    rows.append({"check": "session_file", "ok": runtime.session_path.exists(), "detail": str(runtime.session_path)})
    rows.append({"check": "store_db", "ok": runtime.db_path.exists(), "detail": str(runtime.db_path)})
    rows.append({"check": "sqlite_fts5", "ok": sqlite_has_fts5(), "detail": sqlite3.sqlite_version})
    if runtime.account_dir.exists():
        ok, detail = check_private_permissions(runtime.account_dir, 0o077)
        rows.append({"check": "account_dir_perms", "ok": ok, "detail": detail})
    if runtime.config_path.exists():
        ok, detail = check_private_permissions(runtime.config_path, 0o177)
        rows.append({"check": "config_file_perms", "ok": ok, "detail": detail})
    if runtime.session_path.exists():
        ok, detail = check_private_permissions(runtime.session_path, 0o177)
        rows.append({"check": "session_file_perms", "ok": ok, "detail": detail})
    if args.connect:
        try:
            status = run(auth_status(runtime))
            rows.append({"check": "telegram_connect", "ok": bool(status.get("authorized")), "detail": status.get("name") or status})
        except CliError as exc:
            rows.append({"check": "telegram_connect", "ok": False, "detail": str(exc)})
    emit_rows(
        rows,
        [("check", "CHECK", 24), ("ok", "OK", 8), ("detail", "DETAIL", 80)],
        json_output=runtime.json_output,
        full=runtime.full_output,
    )
    return 0


def dispatch_smoke_test(args: argparse.Namespace, runtime: RuntimeConfig) -> int:
    if runtime.read_only:
        raise CliError("Refusing to run smoke test in read-only mode because it sends and syncs.")
    token = args.token or f"tgclilivetest{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    message = f"tgcli live test {token}"
    sent = run(send_text(runtime, to="me", message=message, reply_to=None))
    sync = run(sync_dialogs(runtime, limit=1, per_chat=args.per_chat, chat="me", follow=False))
    with Store(runtime.db_path, read_only=True) as store:
        matches = rows_to_public(store.search_messages(token, limit=5))
    ok = any(token in row.get("text", "") for row in matches)
    emit_object(
        {
            "ok": ok,
            "token": token,
            "sent_chat_id": sent.get("chat_id"),
            "sent_message_id": sent.get("message_id"),
            "synced_messages": sync.get("messages"),
            "matches": len(matches),
            "store": sync.get("store"),
        },
        json_output=runtime.json_output,
    )
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgcli",
        description="Telegram CLI for macOS-first auth, local sync/search, and send workflows.",
    )
    parser.add_argument("--store", default=None, help=f"Store directory. Default: {default_store_dir()}")
    parser.add_argument("--account", default=None, help="Named account. Default: TGCLI_ACCOUNT or default.")
    parser.add_argument("--json", action="store_true", help="Emit JSON for scripts.")
    parser.add_argument("--full", action="store_true", help="Do not truncate table columns.")
    parser.add_argument("--read-only", action="store_true", help="Reject commands that intentionally write state.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    auth = subparsers.add_parser("auth", help="Login, inspect, or logout.")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_sub.add_parser("login", help="Login as a Telegram user account. Defaults to QR pairing.")
    auth_login.add_argument("--api-id", default=None, help="Telegram API ID from my.telegram.org.")
    auth_login.add_argument("--api-hash", default=None, help="Telegram API hash from my.telegram.org.")
    auth_login.add_argument("--phone", default=None, help="Use phone-code login with this phone number.")
    auth_login.add_argument("--code", default=None, help="Use phone-code login with this Telegram code.")
    auth_login.add_argument("--timeout", type=int, default=180, help="Total seconds to wait for QR approval.")
    auth_login.add_argument("--show-url", action="store_true", help="Also print the tg://login URL for QR login.")
    auth_qr_login = auth_sub.add_parser("qr-login", help="Login by scanning a Telegram QR code.")
    auth_qr_login.add_argument("--api-id", default=None, help="Telegram API ID from my.telegram.org.")
    auth_qr_login.add_argument("--api-hash", default=None, help="Telegram API hash from my.telegram.org.")
    auth_qr_login.add_argument("--timeout", type=int, default=180, help="Total seconds to wait for QR approval.")
    auth_qr_login.add_argument("--show-url", action="store_true", help="Also print the tg://login URL.")
    auth_sub.add_parser("status", help="Show authorization status.")
    auth_sub.add_parser("logout", help="Log out this tgcli Telegram session.")

    sync = subparsers.add_parser("sync", help="Mirror Telegram dialogs and messages into local SQLite.")
    sync.add_argument("--limit", type=int, default=100, help="Number of dialogs to scan.")
    sync.add_argument("--per-chat", type=int, default=200, help="Maximum new messages to fetch per chat.")
    sync.add_argument("--chat", default=None, help="Only sync one chat/user/channel.")
    sync.add_argument("--follow", action="store_true", help="Keep running and store new messages.")

    chats = subparsers.add_parser("chats", help="List or inspect synced chats.")
    chats_sub = chats.add_subparsers(dest="chats_command", required=True)
    chats_list = chats_sub.add_parser("list", help="List chats from local store or Telegram.")
    chats_list.add_argument("--limit", type=int, default=50)
    chats_list.add_argument("--query", default=None)
    chats_list.add_argument("--live", action="store_true", help="Read from Telegram instead of local store.")
    chats_show = chats_sub.add_parser("show", help="Show one local chat by chat_id.")
    chats_show.add_argument("chat_id")

    messages = subparsers.add_parser("messages", help="List, search, or show messages.")
    messages_sub = messages.add_subparsers(dest="messages_command", required=True)
    messages_list = messages_sub.add_parser("list", help="List messages from local store or live Telegram.")
    messages_list.add_argument("--chat", default=None, help="chat_id locally, or entity when --live.")
    messages_list.add_argument("--limit", type=int, default=50)
    messages_list.add_argument("--live", action="store_true")
    messages_search = messages_sub.add_parser("search", help="Search local SQLite FTS or live Telegram.")
    messages_search.add_argument("query")
    messages_search.add_argument("--chat", default=None, help="chat_id locally, or entity when --live.")
    messages_search.add_argument("--limit", type=int, default=50)
    messages_search.add_argument("--live", action="store_true")
    messages_search.add_argument("--raw-fts", action="store_true", help="Treat query as raw SQLite FTS5 syntax.")
    messages_show = messages_sub.add_parser("show", help="Show one local message.")
    messages_show.add_argument("--chat", required=True)
    messages_show.add_argument("message_id")

    send = subparsers.add_parser("send", help="Send Telegram messages.")
    send_sub = send.add_subparsers(dest="send_command", required=True)
    send_text_parser = send_sub.add_parser("text", help="Send a text message.")
    send_text_parser.add_argument("--to", required=True, help="@username, phone, chat_id, or synced chat name.")
    send_text_parser.add_argument("--message", required=True)
    send_text_parser.add_argument("--reply-to", type=int, default=None)
    send_file_parser = send_sub.add_parser("file", help="Send a file with optional caption.")
    send_file_parser.add_argument("--to", required=True)
    send_file_parser.add_argument("--file", required=True)
    send_file_parser.add_argument("--caption", default=None)
    send_file_parser.add_argument("--reply-to", type=int, default=None)

    stories = subparsers.add_parser("stories", help="Post Telegram Stories.")
    stories_sub = stories.add_subparsers(dest="stories_command", required=True)
    stories_can_post = stories_sub.add_parser("can-post", help="Check whether a user/channel can post stories.")
    stories_can_post.add_argument("--as", dest="as_peer", default="me", help="Peer to post as. Default: me.")
    stories_sub.add_parser("targets", help="List channels/supergroups where Telegram allows this account to post stories.")
    stories_post = stories_sub.add_parser("post", help="Post an image story with an optional caption.")
    stories_post.add_argument("--as", dest="as_peer", default="me", help="Peer to post as. Default: me.")
    stories_post.add_argument("--file", required=True, help="Image file to post as the story media.")
    stories_post.add_argument("--caption", default=None, help="Story caption.")
    stories_post.add_argument(
        "--privacy",
        choices=["contacts", "public", "close-friends"],
        default="contacts",
        help="Story audience. Default: contacts.",
    )
    stories_post.add_argument(
        "--period-hours",
        type=int,
        choices=[6, 12, 24, 48],
        default=24,
        help="Story lifetime in hours. 48 hours requires Telegram Premium.",
    )
    stories_post.add_argument("--pinned", action="store_true", help="Pin the story to the profile after it expires.")
    stories_post.add_argument("--no-forwards", action="store_true", help="Disable forwards, screenshots, and downloads.")

    contacts = subparsers.add_parser("contacts", help="List Telegram contacts.")
    contacts_sub = contacts.add_subparsers(dest="contacts_command", required=True)
    contacts_list = contacts_sub.add_parser("list", help="List contacts from Telegram.")
    contacts_list.add_argument("--limit", type=int, default=100)

    store = subparsers.add_parser("store", help="Inspect local state.")
    store_sub = store.add_subparsers(dest="store_command", required=True)
    store_sub.add_parser("stats", help="Show local store stats.")

    doctor = subparsers.add_parser("doctor", help="Run local diagnostics.")
    doctor.add_argument("--connect", action="store_true", help="Also connect to Telegram and check auth.")

    smoke = subparsers.add_parser("smoke-test", help="Send to Saved Messages, sync, and verify local search.")
    smoke.add_argument("--token", default=None, help="Custom token to send and search for.")
    smoke.add_argument("--per-chat", type=int, default=50, help="Messages to fetch from Saved Messages after sending.")

    subparsers.add_parser("docs", help="Print relevant docs links.")
    subparsers.add_parser("version", help="Print version.")
    return parser


def credentials_for_login(runtime: RuntimeConfig, args: argparse.Namespace) -> tuple[int, str]:
    if args.api_id and args.api_hash:
        return api_credentials(runtime, api_id=args.api_id, api_hash=args.api_hash)
    try:
        return api_credentials(runtime, api_id=args.api_id, api_hash=args.api_hash)
    except CliError:
        api_id = args.api_id or input("Telegram API ID (from my.telegram.org): ").strip()
        api_hash = args.api_hash or input("Telegram API hash: ").strip()
        return api_credentials(runtime, api_id=api_id, api_hash=api_hash)


def parse_int(value: str, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CliError(f"{label} must be an integer for local-store commands. Use --live for names/usernames.") from exc


def api_env_present() -> bool:
    import os

    return bool((os.environ.get("TGCLI_API_ID") or os.environ.get("TELEGRAM_API_ID")) and (os.environ.get("TGCLI_API_HASH") or os.environ.get("TELEGRAM_API_HASH")))


def sqlite_has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE VIRTUAL TABLE f USING fts5(x)")
        conn.close()
        return True
    except sqlite3.Error:
        return False


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
