from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import __version__
from .cli_health import dispatch_doctor, dispatch_smoke_test
from .cli_helpers import (
    CHAT_COLUMNS,
    MESSAGE_COLUMNS,
    arg_bool,
    arg_int,
    arg_optional_int,
    arg_optional_str,
    arg_str,
    credentials_for_login,
    parse_int,
)
from .config import RuntimeConfig, load_account_config, save_account_config
from .errors import CliError
from .output import emit_object, emit_qr_login, emit_rows
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
    story_history,
    story_limits,
    story_targets,
    sync_dialogs,
)

CommandHandler = Callable[[object, RuntimeConfig], int]


def dispatch(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {
        "auth": dispatch_auth,
        "sync": dispatch_sync,
        "chats": dispatch_chats,
        "messages": dispatch_messages,
        "send": dispatch_send,
        "stories": dispatch_stories,
        "contacts": dispatch_contacts,
        "store": dispatch_store,
        "doctor": dispatch_doctor,
        "smoke-test": dispatch_smoke_test,
        "docs": dispatch_docs,
        "version": dispatch_version,
    }
    command = arg_str(args, "command")
    handler = handlers.get(command)
    if handler is None:
        raise CliError(f"Unknown command: {command}")
    return handler(args, runtime)


def dispatch_sync(args: object, runtime: RuntimeConfig) -> int:
    result = run(
        sync_dialogs(
            runtime,
            limit=arg_int(args, "limit"),
            per_chat=arg_int(args, "per_chat"),
            chat=arg_optional_str(args, "chat"),
            follow=arg_bool(args, "follow"),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_auth(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {
        "login": dispatch_login,
        "qr-login": dispatch_qr_login,
        "status": dispatch_auth_status,
        "logout": dispatch_logout,
    }
    subcommand = arg_str(args, "auth_command")
    handler = handlers.get(subcommand)
    if handler is None:
        raise CliError(f"Unknown auth command: {subcommand}")
    return handler(args, runtime)


def dispatch_login(args: object, runtime: RuntimeConfig) -> int:
    if should_use_qr_login(args):
        return dispatch_qr_login(args, runtime)
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    config = load_account_config(runtime)
    api_id, api_hash = credentials_for_login(runtime, args)
    phone = arg_optional_str(args, "phone") or config.get("phone")
    result = run(
        login(
            runtime,
            api_id=api_id,
            api_hash=api_hash,
            phone=str(phone) if phone else None,
            code=arg_optional_str(args, "code"),
        )
    )
    save_account_config(runtime, {"api_id": api_id, "api_hash": api_hash, "phone": result.get("phone") or phone})
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_qr_login(args: object, runtime: RuntimeConfig) -> int:
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
            timeout=arg_int(args, "timeout"),
            on_qr=lambda url, expires, attempt: emit_qr_login(
                url,
                expires=expires,
                attempt=attempt,
                show_url=arg_bool(args, "show_url"),
            ),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def should_use_qr_login(args: object) -> bool:
    return not arg_optional_str(args, "phone") and not arg_optional_str(args, "code")


def dispatch_auth_status(args: object, runtime: RuntimeConfig) -> int:
    emit_object(run(auth_status(runtime)), json_output=runtime.json_output)
    return 0


def dispatch_logout(args: object, runtime: RuntimeConfig) -> int:
    emit_object(run(logout(runtime)), json_output=runtime.json_output)
    return 0


def dispatch_chats(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {"list": dispatch_chat_list, "show": dispatch_chat_show}
    subcommand = arg_str(args, "chats_command")
    handler = handlers.get(subcommand)
    if handler is None:
        raise CliError(f"Unknown chats command: {subcommand}")
    return handler(args, runtime)


def dispatch_chat_list(args: object, runtime: RuntimeConfig) -> int:
    if arg_bool(args, "live"):
        rows = run(list_live_chats(runtime, limit=arg_int(args, "limit"), query=arg_optional_str(args, "query")))
    else:
        with Store(runtime.db_path, read_only=True) as store:
            rows = [
                public_row(row)
                for row in store.chats(query=arg_optional_str(args, "query"), limit=arg_int(args, "limit"))
            ]
    emit_rows(rows, CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def dispatch_chat_show(args: object, runtime: RuntimeConfig) -> int:
    chat_id = parse_int(arg_str(args, "chat_id"), "chat_id")
    with Store(runtime.db_path, read_only=True) as store:
        row = store.chat(chat_id)
    if row is None:
        raise CliError(f"Unknown chat in local store: {chat_id}")
    emit_object(public_row(row), json_output=runtime.json_output)
    return 0


def dispatch_messages(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {
        "list": dispatch_message_list,
        "search": dispatch_message_search,
        "show": dispatch_message_show,
    }
    subcommand = arg_str(args, "messages_command")
    handler = handlers.get(subcommand)
    if handler is None:
        raise CliError(f"Unknown messages command: {subcommand}")
    return handler(args, runtime)


def dispatch_message_list(args: object, runtime: RuntimeConfig) -> int:
    chat = arg_optional_str(args, "chat")
    if arg_bool(args, "live"):
        rows = run(list_live_messages(runtime, chat=required_live_chat(chat), limit=arg_int(args, "limit")))
    else:
        chat_id = parse_int(chat, "chat") if chat else None
        with Store(runtime.db_path, read_only=True) as store:
            rows = rows_to_public(store.messages(chat_id=chat_id, limit=arg_int(args, "limit")))
    emit_rows(rows, MESSAGE_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def dispatch_message_search(args: object, runtime: RuntimeConfig) -> int:
    chat = arg_optional_str(args, "chat")
    if arg_bool(args, "live"):
        rows = run(search_live_messages(runtime, query=arg_str(args, "query"), chat=chat, limit=arg_int(args, "limit")))
    else:
        chat_id = parse_int(chat, "chat") if chat else None
        with Store(runtime.db_path, read_only=True) as store:
            rows = rows_to_public(
                store.search_messages(
                    arg_str(args, "query"),
                    chat_id=chat_id,
                    limit=arg_int(args, "limit"),
                    raw_fts=arg_bool(args, "raw_fts"),
                )
            )
    emit_rows(rows, MESSAGE_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def dispatch_message_show(args: object, runtime: RuntimeConfig) -> int:
    chat_id = parse_int(arg_str(args, "chat"), "chat")
    message_id = parse_int(arg_str(args, "message_id"), "message_id")
    with Store(runtime.db_path, read_only=True) as store:
        row = store.message(chat_id, message_id)
    if row is None:
        raise CliError(f"Unknown local message: chat={chat_id} message={message_id}")
    emit_object(public_row(row), json_output=runtime.json_output)
    return 0


def required_live_chat(chat: str | None) -> str:
    if chat:
        return chat
    raise CliError("`messages list --live` requires --chat.")


def dispatch_send(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {"text": dispatch_send_text, "file": dispatch_send_file}
    subcommand = arg_str(args, "send_command")
    handler = handlers.get(subcommand)
    if handler is None:
        raise CliError(f"Unknown send command: {subcommand}")
    return handler(args, runtime)


def dispatch_send_text(args: object, runtime: RuntimeConfig) -> int:
    result = run(
        send_text(
            runtime,
            to=arg_str(args, "to"),
            message=arg_str(args, "message"),
            reply_to=arg_optional_int(args, "reply_to"),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_send_file(args: object, runtime: RuntimeConfig) -> int:
    result = run(
        send_file(
            runtime,
            to=arg_str(args, "to"),
            file_path=Path(arg_str(args, "file")).expanduser(),
            caption=arg_optional_str(args, "caption"),
            reply_to=arg_optional_int(args, "reply_to"),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_stories(args: object, runtime: RuntimeConfig) -> int:
    handlers: dict[str, CommandHandler] = {
        "can-post": dispatch_story_can_post,
        "targets": dispatch_story_targets,
        "limits": dispatch_story_limits,
        "history": dispatch_story_history,
        "post": dispatch_story_post,
    }
    subcommand = arg_str(args, "stories_command")
    handler = handlers.get(subcommand)
    if handler is None:
        raise CliError(f"Unknown stories command: {subcommand}")
    return handler(args, runtime)


def dispatch_story_can_post(args: object, runtime: RuntimeConfig) -> int:
    result = run(can_post_story(runtime, as_peer=arg_str(args, "as_peer")))
    emit_object(result, json_output=runtime.json_output)
    return 0 if result.get("can_post") else 2


def dispatch_story_targets(args: object, runtime: RuntimeConfig) -> int:
    emit_rows(run(story_targets(runtime)), CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def dispatch_story_limits(args: object, runtime: RuntimeConfig) -> int:
    emit_object(run(story_limits(runtime, as_peer=arg_str(args, "as_peer"))), json_output=runtime.json_output)
    return 0


def dispatch_story_history(args: object, runtime: RuntimeConfig) -> int:
    result = run(story_history(runtime, as_peer=arg_str(args, "as_peer"), limit=arg_int(args, "limit")))
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_story_post(args: object, runtime: RuntimeConfig) -> int:
    result = run(
        post_story_photo(
            runtime,
            as_peer=arg_str(args, "as_peer"),
            file_path=Path(arg_str(args, "file")).expanduser(),
            caption=arg_optional_str(args, "caption"),
            privacy=arg_str(args, "privacy"),
            period_hours=arg_int(args, "period_hours"),
            pinned=arg_bool(args, "pinned"),
            noforwards=arg_bool(args, "no_forwards"),
        )
    )
    emit_object(result, json_output=runtime.json_output)
    return 0


def dispatch_contacts(args: object, runtime: RuntimeConfig) -> int:
    subcommand = arg_str(args, "contacts_command")
    if subcommand != "list":
        raise CliError(f"Unknown contacts command: {subcommand}")
    rows = run(list_contacts(runtime, limit=arg_int(args, "limit")))
    emit_rows(rows, CHAT_COLUMNS, json_output=runtime.json_output, full=runtime.full_output)
    return 0


def dispatch_store(args: object, runtime: RuntimeConfig) -> int:
    subcommand = arg_str(args, "store_command")
    if subcommand != "stats":
        raise CliError(f"Unknown store command: {subcommand}")
    with Store(runtime.db_path, read_only=True) as store:
        emit_object(store.stats(), json_output=runtime.json_output)
    return 0


def dispatch_docs(args: object, runtime: RuntimeConfig) -> int:
    print("https://github.com/openclaw/wacli")
    print("https://docs.telethon.dev/")
    print("https://core.telegram.org/api/obtaining_api_id")
    print("https://core.telegram.org/api/stories")
    print("https://core.telegram.org/method/stories.sendStory")
    return 0


def dispatch_version(args: object, runtime: RuntimeConfig) -> int:
    print(f"tgcli {__version__}")
    return 0
