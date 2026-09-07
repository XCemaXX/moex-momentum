"""tbank and yahoo dividend fetchers.

Since ISS withdrew its dividends handle (task 054) every new payout arrives
through fetchers like these, so their parsers are load-bearing. Both read a
vendor page shape that can change without notice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ingest.dividends.tbank import TbankFetcher
from ingest.dividends.yahoo import YahooFetcher


def _tbank_page(buckets: dict[str, Any], *, extra_script: str = "") -> str:
    payload = json.dumps({"stores": {"investDividends": buckets}})
    return (
        "<html><head>"
        f'<script type="application/json">{{"stores": {{"other": 1}}}}</script>'
        f"{extra_script}"
        f'<script type="application/json">{payload}</script>'
        "</head><body></body></html>"
    )


def _entry(reestr: str, value: float, currency: str = "RUB") -> dict[str, Any]:
    return {"reestr": reestr, "dividend": {"value": value, "currency": currency}}


def _fetcher(cls: type, page: str, tmp_path: Path, calls: list[str] | None = None):  # type: ignore[no-untyped-def]
    def http_get(url: str) -> str:
        if calls is not None:
            calls.append(url)
        return page

    return cls(http_get, cache_dir=tmp_path)


def test_tbank_parses_and_sorts(tmp_path: Path) -> None:
    page = _tbank_page(
        {
            "LNZLP": {
                "dividends": [
                    _entry("2024-06-17T00:00:00+03:00", 13.87),
                    _entry("2021-05-31T00:00:00+03:00", 1057.17, "SUR"),
                ]
            }
        }
    )
    rows = _fetcher(TbankFetcher, page, tmp_path).fetch("LNZLP")
    assert [r["registry_close"] for r in rows] == ["2021-05-31", "2024-06-17"]
    assert rows[0]["currency"] == "RUB"  # SUR is the legacy rouble code
    assert rows[0]["source"] == "skill_fill_tbank"
    assert rows[0]["registry_close_source"] == "tbank_reestr"


def test_tbank_drops_unusable_rows(tmp_path: Path) -> None:
    page = _tbank_page(
        {
            "MTSS": {
                "dividends": [
                    _entry("2024-06-17T00:00:00+03:00", 35.0),
                    _entry("2024-01-10T00:00:00+03:00", 0.0),  # zero payout
                    _entry("", 5.0),  # no date
                    {"reestr": "2023-01-10T00:00:00+03:00", "dividend": {}},  # no value
                    "not a dict",
                ]
            }
        }
    )
    rows = _fetcher(TbankFetcher, page, tmp_path).fetch("MTSS")
    assert [r["amount"] for r in rows] == [35.0]


def test_tbank_falls_back_to_the_only_bucket(tmp_path: Path) -> None:
    """The page sometimes keys by ISIN instead of ticker."""
    page = _tbank_page({"RU0009024277": {"dividends": [_entry("2024-06-17T00:00:00+03:00", 35.0)]}})
    rows = _fetcher(TbankFetcher, page, tmp_path).fetch("MTSS")
    assert len(rows) == 1


def test_tbank_refuses_to_guess_between_two_buckets(tmp_path: Path) -> None:
    """Two unkeyed buckets — picking either could attribute another share's payouts."""
    page = _tbank_page(
        {
            "RU0009024277": {"dividends": [_entry("2024-06-17T00:00:00+03:00", 35.0)]},
            "RU0007288411": {"dividends": [_entry("2024-06-17T00:00:00+03:00", 99.0)]},
        }
    )
    assert _fetcher(TbankFetcher, page, tmp_path).fetch("MTSS") == []


def test_tbank_survives_a_malformed_script_block(tmp_path: Path) -> None:
    page = _tbank_page(
        {"MTSS": {"dividends": [_entry("2024-06-17T00:00:00+03:00", 35.0)]}},
        extra_script='<script type="application/json">{investDividends: broken</script>',
    )
    assert len(_fetcher(TbankFetcher, page, tmp_path).fetch("MTSS")) == 1


def test_tbank_missing_block_is_empty_not_an_error(tmp_path: Path) -> None:
    page = "<html><body>no payload here</body></html>"
    assert _fetcher(TbankFetcher, page, tmp_path).fetch("MTSS") == []


def _yahoo_payload(
    dividends: dict[str, Any] | None = None, *, error: Any = None, currency: str = "RUB"
) -> str:
    if error is not None:
        return json.dumps({"chart": {"error": error, "result": None}})
    return json.dumps(
        {
            "chart": {
                "error": None,
                "result": [
                    {
                        "meta": {"currency": currency, "exchangeName": "MCX"},
                        "events": {"dividends": dividends or {}},
                    }
                ],
            }
        }
    )


def test_yahoo_converts_timestamps_to_ex_dates(tmp_path: Path) -> None:
    page = _yahoo_payload(
        {
            "1622160000": {"amount": 1057.17, "date": 1622160000},  # 2021-05-28
            "1718582400": {"amount": 13.87, "date": 1718582400},  # 2024-06-17
        }
    )
    rows = _fetcher(YahooFetcher, page, tmp_path).fetch("LNZLP")
    assert [r["registry_close"] for r in rows] == ["2021-05-28", "2024-06-17"]
    # The date is the ex-date, not the register close; merge.py needs the tag to
    # let a higher-priority source overwrite it.
    assert {r["registry_close_source"] for r in rows} == {"yahoo_ex_div"}


def test_yahoo_error_payload_yields_nothing(tmp_path: Path) -> None:
    page = _yahoo_payload(error={"code": "Not Found"})
    assert _fetcher(YahooFetcher, page, tmp_path).fetch("NOSUCH") == []


def test_yahoo_drops_incomplete_and_zero_rows(tmp_path: Path) -> None:
    page = _yahoo_payload(
        {
            "a": {"amount": 13.87, "date": 1718582400},
            "b": {"amount": 0.0, "date": 1718582400},
            "c": {"amount": 5.0},  # no date
            "d": {"date": 1718582400},  # no amount
        }
    )
    rows = _fetcher(YahooFetcher, page, tmp_path).fetch("LNZLP")
    assert [r["amount"] for r in rows] == [13.87]


def test_yahoo_malformed_json_yields_nothing(tmp_path: Path) -> None:
    assert _fetcher(YahooFetcher, "{not json", tmp_path).fetch("LNZLP") == []


def test_a_parse_failure_does_not_cost_a_second_round_trip(tmp_path: Path) -> None:
    """The raw response is cached before parsing, so a re-run re-parses on disk."""
    calls: list[str] = []
    assert _fetcher(YahooFetcher, "{not json", tmp_path, calls).fetch("LNZLP") == []
    assert len(calls) == 1
    assert _fetcher(YahooFetcher, "{not json", tmp_path, calls).fetch("LNZLP") == []
    assert len(calls) == 1
