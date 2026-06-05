from __future__ import annotations

import json


def attribute(source: object, name: str, default: object = None) -> object:
    # Dynamic libraries expose runtime attributes; this is the only generic attribute escape hatch.
    return getattr(source, name, default)


def json_loads(text: str | bytes) -> object:
    return json.loads(text)  # type: ignore[misc]
