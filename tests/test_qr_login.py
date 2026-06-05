import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pytest import MonkeyPatch

from tgcli.cli import build_parser, should_use_qr_login
from tgcli.config import RuntimeConfig
from tgcli.output import terminal_qr
from tgcli.telegram import qr_login


class FakeUser:
    id = 42
    first_name = "Ada"
    last_name = "Lovelace"
    username = "ada"
    phone = None
    bot = False


class FakeQR:
    url = "tg://login?token=test"
    expires = datetime.now(UTC) + timedelta(seconds=30)

    async def wait(self, timeout: float | None = None) -> FakeUser:
        return FakeUser()

    async def recreate(self) -> None:
        raise AssertionError("QR token should not be recreated on immediate success")


class FakeClient:
    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def is_user_authorized(self) -> bool:
        return False

    async def qr_login(self) -> FakeQR:
        return FakeQR()


def test_terminal_qr_renders_content() -> None:
    rendered = terminal_qr("tg://login?token=test")
    assert len(rendered.splitlines()) > 5


def test_auth_login_defaults_to_qr() -> None:
    args = build_parser().parse_args(["auth", "login"])
    assert should_use_qr_login(args)
    assert args.timeout == 180


def test_auth_login_uses_code_flow_when_phone_is_explicit() -> None:
    args = build_parser().parse_args(["auth", "login", "--phone", "+123"])
    assert not should_use_qr_login(args)


def test_smoke_test_parser_defaults() -> None:
    args = build_parser().parse_args(["smoke-test"])
    assert args.command == "smoke-test"
    assert args.per_chat == 50


def test_qr_login_success_path(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    runtime = RuntimeConfig(
        store_dir=tmp_path,
        account="default",
        account_dir=tmp_path,
        json_output=False,
        full_output=False,
        read_only=False,
    )
    seen: list[tuple[str, datetime, int]] = []

    monkeypatch.setattr("tgcli.telegram_auth.make_client", lambda *_args, **_kwargs: FakeClient())

    result = asyncio.run(
        qr_login(
            runtime,
            api_id=123,
            api_hash="hash",
            timeout=10,
            on_qr=lambda url, expires, attempt: seen.append((url, expires, attempt)),
        )
    )

    assert result["authorized"] is True
    assert result["login_method"] == "qr"
    assert result["username"] == "ada"
    assert seen[0][0] == "tg://login?token=test"
    assert seen[0][2] == 1
