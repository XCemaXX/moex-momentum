from __future__ import annotations

from pathlib import Path

from storage.records import read_records, write_records_atomic

_DIV_FIELDS = ("registry_close", "amount", "currency", "source", "registry_close_source")
_DIV_CASTS = {"amount": float}


def test_csv_roundtrip_with_casts(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    rows = [
        {
            "registry_close": "2024-07-11",
            "amount": 33.3,
            "currency": "RUB",
            "source": "moex_iss",
            "registry_close_source": "",
        },
        {
            "registry_close": "2025-07-18",
            "amount": 34.84,
            "currency": "RUB",
            "source": "skill_fill_tbank",
            "registry_close_source": "tbank_reestr",
        },
    ]
    n = write_records_atomic(p, rows, _DIV_FIELDS)
    assert n == 2
    got = read_records(p, casts=_DIV_CASTS)
    assert got[0]["amount"] == 33.3
    assert got[0]["currency"] == "RUB"
    assert got[1]["source"] == "skill_fill_tbank"


def test_csv_header_only_when_empty(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    n = write_records_atomic(p, [], _DIV_FIELDS)
    assert n == 0
    assert p.read_text(encoding="utf-8") == ",".join(_DIV_FIELDS) + "\n"
    assert read_records(p, casts=_DIV_CASTS) == []


def test_csv_heterogeneity_missing_field_becomes_empty(tmp_path: Path) -> None:
    p = tmp_path / "d.csv"
    # second row omits registry_close_source — should null-pad, not crash
    rows = [
        {
            "registry_close": "2024-07-11",
            "amount": 33.3,
            "currency": "RUB",
            "source": "moex_iss",
            "registry_close_source": "iss",
        },
        {"registry_close": "2025-07-18", "amount": 34.84, "currency": "RUB", "source": "moex_iss"},
    ]
    write_records_atomic(p, rows, _DIV_FIELDS)
    raw = p.read_text(encoding="utf-8").splitlines()
    assert raw[2].endswith(",moex_iss,")  # trailing empty field
    got = read_records(p, casts=_DIV_CASTS)
    assert got[1]["registry_close_source"] == ""
    assert got[1]["amount"] == 34.84


def test_empty_casted_field_becomes_none(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    write_records_atomic(p, [{"a": "", "b": "x"}], ("a", "b"))
    got = read_records(p, casts={"a": float})
    assert got[0]["a"] is None
    assert got[0]["b"] == "x"


def test_no_tmp_left_after_write(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    write_records_atomic(p, [{"a": "1"}], ("a",))
    assert not (tmp_path / "x.csv.tmp").exists()


def test_unicode_preserved(tmp_path: Path) -> None:
    p = tmp_path / "ru.csv"
    write_records_atomic(p, [{"name": "Сбербанк"}], ("name",))
    assert "Сбербанк" in p.read_text(encoding="utf-8")
    assert read_records(p)[0]["name"] == "Сбербанк"


def test_atomic_rename(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    write_records_atomic(p, [{"a": "1"}], ("a",))
    write_records_atomic(p, [{"a": "2"}], ("a",))
    assert read_records(p) == [{"a": "2"}]


def test_read_records_returns_empty_when_no_file(tmp_path: Path) -> None:
    assert read_records(tmp_path / "missing.csv") == []


def test_price_row_roundtrip_preserves_numeric_precision(tmp_path: Path) -> None:
    p = tmp_path / "p.csv"
    fields = ("date", "open", "high", "low", "close", "volume", "value", "board")
    casts = {
        "open": float,
        "high": float,
        "low": float,
        "close": float,
        "volume": int,
        "value": float,
    }
    row = {
        "date": "2007-04-05",
        "open": 92500.0,
        "high": 94996.0,
        "low": 92001.0,
        "close": 94650.0,
        "volume": 1138,
        "value": 106985066.61,
        "board": "EQBR",
    }
    write_records_atomic(p, [row], fields)
    got = read_records(p, casts=casts)[0]
    assert got["close"] == 94650.0
    assert got["volume"] == 1138
    assert got["value"] == 106985066.61
    assert got["board"] == "EQBR"
