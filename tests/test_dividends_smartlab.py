"""Tests for the smart-lab dividend fetcher."""

from __future__ import annotations

from pathlib import Path

from ingest.dividends.smartlab import SmartLabFetcher, _parse_amount, _parse_smartlab_date


def _page(rows: str) -> str:
    return (
        "<html><body><table>"
        "<tr><td>Выплаченные дивиденды</td></tr>"
        "<tr><th>Тикер</th><th>дата T-1</th><th>дата отсечки</th><th>Период</th>"
        "<th>дивиденд</th><th>Цена акции</th><th>Див. доходность</th></tr>"
        f"{rows}"
        "</table></body></html>"
    )


def _row(ticker: str, t1: str, cut: str, amount: str) -> str:
    return (
        f"<tr><td>{ticker}</td><td>{t1}</td><td>{cut}</td><td>2025 год</td>"
        f"<td>{amount}</td><td>100</td><td>2,5%</td></tr>"
    )


def test_parse_amount() -> None:
    assert _parse_amount("394₽") == 394.0
    assert _parse_amount("0,0294 ₽") == 0.0294
    assert _parse_amount("1 234,5₽") == 1234.5
    assert _parse_amount("12,3 $") is None  # non-rouble must not pass as RUB
    assert _parse_amount("n/a") is None
    assert _parse_amount("0₽") is None


def test_parse_date() -> None:
    assert _parse_smartlab_date("06.07.2026") == "2026-07-06"
    assert _parse_smartlab_date("прогноз") is None


def test_fetch_reads_the_record_date_column(tmp_path: Path) -> None:
    html = _page(_row("CHKZ", "03.07.2026", "06.07.2026", "394₽"))
    f = SmartLabFetcher(lambda _u: html, cache_dir=tmp_path)
    assert f.fetch("CHKZ") == [
        {
            "registry_close": "2026-07-06",
            "amount": 394.0,
            "currency": "RUB",
            "source": "skill_fill_smartlab",
        }
    ]


def test_other_share_class_is_filtered_out(tmp_path: Path) -> None:
    html = _page(
        _row("TORS", "23.06.2026", "24.06.2026", "0,0156₽")
        + _row("TORSP", "23.06.2026", "24.06.2026", "0,0294₽")
    )
    f = SmartLabFetcher(lambda _u: html, cache_dir=tmp_path)
    assert [r["amount"] for r in f.fetch("TORS")] == [0.0156]


def test_pref_falls_back_to_the_ordinary_page(tmp_path: Path) -> None:
    html = _page(
        _row("JNOS", "06.07.2026", "07.07.2026", "0,02₽")
        + _row("JNOSP", "06.07.2026", "07.07.2026", "0,01₽")
    )
    seen: list[str] = []

    def http_get(url: str) -> str | None:
        seen.append(url)
        return None if "JNOSP" in url else html

    f = SmartLabFetcher(http_get, cache_dir=tmp_path)
    assert [r["amount"] for r in f.fetch("JNOSP")] == [0.01]
    assert seen == [
        "https://smart-lab.ru/q/JNOSP/dividend/",
        "https://smart-lab.ru/q/JNOS/dividend/",
    ]


def test_missing_header_yields_nothing(tmp_path: Path) -> None:
    html = "<html><body><table><tr><td>ничего</td></tr></table></body></html>"
    f = SmartLabFetcher(lambda _u: html, cache_dir=tmp_path)
    assert f.fetch("YRSB") == []


def test_cancelled_payout_is_dropped(tmp_path: Path) -> None:
    """A recommendation the AGM voted down is still listed, marked only in the markup."""
    html = _page(
        "<tr><td>PLZL</td><td>14.06.2023</td><td>16.06.2023</td><td>2022 год</td>"
        '<td><strong class="dividend_canceled">436,79</strong>₽</td>'
        "<td>10430</td><td>4,2%</td></tr>" + _row("PLZL", "12.07.2026", "13.07.2026", "29,05₽")
    )
    f = SmartLabFetcher(lambda _u: html, cache_dir=tmp_path)
    assert [r["registry_close"] for r in f.fetch("PLZL")] == ["2026-07-13"]
