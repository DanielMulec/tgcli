from __future__ import annotations

import asyncio
import platform
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TypeVar

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError

from . import __version__
from .config import RuntimeConfig, api_credentials, chmod_private_file, ensure_private_dir
from .errors import CliError

Result = TypeVar("Result")


def make_client(runtime: RuntimeConfig, *, api_id: int, api_hash: str) -> TelegramClient:
    if runtime.read_only and not runtime.account_dir.exists():
        raise CliError(f"Account directory does not exist in read-only mode: {runtime.account_dir}")
    if not runtime.read_only:
        ensure_private_dir(runtime.account_dir)
    return TelegramClient(
        str(runtime.session_path),
        api_id,
        api_hash,
        device_model="tgcli",
        system_version=platform.platform(),
        app_version=__version__,
    )


@asynccontextmanager
async def connected_client(runtime: RuntimeConfig) -> AsyncIterator[TelegramClient]:
    client = configured_client(runtime)
    await client.connect()
    try:
        await require_authorized(client)
        yield client
    except FloodWaitError as exc:
        raise CliError(f"Telegram rate-limited this request. Retry after {exc.seconds} seconds.") from exc
    except RPCError as exc:
        raise CliError(f"Telegram API error: {exc}") from exc
    finally:
        await client.disconnect()
        if not runtime.read_only:
            chmod_private_file(Path(str(runtime.session_path)))


def configured_client(runtime: RuntimeConfig) -> TelegramClient:
    api_id, api_hash = api_credentials(runtime)
    if runtime.read_only and not runtime.session_path.exists():
        raise CliError(f"Session file does not exist in read-only mode: {runtime.session_path}")
    return make_client(runtime, api_id=api_id, api_hash=api_hash)


async def require_authorized(client: TelegramClient) -> None:
    if not await client.is_user_authorized():
        raise CliError("Not authenticated. Run `tgcli auth qr-login` or `tgcli auth login` first.")


def run(coroutine: Coroutine[object, object, Result]) -> Result:
    return asyncio.run(coroutine)
