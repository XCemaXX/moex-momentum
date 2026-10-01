"""Tests for the MOEX register-closing-dates completeness check."""

from __future__ import annotations

from pathlib import Path

import pytest

from adjustments.dividend_gaps import load_acked, load_acked_dates
from ingest.dividends.register import missing_payouts, parse_register
from storage.records import write_records_atomic
from storage.schemas import DIV_FIELDS, PRICE_FIELDS

HEADER = "Эмитент,Дата события,Адрес сайта,Тип события\n"


def _csv(*lines: str) -> bytes:
    return (HEADER + "".join(line + "\n" for line in lines)).encode("cp1251")


def test_parse_extracts_ticker_and_date() -> None:
    payload = _csv(
        '"ПАО ""Татнефть"" - 2-03-00161-A, TATNP [Акция привилегированная]",'
        "10/13/2026 00:00:00,www.tatneft.ru,закрытие реестра"
    )
    assert parse_register(payload) == [
        {"ticker": "TATNP", "record_date": "2026-10-13", "confirmed": True}
    ]


def test_parse_skips_untagged_rows() -> None:
    payload = _csv('"ПАО ""Газпром""",05/13/2013 00:00:00,www.gazprom.ru,закрытие реестра')
    assert parse_register(payload) == []


def test_parse_keeps_recommended_rows_unconfirmed() -> None:
    """MOEX may leave a paid closing "рекомендуемая" for months (LVHK 2026-06-15)."""
    payload = _csv(
        '"ПАО ""Левенгук"" - 1-01-04329-D, LVHK [Акция обыкновенная]",'
        "06/15/2026 00:00:00,,закрытие реестра (рекомендуемая)"
    )
    assert parse_register(payload) == [
        {"ticker": "LVHK", "record_date": "2026-06-15", "confirmed": False}
    ]


def _seed(tmp_path: Path, ticker: str, dates: list[str]) -> tuple[Path, Path]:
    divs, prices = tmp_path / "div", tmp_path / "px"
    write_records_atomic(
        prices / f"{ticker}.csv",
        [{"date": "2026-01-01", "close": 1.0, "value": 1.0, "volume": 1}],
        fieldnames=PRICE_FIELDS,
    )
    if dates:
        write_records_atomic(
            divs / f"{ticker}.csv",
            [
                {"registry_close": d, "amount": 1.0, "currency": "RUB", "source": "moex_iss"}
                for d in dates
            ],
            fieldnames=DIV_FIELDS,
        )
    return divs, prices


def test_stored_payout_near_the_register_date_is_not_a_gap(tmp_path: Path) -> None:
    divs, prices = _seed(tmp_path, "CHKZ", ["2026-07-05"])
    register = [{"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": True}]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-12-31") == []


def test_register_closing_without_a_payout_is_reported(tmp_path: Path) -> None:
    divs, prices = _seed(tmp_path, "CHKZ", ["2025-07-07"])
    register = [{"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": True}]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-12-31") == [
        {"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": True}
    ]


def test_first_ever_payout_counts(tmp_path: Path) -> None:
    """Keying membership on the dividend file would hide a share's first payout."""
    divs, prices = _seed(tmp_path, "NEWCO", [])
    register = [{"ticker": "NEWCO", "record_date": "2026-07-06", "confirmed": True}]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-12-31") == [
        {"ticker": "NEWCO", "record_date": "2026-07-06", "confirmed": True}
    ]


def test_tickers_we_do_not_track_are_ignored(tmp_path: Path) -> None:
    divs, prices = _seed(tmp_path, "CHKZ", ["2026-07-06"])
    register = [{"ticker": "OTHER", "record_date": "2026-07-06", "confirmed": True}]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-12-31") == []


def test_closing_before_the_first_traded_day_is_not_a_gap(tmp_path: Path) -> None:
    """Pre-IPO registers pay the founders; no listed share was entitled."""
    divs, prices = _seed(tmp_path, "BAZA", [])
    register = [
        {"ticker": "BAZA", "record_date": "2025-12-01", "confirmed": True},
        {"ticker": "BAZA", "record_date": "2026-07-06", "confirmed": True},
    ]
    assert missing_payouts(register, divs, prices, since="2025-01-01", until="2026-12-31") == [
        {"ticker": "BAZA", "record_date": "2026-07-06", "confirmed": True}
    ]


def test_acked_year_is_suppressed(tmp_path: Path) -> None:
    """The export mixes in shareholder-meeting registers; a confirmed non-payer stays quiet."""
    divs, prices = _seed(tmp_path, "CBOM", ["2026-02-01"])
    register = [{"ticker": "CBOM", "record_date": "2026-07-31", "confirmed": True}]
    args = {"since": "2026-01-01", "until": "2026-12-31"}
    assert missing_payouts(register, divs, prices, acked={"CBOM": {2026}}, **args) == []
    assert len(missing_payouts(register, divs, prices, **args)) == 1


def test_unconfirmed_closing_is_reported_with_its_flag(tmp_path: Path) -> None:
    divs, prices = _seed(tmp_path, "LVHK", ["2024-06-28"])
    register = [
        {"ticker": "LVHK", "record_date": "2026-06-15", "confirmed": False},
        {"ticker": "LVHK", "record_date": "2026-12-15", "confirmed": False},
    ]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-10-01") == [
        {"ticker": "LVHK", "record_date": "2026-06-15", "confirmed": False}
    ]


def test_date_listed_under_both_types_counts_as_confirmed(tmp_path: Path) -> None:
    divs, prices = _seed(tmp_path, "CHKZ", [])
    register = [
        {"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": False},
        {"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": True},
    ]
    assert missing_payouts(register, divs, prices, since="2026-01-01", until="2026-12-31") == [
        {"ticker": "CHKZ", "record_date": "2026-07-06", "confirmed": True}
    ]


def test_acked_date_suppresses_only_that_closing(tmp_path: Path) -> None:
    """SVET pays several times a year; acking the cancelled July closing must not
    hide a real December one."""
    divs, prices = _seed(tmp_path, "SVET", [])
    register = [
        {"ticker": "SVET", "record_date": "2026-07-08", "confirmed": False},
        {"ticker": "SVET", "record_date": "2026-12-30", "confirmed": True},
    ]
    hits = missing_payouts(
        register,
        divs,
        prices,
        acked_dates={"SVET": {"2026-07-08"}},
        since="2026-01-01",
        until="2026-12-31",
    )
    assert [h["record_date"] for h in hits] == ["2026-12-30"]


def test_acked_file_splits_years_from_dates(tmp_path: Path) -> None:
    path = tmp_path / "acked.json"
    path.write_text(
        '{"svet": {"2026-07-08": "AGM failed"}, "CBOM": {"2015": "meeting list"}}',
        encoding="utf-8",
    )
    assert load_acked(path) == {"SVET": set(), "CBOM": {2015}}
    assert load_acked_dates(path) == {"SVET": {"2026-07-08"}, "CBOM": set()}


def test_acked_file_rejects_malformed_key(tmp_path: Path) -> None:
    path = tmp_path / "acked.json"
    path.write_text('{"SVET": {"2026-07": "x"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="neither YYYY"):
        load_acked(path)
