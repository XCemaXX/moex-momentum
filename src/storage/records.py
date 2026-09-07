"""Atomic read/write: write to `*.tmp`, then os.replace.

After a network blip / Ctrl-C the on-disk file is either the old version or
the new one in full — never a half-write. Concurrent CLI invocations on the
same file are not supported (single-process).
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_json_atomic(path: Path, obj: Any, *, sort_keys: bool = True) -> None:
    """Pretty JSON with a trailing newline.

    `sort_keys=False` preserves dataclass field order in reports meant to be read
    by a human; committed files use the sorted form.
    """
    body = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=sort_keys)
    write_text_atomic(path, body + "\n")


def write_records_atomic(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    fieldnames: Sequence[str],
) -> int:
    """Write records to CSV with explicit fieldnames. Always emits header.

    Missing keys fall to `''`; extra keys raise (default DictWriter behavior).
    Caller controls column order via `fieldnames`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with tmp.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), restval="", lineterminator="\n")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)
            count += 1
    os.replace(tmp, path)
    return count


def read_records(
    path: Path,
    *,
    casts: Mapping[str, Callable[[str], Any]] | None = None,
) -> list[dict[str, Any]]:
    """Read CSV with header. Empty string for a casted field becomes None.

    Fields not in `casts` stay as strings. Caller owns the type schema.
    Returns [] if path does not exist.
    """
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        casts = casts or {}
        for row in reader:
            rec: dict[str, Any] = {}
            for k, v in row.items():
                if k in casts:
                    rec[k] = casts[k](v) if v != "" else None
                else:
                    rec[k] = v
            out.append(rec)
    return out
