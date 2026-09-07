from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from cli import app
from cli.ingest_cmd import since_from_months
from ingest.dividends import iss as iss_mod
from storage.records import write_records_atomic
from storage.schemas import DIV_FIELDS


def test_version() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip()


def test_ingest_dividends_fails_when_source_serves_no_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dead ISS handle must not report a successful ingest — see task 054."""
    tickers_file = tmp_path / "tickers.json"
    tickers_file.write_text(
        json.dumps({"SBER": {"canonical": "Sberbank"}, "LKOH": {"canonical": "Lukoil"}}),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"description": {"columns": [], "data": []}})

    monkeypatch.setattr(
        iss_mod,
        "make_async_client",
        lambda: httpx.AsyncClient(
            base_url="https://iss.moex.com/iss", transport=httpx.MockTransport(handler)
        ),
    )

    result = CliRunner().invoke(
        app,
        [
            "ingest",
            "dividends",
            "--tickers",
            str(tickers_file),
            "--output-dir",
            str(tmp_path / "dividends"),
            "--prices-dir",
            str(tmp_path / "prices"),
            "--acked-no-div",
            str(tmp_path / "_acked.json"),
            "--gaps",
            str(tmp_path / "_gaps.json"),
            "--cache-dir",
            str(tmp_path / "cache"),
        ],
    )
    assert result.exit_code == 1
    assert "endpoint is gone" in result.output


def test_apply_conflicts_rejects_a_self_contradicting_journal(tmp_path: Path) -> None:
    """An augment feeding a replace re-adds its row on every pass — data grows silently."""
    divs = tmp_path / "dividends"
    write_records_atomic(
        divs / "AAA.csv",
        [{"registry_close": "2024-06-01", "amount": 1.0, "currency": "RUB", "source": "moex_iss"}],
        fieldnames=DIV_FIELDS,
    )
    journal = tmp_path / "_conflicts.json"
    journal.write_text(
        json.dumps(
            [
                {
                    "ticker": "AAA",
                    "registry_close": "2024-06-01",
                    "action": "augment",
                    "add": {"amount": 2.0, "currency": "RUB", "source": "manual_disclosure"},
                    "reason": "second tranche",
                },
                {
                    "ticker": "AAA",
                    "registry_close": "2024-06-01",
                    "action": "replace",
                    "from": {"amount": 2.0, "source": "manual_disclosure"},
                    "to": {"amount": 3.0, "currency": "RUB", "source": "manual_disclosure"},
                    "reason": "corrected",
                },
            ]
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "corporate",
            "apply-conflicts",
            "--dividends-dir",
            str(divs),
            "--conflicts",
            str(journal),
        ],
    )
    assert result.exit_code == 1
    assert "contradicts itself" in result.output


def test_apply_conflicts_accepts_a_settled_journal(tmp_path: Path) -> None:
    divs = tmp_path / "dividends"
    write_records_atomic(
        divs / "AAA.csv",
        [{"registry_close": "2024-06-01", "amount": 1.0, "currency": "RUB", "source": "moex_iss"}],
        fieldnames=DIV_FIELDS,
    )
    journal = tmp_path / "_conflicts.json"
    journal.write_text(
        json.dumps(
            [
                {
                    "ticker": "AAA",
                    "registry_close": "2024-06-01",
                    "action": "augment",
                    "add": {"amount": 2.0, "currency": "RUB", "source": "manual_disclosure"},
                    "reason": "second tranche",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = CliRunner().invoke(
        app,
        [
            "corporate",
            "apply-conflicts",
            "--dividends-dir",
            str(divs),
            "--conflicts",
            str(journal),
        ],
    )
    assert result.exit_code == 0


@pytest.mark.parametrize(
    ("today", "months", "expected"),
    [
        ("2026-06-15", 3, "2026-03-01"),
        ("2026-01-15", 3, "2025-10-01"),  # crosses the year boundary
        ("2026-01-31", 1, "2025-12-01"),
        ("2026-01-15", 12, "2025-01-01"),
        ("2026-01-15", 13, "2024-12-01"),
        ("2026-01-15", 24, "2024-01-01"),  # more than one year back
        ("2026-03-31", 1, "2026-02-01"),  # short month, day is discarded
    ],
)
def test_since_from_months_crosses_year_boundaries(today: str, months: int, expected: str) -> None:
    got = since_from_months(months, date.fromisoformat(today))
    assert got == date.fromisoformat(expected)


def test_since_from_months_zero_means_no_bound() -> None:
    assert since_from_months(0, date(2026, 6, 15)) is None
    assert since_from_months(-1, date(2026, 6, 15)) is None
