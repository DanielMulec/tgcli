from __future__ import annotations

import sys

from .cli_dispatch import dispatch, should_use_qr_login
from .cli_parser import build_parser
from .config import build_runtime
from .errors import CliError
from .output import eprint

__all__ = ["build_parser", "main", "should_use_qr_login"]


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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
