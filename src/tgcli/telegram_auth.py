from __future__ import annotations

import asyncio
import getpass
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

from .config import RuntimeConfig, api_credentials, chmod_private_file
from .errors import CliError
from .telegram_client import connected_client, make_client
from .telegram_mapping import me_to_dict
from .types import JsonObject


class SignInClient(Protocol):
    # Telethon is dynamic; protocols keep the untyped login edge narrow and testable.
    async def sign_in(
        self,
        *,
        phone: str | None = None,
        code: str | None = None,
        password: str | None = None,
    ) -> object: ...


class QRClient(SignInClient, Protocol):
    async def get_me(self) -> object: ...


class QRLoginToken(Protocol):
    url: str
    expires: datetime

    async def wait(self, *, timeout: float) -> object: ...

    async def recreate(self) -> None: ...


async def login(
    runtime: RuntimeConfig,
    *,
    api_id: int,
    api_hash: str,
    phone: str | None,
    code: str | None,
) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            return me_to_dict(await client.get_me())
        phone_number = required_phone(phone)
        await client.send_code_request(phone_number)
        await sign_in_with_code(client, phone_number, code)
        return me_to_dict(await client.get_me())
    finally:
        await client.disconnect()
        chmod_private_file(Path(str(runtime.session_path)))


def required_phone(phone: str | None) -> str:
    phone_number = phone or input("Telegram phone number (international format): ").strip()
    if not phone_number:
        raise CliError("Phone number is required.")
    return phone_number


async def sign_in_with_code(client: SignInClient, phone: str, code: str | None) -> None:
    login_code = code or input("Login code from Telegram: ").strip()
    try:
        await client.sign_in(phone=phone, code=login_code)
    except SessionPasswordNeededError:
        await sign_in_with_password(client)
    except PhoneCodeInvalidError as exc:
        raise CliError("Invalid Telegram login code.") from exc
    except PhoneCodeExpiredError as exc:
        raise CliError("Telegram login code expired. Run `tgcli auth login` again.") from exc


async def sign_in_with_password(client: SignInClient) -> None:
    password = getpass.getpass("Two-step verification password: ")
    try:
        await client.sign_in(password=password)
    except PasswordHashInvalidError as exc:
        raise CliError("Invalid two-step verification password.") from exc


async def qr_login(
    runtime: RuntimeConfig,
    *,
    api_id: int,
    api_hash: str,
    timeout: int,
    on_qr: Callable[[str, datetime, int], None],
) -> JsonObject:
    validate_qr_login(runtime, timeout)
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        if await client.is_user_authorized():
            return login_result(await client.get_me(), "existing_session")
        qr = cast(QRLoginToken, await client.qr_login())
        return await wait_for_qr_login(client, qr, timeout, on_qr)
    finally:
        await client.disconnect()
        chmod_private_file(Path(str(runtime.session_path)))


def validate_qr_login(runtime: RuntimeConfig, timeout: int) -> None:
    if runtime.read_only:
        raise CliError("Refusing to authenticate in read-only mode.")
    if timeout <= 0:
        raise CliError("QR login timeout must be greater than zero seconds.")


async def wait_for_qr_login(
    client: QRClient,
    qr: QRLoginToken,
    timeout: int,
    on_qr: Callable[[str, datetime, int], None],
) -> JsonObject:
    deadline = datetime.now(UTC).timestamp() + timeout
    attempt = 1
    while True:
        remaining = remaining_qr_seconds(deadline, qr)
        wait_task = asyncio.create_task(qr.wait(timeout=remaining))
        await asyncio.sleep(0)
        on_qr(str(qr.url), qr.expires, attempt)
        try:
            return login_result(await wait_task, "qr")
        except SessionPasswordNeededError:
            await sign_in_with_password(client)
            return login_result(await client.get_me(), "qr")
        except TimeoutError:
            attempt = await next_qr_attempt(qr, deadline, attempt)


def remaining_qr_seconds(deadline: float, qr: QRLoginToken) -> float:
    now = datetime.now(UTC)
    total_remaining = deadline - now.timestamp()
    if total_remaining <= 0:
        raise CliError("QR login timed out before Telegram approved the session.")
    token_remaining = max((qr.expires - now).total_seconds(), 1)
    return min(total_remaining, token_remaining)


async def next_qr_attempt(qr: QRLoginToken, deadline: float, attempt: int) -> int:
    if datetime.now(UTC).timestamp() >= deadline:
        raise CliError("QR login timed out before Telegram approved the session.")
    await qr.recreate()
    return attempt + 1


def login_result(me: object, method: str) -> JsonObject:
    result = me_to_dict(me)
    result["login_method"] = method
    return result


async def auth_status(runtime: RuntimeConfig) -> JsonObject:
    api_id, api_hash = api_credentials(runtime)
    if not runtime.session_path.exists():
        return {"authorized": False, "session": str(runtime.session_path)}
    client = make_client(runtime, api_id=api_id, api_hash=api_hash)
    await client.connect()
    try:
        authorized = await client.is_user_authorized()
        data: JsonObject = {"authorized": authorized, "session": str(runtime.session_path)}
        if authorized:
            data.update(me_to_dict(await client.get_me()))
        return data
    finally:
        await client.disconnect()


async def logout(runtime: RuntimeConfig) -> JsonObject:
    if runtime.read_only:
        raise CliError("Refusing to logout in read-only mode.")
    async with connected_client(runtime) as client:
        await client.log_out()
    return {"authorized": False, "session": str(runtime.session_path)}
