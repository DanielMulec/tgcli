from __future__ import annotations

import json
import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import CliError


CONFIG_FILE = "config.json"
SESSION_FILE = "tgcli.session"
DB_FILE = "tgcli.db"


@dataclass(frozen=True)
class RuntimeConfig:
    store_dir: Path
    account: str
    account_dir: Path
    json_output: bool
    full_output: bool
    read_only: bool

    @property
    def config_path(self) -> Path:
        return self.account_dir / CONFIG_FILE

    @property
    def session_path(self) -> Path:
        return self.account_dir / SESSION_FILE

    @property
    def db_path(self) -> Path:
        return self.account_dir / DB_FILE


def truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_store_dir() -> Path:
    override = os.environ.get("TGCLI_STORE_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_STATE_HOME")
        return Path(xdg).expanduser() / "tgcli" if xdg else Path.home() / ".local/state/tgcli"
    return Path.home() / ".tgcli"


def account_dir(store_dir: Path, account: str) -> Path:
    clean = account.strip() or "default"
    if clean == "default":
        return store_dir
    if "/" in clean or clean in {".", ".."}:
        raise CliError("Account names cannot contain slashes or be '.'/'..'.")
    return store_dir / "accounts" / clean


def build_runtime(args: Any) -> RuntimeConfig:
    store = Path(args.store).expanduser() if args.store else default_store_dir()
    account = args.account or os.environ.get("TGCLI_ACCOUNT") or "default"
    return RuntimeConfig(
        store_dir=store,
        account=account,
        account_dir=account_dir(store, account),
        json_output=bool(args.json),
        full_output=bool(args.full),
        read_only=bool(args.read_only) or truthy(os.environ.get("TGCLI_READONLY")),
    )


def ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except PermissionError:
        raise CliError(f"Cannot set private permissions on {path}.")


def ensure_parent(path: Path) -> None:
    ensure_private_dir(path.parent)


def chmod_private_file(path: Path) -> None:
    if path.exists():
        try:
            path.chmod(0o600)
        except PermissionError:
            raise CliError(f"Cannot set private permissions on {path}.")


def check_private_permissions(path: Path, expected_mask: int) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & expected_mask:
        return False, oct(mode)
    return True, oct(mode)


def load_account_config(runtime: RuntimeConfig) -> dict[str, Any]:
    if not runtime.config_path.exists():
        return {}
    try:
        return json.loads(runtime.config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CliError(f"Invalid config JSON at {runtime.config_path}: {exc}") from exc


def save_account_config(runtime: RuntimeConfig, config: dict[str, Any]) -> None:
    if runtime.read_only:
        raise CliError("Refusing to write account config in read-only mode.")
    ensure_private_dir(runtime.account_dir)
    tmp = runtime.config_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(runtime.config_path)
    chmod_private_file(runtime.config_path)


def api_credentials(
    runtime: RuntimeConfig,
    *,
    api_id: str | int | None = None,
    api_hash: str | None = None,
) -> tuple[int, str]:
    config = load_account_config(runtime)
    raw_id = (
        api_id
        or os.environ.get("TGCLI_API_ID")
        or os.environ.get("TELEGRAM_API_ID")
        or config.get("api_id")
    )
    raw_hash = (
        api_hash
        or os.environ.get("TGCLI_API_HASH")
        or os.environ.get("TELEGRAM_API_HASH")
        or config.get("api_hash")
    )
    if not raw_id or not raw_hash:
        raise CliError(
            "Missing Telegram API credentials. Run `tgcli auth login --api-id ID --api-hash HASH`, "
            "or set TGCLI_API_ID/TGCLI_API_HASH. Create them at https://my.telegram.org."
        )
    try:
        parsed_id = int(raw_id)
    except (TypeError, ValueError) as exc:
        raise CliError("Telegram API ID must be an integer.") from exc
    return parsed_id, str(raw_hash)
