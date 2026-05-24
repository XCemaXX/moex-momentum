"""Stdlib logging with key=value format on stderr."""

from __future__ import annotations

import logging
import sys


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def kv(**fields: object) -> str:
    """Format fields as `key=value key=value` for logs.

    Values with spaces or quotes are wrapped in quotes.
    """
    parts: list[str] = []
    for k, v in fields.items():
        s = str(v)
        if any(c in s for c in (" ", "=", '"')):
            s = '"' + s.replace('"', '\\"') + '"'
        parts.append(f"{k}={s}")
    return " ".join(parts)
