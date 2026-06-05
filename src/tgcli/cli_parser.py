from __future__ import annotations

import argparse

from .config import default_store_dir

STORY_PRIVACY_CHOICES = ("contacts", "public", "close-friends")
STORY_PERIOD_CHOICES = (6, 12, 24, 48)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tgcli",
        description="Telegram CLI for macOS-first auth, local sync/search, and send workflows.",
    )
    add_global_options(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    add_auth_parser(subparsers)
    add_sync_parser(subparsers)
    add_chat_parser(subparsers)
    add_message_parser(subparsers)
    add_send_parser(subparsers)
    add_story_parser(subparsers)
    add_misc_parsers(subparsers)
    return parser


def add_global_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--store", default=None, help=f"Store directory. Default: {default_store_dir()}")
    parser.add_argument("--account", default=None, help="Named account. Default: TGCLI_ACCOUNT or default.")
    parser.add_argument("--json", action="store_true", help="Emit JSON for scripts.")
    parser.add_argument("--full", action="store_true", help="Do not truncate table columns.")
    parser.add_argument("--read-only", action="store_true", help="Reject commands that intentionally write state.")


def add_auth_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    auth = subparsers.add_parser("auth", help="Login, inspect, or logout.")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    auth_login = auth_sub.add_parser("login", help="Login as a Telegram user account. Defaults to QR pairing.")
    add_api_options(auth_login)
    auth_login.add_argument("--phone", default=None, help="Use phone-code login with this phone number.")
    auth_login.add_argument("--code", default=None, help="Use phone-code login with this Telegram code.")
    auth_login.add_argument("--timeout", type=int, default=180, help="Total seconds to wait for QR approval.")
    auth_login.add_argument("--show-url", action="store_true", help="Also print the tg://login URL for QR login.")
    auth_qr_login = auth_sub.add_parser("qr-login", help="Login by scanning a Telegram QR code.")
    add_api_options(auth_qr_login)
    auth_qr_login.add_argument("--timeout", type=int, default=180, help="Total seconds to wait for QR approval.")
    auth_qr_login.add_argument("--show-url", action="store_true", help="Also print the tg://login URL.")
    auth_sub.add_parser("status", help="Show authorization status.")
    auth_sub.add_parser("logout", help="Log out this tgcli Telegram session.")


def add_api_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-id", default=None, help="Telegram API ID from my.telegram.org.")
    parser.add_argument("--api-hash", default=None, help="Telegram API hash from my.telegram.org.")


def add_sync_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    sync = subparsers.add_parser("sync", help="Mirror Telegram dialogs and messages into local SQLite.")
    sync.add_argument("--limit", type=int, default=100, help="Number of dialogs to scan.")
    sync.add_argument("--per-chat", type=int, default=200, help="Maximum new messages to fetch per chat.")
    sync.add_argument("--chat", default=None, help="Only sync one chat/user/channel.")
    sync.add_argument("--follow", action="store_true", help="Keep running and store new messages.")


def add_chat_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    chats = subparsers.add_parser("chats", help="List or inspect synced chats.")
    chats_sub = chats.add_subparsers(dest="chats_command", required=True)
    chats_list = chats_sub.add_parser("list", help="List chats from local store or Telegram.")
    chats_list.add_argument("--limit", type=int, default=50)
    chats_list.add_argument("--query", default=None)
    chats_list.add_argument("--live", action="store_true", help="Read from Telegram instead of local store.")
    chats_show = chats_sub.add_parser("show", help="Show one local chat by chat_id.")
    chats_show.add_argument("chat_id")


def add_message_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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


def add_send_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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


def add_story_parser(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    stories = subparsers.add_parser("stories", help="Post Telegram Stories.")
    stories_sub = stories.add_subparsers(dest="stories_command", required=True)
    stories_can_post = stories_sub.add_parser("can-post", help="Check whether a user/channel can post stories.")
    stories_can_post.add_argument("--as", dest="as_peer", default="me", help="Peer to post as. Default: me.")
    stories_sub.add_parser(
        "targets",
        help="List channels/supergroups where Telegram allows this account to post stories.",
    )
    stories_limits = stories_sub.add_parser("limits", help="Show Telegram story limits and live posting eligibility.")
    stories_limits.add_argument("--as", dest="as_peer", default="me", help="Peer to check. Default: me.")
    stories_history = stories_sub.add_parser("history", help="Show active and archived story metadata.")
    stories_history.add_argument("--as", dest="as_peer", default="me", help="Peer to inspect. Default: me.")
    stories_history.add_argument("--limit", type=int, default=20, help="Archived stories to fetch. Default: 20.")
    stories_post = stories_sub.add_parser("post", help="Post an image story with an optional caption.")
    add_story_post_options(stories_post)


def add_story_post_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--as", dest="as_peer", default="me", help="Peer to post as. Default: me.")
    parser.add_argument("--file", required=True, help="Image file to post as the story media.")
    parser.add_argument("--caption", default=None, help="Story caption.")
    parser.add_argument(
        "--privacy",
        choices=STORY_PRIVACY_CHOICES,
        default="contacts",
        help="Story audience. Default: contacts.",
    )
    parser.add_argument(
        "--period-hours",
        type=int,
        choices=STORY_PERIOD_CHOICES,
        default=24,
        help="Story lifetime in hours. 48 hours requires Telegram Premium.",
    )
    parser.add_argument("--pinned", action="store_true", help="Pin the story to the profile after it expires.")
    parser.add_argument("--no-forwards", action="store_true", help="Disable forwards, screenshots, and downloads.")


def add_misc_parsers(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
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
