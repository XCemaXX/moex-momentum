"""Parse author's momentum quartiles from the Telegram blog export.

Source: raw_sources/dohodnost_blog/result.json (channel "Как приручить
доходность"). The author posts monthly momentum Q1-Q4 ticker lists in two text
formats: "Momentum Q1: ..." (older) and "Q1: ..." (newer). Earlier history
(pre-2022) lives in telegra.ph links / photos, not in the export text.

Output: agent_context/reference_quartiles.json — one object keyed by YYYY-MM,
each holding msg_id, post_date, and Q1-Q4 ticker lists.

Month convention: each post is an end-of-month ranking. A post on day <= 5 is a
late post of the previous month's close, so it maps to the previous month.

One-shot. Re-run after pulling more posts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "raw_sources" / "dohodnost_blog" / "result.json"
OUT = ROOT / "agent_context" / "reference_quartiles.json"

# optional "(annotation)" between Qn and colon, e.g. "Momentum Q1 (наибольший импульс):"
_QLINE = re.compile(r"(?:Momentum\s+)?Q([1-4])(?:\s*\([^)]*\))?\s*:\s*([^\n]+)", re.I)
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,5}")  # T, X5, VSMO; min 1 char (T = T-Tech)


def _flatten(text: object) -> str:
    if isinstance(text, list):
        return "".join(x if isinstance(x, str) else x.get("text", "") for x in text)
    return text if isinstance(text, str) else ""


def _tickers(value: str) -> list[str]:
    # split on comma/period/space (handles "LNZLP. PIKK" typo), keep ticker tokens
    return [tok for tok in re.split(r"[,.\s]+", value.strip()) if _TICKER.fullmatch(tok)]


def _asof_month(post_date: str) -> str:
    y, mo, da = (int(p) for p in post_date[:10].split("-"))
    if da <= 5:
        mo -= 1
        if mo == 0:
            mo, y = 12, y - 1
    return f"{y:04d}-{mo:02d}"


def main() -> None:
    messages = json.loads(SRC.read_text(encoding="utf-8"))["messages"]
    index: dict[str, dict] = {}

    for m in messages:
        quartiles: dict[int, list[str]] = {}
        for g, value in _QLINE.findall(_flatten(m.get("text", ""))):
            quartiles.setdefault(int(g), _tickers(value))
        if set(quartiles) < {1, 2, 3, 4}:
            continue
        post_date = m.get("date", "")[:10]
        month = _asof_month(post_date)
        if month in index:
            raise ValueError(f"month collision {month}: msg {m['id']} vs {index[month]['msg_id']}")
        index[month] = {
            "msg_id": m["id"],
            "post_date": post_date,
            "Q1": quartiles[1],
            "Q2": quartiles[2],
            "Q3": quartiles[3],
            "Q4": quartiles[4],
        }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(dict(sorted(index.items())), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    months = sorted(index)
    print(f"parsed {len(months)} months: {months[0]} -> {months[-1]}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
