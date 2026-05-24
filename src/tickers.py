"""Ticker dictionary: data/tickers.json (auto-seed) + data/tickers_manual.json (override).

Auto-seed: bootstrap from ISS — listing.json + securities/{SECID}.json + changeover.json.
Manual: redomiciles and bonus issues missing from /splits.json.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict


def enumerate_tickers(*dirs: Path) -> list[str]:
    """Sorted union of `.csv` stems across the given dirs."""
    seen: set[str] = set()
    for d in dirs:
        if not d.exists():
            continue
        for p in d.glob("*.csv"):
            seen.add(p.stem)
    return sorted(seen)


class Board(TypedDict, total=False):
    board: str
    history_from: str
    history_till: str
    is_primary: bool


class Rebrand(TypedDict):
    prev_ticker: str
    renamed: str
    source: Literal["iss_changeover", "manual"]


class TickerEntry(TypedDict, total=False):
    canonical: str
    aliases: list[str]
    type: Literal["share", "bond", "ofz", "etf", "fx"]
    boards: list[Board]
    history: list[Rebrand]
    delisted_after: str


TickersDict = dict[str, TickerEntry]

ManualType = Literal["redomicile", "bonus_issue", "reverse_split"]


class ManualEntry(TypedDict, total=False):
    old_secid: str
    new_secid: str
    renamed: str
    type: ManualType
    reason: str
    ratio: float


VALID_MANUAL_TYPES: tuple[ManualType, ...] = ("redomicile", "bonus_issue", "reverse_split")
VALID_REBRAND_SOURCES: tuple[str, ...] = ("iss_changeover", "manual")


def load(path: Path) -> TickersDict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        data: Any = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object, got {type(data).__name__}")
    return data


def save(path: Path, data: TickersDict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def load_unavailable(path: Path) -> dict[str, dict[str, str]]:
    """`data/tickers_unavailable.jsonl` — SECIDs for which ISS is empty on all boards.

    Bootstrap skips them at the listing stage, ingest never sees them. Editable by hand:
    add a line = new skip; remove it = retry pull.
    """
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            rec: Any = json.loads(line)
            if not isinstance(rec, dict) or "secid" not in rec:
                raise ValueError(f"{path}: each line must be an object with 'secid'")
            secid = str(rec.pop("secid")).upper()
            out[secid] = {k: str(v) for k, v in rec.items()}
    return out


def save_unavailable(path: Path, data: dict[str, dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for secid in sorted(data):
            rec = {"secid": secid, **data[secid]}
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")
    tmp.replace(path)


def load_manual(path: Path) -> list[ManualEntry]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data: Any = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON array")
    for i, rec in enumerate(data):
        if not isinstance(rec, dict):
            raise ValueError(f"{path}[{i}]: entry is not an object")
        validate_manual_entry(rec, where=f"{path}[{i}]")
    return data


def validate_manual_entry(rec: dict[str, Any], where: str) -> None:
    for fld in ("old_secid", "new_secid", "renamed", "type", "reason"):
        if not rec.get(fld):
            raise ValueError(f"{where}: missing or empty field {fld!r}")
    if rec["type"] not in VALID_MANUAL_TYPES:
        raise ValueError(f"{where}: type={rec['type']!r} not in {VALID_MANUAL_TYPES}")
    if rec["type"] in ("bonus_issue", "reverse_split") and "ratio" not in rec:
        raise ValueError(f"{where}: {rec['type']} requires field ratio")


def validate_tickers(tickers: TickersDict) -> None:
    for secid, entry in tickers.items():
        where = f"tickers[{secid!r}]"
        if secid != secid.upper():
            raise ValueError(f"{where}: key must be uppercase")
        canonical = entry.get("canonical")
        if not canonical:
            raise ValueError(f"{where}: canonical is empty")
        for alias in entry.get("aliases", ()):
            if alias == canonical:
                raise ValueError(f"{where}: alias {alias!r} matches canonical")
        primary_count = sum(1 for b in entry.get("boards", ()) if b.get("is_primary"))
        if primary_count > 1:
            raise ValueError(f"{where}: more than one board with is_primary=true")
        for h in entry.get("history", ()):
            if h.get("source") not in VALID_REBRAND_SOURCES:
                raise ValueError(f"{where}: history.source is invalid")
            if not h.get("prev_ticker") or not h.get("renamed"):
                raise ValueError(f"{where}: history has empty fields")


def get_canonical(tickers: TickersDict, ticker: str) -> str:
    return tickers[ticker.upper()]["canonical"]


def resolve_alias(tickers: TickersDict, name: str) -> str | None:
    needle = name.strip().casefold()
    if not needle:
        return None
    for secid, entry in tickers.items():
        if entry.get("canonical", "").casefold() == needle:
            return secid
        for alias in entry.get("aliases", ()):
            if alias.casefold() == needle:
                return secid
    return None


def get_history(tickers: TickersDict, ticker: str) -> list[Rebrand]:
    entry = tickers.get(ticker.upper())
    if entry is None:
        return []
    return list(entry.get("history", ()))


def walk_history(tickers: TickersDict, ticker: str, on: date | str) -> str:
    """SECID under which the ticker traded on date `on`. Walks the chain recursively.

    Boundary: a rebrand with `renamed = D` means the new name takes effect on day D.
    A query with `on < D` returns prev_ticker.
    """
    on_iso = on.isoformat() if isinstance(on, date) else on
    cur = ticker.upper()
    visited: set[str] = set()
    while cur not in visited:
        visited.add(cur)
        entry = tickers.get(cur)
        if entry is None:
            return cur
        rebrands = sorted(
            entry.get("history", ()),
            key=lambda r: r["renamed"],
            reverse=True,
        )
        for r in rebrands:
            if on_iso < r["renamed"]:
                cur = r["prev_ticker"].upper()
                break
        else:
            return cur
    raise ValueError(f"walk_history: cycle in history of {ticker}")
