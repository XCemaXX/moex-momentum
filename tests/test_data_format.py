"""Format invariants over the committed data tree.

Unit tests exercise the writer on synthetic input; these check the files that are
actually in git. That gap is real: a schema widening drifted through 52 dividend
files unnoticed because nothing compared headers on disk against the schema.

`momentum/` is absent because it is gitignored, not committed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from storage.records import read_records, write_records_atomic
from storage.schemas import (
    DIV_CASTS,
    DIV_FIELDS,
    INDEX_CASTS,
    INDEX_FIELDS,
    PRICE_CASTS,
    PRICE_FIELDS,
    SPLIT_CASTS,
    SPLIT_FIELDS,
)
from tests.conftest import DATA_DIR

Schema = tuple[str, tuple[str, ...], Mapping[str, Callable[[str], object]], str]

# (directory, fields, casts, sort key)
SCHEMAS: tuple[Schema, ...] = (
    ("dividends", DIV_FIELDS, DIV_CASTS, "registry_close"),
    ("prices_iss", PRICE_FIELDS, PRICE_CASTS, "date"),
    ("splits", SPLIT_FIELDS, SPLIT_CASTS, "date"),
    ("indices", INDEX_FIELDS, INDEX_CASTS, "date"),
)

IDS = [s[0] for s in SCHEMAS]


def _files(directory: str) -> list[Path]:
    # `_`-prefixed files are curated journals, not schema rows.
    return sorted(p for p in (DATA_DIR / directory).glob("*.csv") if not p.name.startswith("_"))


@pytest.mark.parametrize("schema", SCHEMAS, ids=IDS)
def test_tree_is_not_empty(schema: Schema) -> None:
    """A moved or emptied directory must fail, not silently pass zero files."""
    directory, *_ = schema
    assert _files(directory), f"data/{directory}/ has no CSV — did the tree move?"


@pytest.mark.parametrize("schema", SCHEMAS, ids=IDS)
def test_header_matches_schema(schema: Schema) -> None:
    directory, fields, _, _ = schema
    want = ",".join(fields)
    bad = [
        p.name for p in _files(directory) if p.read_text(encoding="utf-8").split("\n", 1)[0] != want
    ]
    assert not bad, f"data/{directory}/: header differs from schema in {bad[:5]}"


@pytest.mark.parametrize("schema", SCHEMAS, ids=IDS)
def test_rows_are_sorted(schema: Schema) -> None:
    directory, _, casts, key = schema
    bad: list[str] = []
    for p in _files(directory):
        values = [str(r[key]) for r in read_records(p, casts=casts)]
        if values != sorted(values):
            bad.append(p.name)
    assert not bad, f"data/{directory}/: rows not sorted by {key} in {bad[:5]}"


@pytest.mark.parametrize("schema", SCHEMAS, ids=IDS)
def test_reserialisation_is_byte_identical(schema: Schema, tmp_path: Path) -> None:
    """Read → write must reproduce the file, or every touch churns the diff."""
    directory, fields, casts, _ = schema
    out = tmp_path / "roundtrip.csv"
    bad: list[str] = []
    for p in _files(directory):
        write_records_atomic(out, read_records(p, casts=casts), fieldnames=fields)
        if out.read_bytes() != p.read_bytes():
            bad.append(p.name)
    assert not bad, (
        f"data/{directory}/: re-serialisation differs for {bad[:5]} — "
        f"the next write to these files will churn the whole diff"
    )


@pytest.mark.parametrize("schema", SCHEMAS, ids=IDS)
def test_line_endings_are_lf(schema: Schema) -> None:
    directory, *_ = schema
    bad = [
        p.name
        for p in _files(directory)
        if b"\r" in (raw := p.read_bytes()) or not raw.endswith(b"\n")
    ]
    assert not bad, f"data/{directory}/: CRLF or missing trailing newline in {bad[:5]}"
