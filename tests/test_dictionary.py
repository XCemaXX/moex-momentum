"""Tests for bootstrap logic: pagination drain, TYPE filter, changeover, alias merge."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from ingest.dictionary import bootstrap, merge_external_aliases


def _listing_payload(rows: list[list[Any]]) -> dict[str, Any]:
    return {
        "securities": {
            "columns": [
                "SECID",
                "SHORTNAME",
                "NAME",
                "BOARDID",
                "decimals",
                "history_from",
                "history_till",
            ],
            "data": rows,
        }
    }


def _description(items: dict[str, str]) -> dict[str, Any]:
    return {
        "columns": ["name", "title", "value", "type", "sort_order", "is_hidden", "precision"],
        "data": [[k, k, v, "string", i + 1, 0, None] for i, (k, v) in enumerate(items.items())],
    }


def _boards(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cols = [
        "secid",
        "boardid",
        "title",
        "board_group_id",
        "market_id",
        "market",
        "engine_id",
        "engine",
        "is_traded",
        "decimals",
        "history_from",
        "history_till",
        "listed_from",
        "listed_till",
        "is_primary",
        "currencyid",
        "unit",
    ]
    data = []
    for r in rows:
        data.append(
            [
                r.get("secid"),
                r["boardid"],
                "",
                0,
                1,
                "shares",
                1,
                "stock",
                r.get("is_traded", 1),
                2,
                r.get("history_from"),
                r.get("history_till"),
                r.get("history_from"),
                r.get("history_till"),
                r.get("is_primary", 0),
                "RUB",
                "M",
            ]
        )
    return {"columns": cols, "data": data}


def _changeover_payload(rows: list[list[str]]) -> dict[str, Any]:
    return {
        "changeover": {
            "columns": ["action_date", "old_secid", "new_secid"],
            "data": rows,
        }
    }


@pytest.fixture
def fake_iss():  # type: ignore[no-untyped-def]
    """Factory for ISS mocks. Each call returns a fresh client + counters (tests don't share state)."""
    listing_calls_total: dict[str, int] = {"listing": 0, "sec": 0, "changeover": 0}

    listing_pages = [
        _listing_payload(
            [
                [
                    "SBER",
                    "Сбербанк",
                    "Сбербанк России ПАО ао",
                    "TQBR",
                    2,
                    "2013-03-25",
                    "2026-05-04",
                ],
                [
                    "SBER",
                    "Сбербанк",
                    "Сбербанк России ПАО ао",
                    "EQBR",
                    2,
                    "2011-11-21",
                    "2013-08-30",
                ],
                ["T", "Т-Техно ао", "Т-Технологии ПАО ао", "TQBR", 2, "2024-11-28", "2026-05-04"],
                ["TCSG", "ТКСХолд ао", "ТКС Холдинг ПАО ао", "TQBR", 2, "2019-10-28", "2024-11-27"],
                ["SBMX", "SBMX ETF", "БПИФ Сбер", "TQTF", 2, "2018-09-17", "2026-05-04"],
                ["DERIV", "Заметка", "deriv", "TQDP", 2, None, None],
            ]
        ),
        _listing_payload([]),
    ]

    securities = {
        "SBER": {
            "description": _description(
                {
                    "SECID": "SBER",
                    "SHORTNAME": "Сбербанк",
                    "NAME": "Сбербанк России ПАО ао",
                    "LATNAME": "Sberbank",
                    "ISIN": "RU0009029540",
                    "TYPE": "common_share",
                }
            ),
            "boards": _boards(
                [
                    {
                        "secid": "SBER",
                        "boardid": "TQBR",
                        "is_primary": 1,
                        "is_traded": 1,
                        "history_from": "2013-03-25",
                        "history_till": "2026-05-04",
                    },
                    {
                        "secid": "SBER",
                        "boardid": "EQBR",
                        "is_primary": 0,
                        "is_traded": 0,
                        "history_from": "2011-11-21",
                        "history_till": "2013-08-30",
                    },
                ]
            ),
        },
        "T": {
            "description": _description(
                {
                    "SHORTNAME": "Т-Техно ао",
                    "NAME": "Т-Технологии ПАО ао",
                    "LATNAME": "T-Tehnologii",
                    "TYPE": "common_share",
                }
            ),
            "boards": _boards(
                [
                    {
                        "secid": "T",
                        "boardid": "TQBR",
                        "is_primary": 1,
                        "is_traded": 1,
                        "history_from": "2024-11-28",
                        "history_till": "2026-05-04",
                    }
                ]
            ),
        },
        "TCSG": {
            "description": _description(
                {
                    "SHORTNAME": "ТКСХолд ао",
                    "NAME": "ТКС Холдинг ПАО ао",
                    "LATNAME": "TCS Holding",
                    "TYPE": "common_share",
                }
            ),
            "boards": _boards(
                [
                    {
                        "secid": "TCSG",
                        "boardid": "TQBR",
                        "is_primary": 1,
                        "is_traded": 0,
                        "history_from": "2019-10-28",
                        "history_till": "2024-11-27",
                    }
                ]
            ),
        },
        "SBMX": {
            "description": _description({"SHORTNAME": "SBMX ETF", "TYPE": "exchange_ppif"}),
            "boards": _boards(
                [
                    {
                        "secid": "SBMX",
                        "boardid": "TQTF",
                        "is_primary": 1,
                        "is_traded": 1,
                        "history_from": "2018-09-17",
                        "history_till": "2026-05-04",
                    }
                ]
            ),
        },
        "DERIV": {
            "description": _description({"SHORTNAME": "Deriv", "TYPE": "common_share"}),
            "boards": _boards(
                [{"secid": "DERIV", "boardid": "TQDP", "is_primary": 1, "is_traded": 0}]
            ),
        },
    }

    changeover = _changeover_payload(
        [
            ["2024-11-27", "TCSG", "T"],
            ["2024-01-01", "RU000A1054321", "XXXXXX"],
        ]
    )

    def make() -> tuple[httpx.Client, dict[str, int]]:
        counters: dict[str, int] = {"listing_calls": 0, "sec_calls": 0, "changeover_calls": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path.endswith("/listing.json"):
                counters["listing_calls"] += 1
                start = int(request.url.params.get("start", "0"))
                page_idx = 0 if start == 0 else 1
                return httpx.Response(200, json=listing_pages[page_idx])
            if path.endswith("/changeover.json"):
                counters["changeover_calls"] += 1
                return httpx.Response(200, json=changeover)
            if path.startswith("/iss/securities/"):
                counters["sec_calls"] += 1
                secid = path.rsplit("/", 1)[-1].removesuffix(".json")
                payload = securities.get(secid)
                if payload is None:
                    return httpx.Response(404)
                return httpx.Response(200, json=payload)
            return httpx.Response(404)

        client = httpx.Client(
            base_url="https://iss.moex.com/iss",
            transport=httpx.MockTransport(handler),
            params={"iss.meta": "off"},
        )
        return client, counters

    _ = listing_calls_total  # silence unused
    return make


def test_bootstrap_drains_pagination(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, counters = fake_iss()
    with client:
        bootstrap({}, client=client, today=date(2026, 5, 5))
    assert counters["listing_calls"] == 2


def test_bootstrap_filters_non_equity(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    assert "SBER" in out
    assert "T" in out
    assert "TCSG" in out
    assert "SBMX" not in out


def test_bootstrap_drops_null_history_rows(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    assert "DERIV" not in out


def test_bootstrap_canonical_and_aliases(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    assert out["SBER"]["canonical"] == "Сбербанк"
    assert "Сбербанк России ПАО ао" in out["SBER"]["aliases"]
    assert "Sberbank" in out["SBER"]["aliases"]
    assert "Сбербанк" not in out["SBER"]["aliases"]


def test_bootstrap_changeover_applied(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    history = out["T"]["history"]
    assert len(history) == 1
    assert history[0] == {
        "prev_ticker": "TCSG",
        "renamed": "2024-11-27",
        "source": "iss_changeover",
    }


def test_bootstrap_changeover_skips_xxxxxx(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    for entry in out.values():
        for h in entry.get("history", []):
            assert h["prev_ticker"] != "XXXXXX"


def test_bootstrap_marks_delisted(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        out = bootstrap({}, client=client, today=date(2026, 5, 5))
    assert out["TCSG"].get("delisted_after") == "2024-11-27"
    assert "delisted_after" not in out["SBER"]


def test_bootstrap_does_not_overwrite_canonical(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    existing = {"SBER": {"canonical": "Сбер (custom)"}}
    with client:
        out = bootstrap(existing, client=client, today=date(2026, 5, 5))  # type: ignore[arg-type]
    assert out["SBER"]["canonical"] == "Сбер (custom)"


def test_bootstrap_idempotent_on_changeover(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    with client:
        first = bootstrap({}, client=client, today=date(2026, 5, 5))
    client2, _ = fake_iss()  # fresh client because mock client is closed
    with client2:
        second = bootstrap(first, client=client2, today=date(2026, 5, 5))
    assert first["T"]["history"] == second["T"]["history"]


def test_bootstrap_preserves_manual_history(fake_iss) -> None:  # type: ignore[no-untyped-def]
    client, _ = fake_iss()
    existing: dict = {
        "T": {
            "canonical": "",
            "history": [{"prev_ticker": "OLDX", "renamed": "2010-01-01", "source": "manual"}],
        }
    }
    with client:
        out = bootstrap(existing, client=client, today=date(2026, 5, 5))
    sources = {h["source"] for h in out["T"]["history"]}
    assert sources == {"manual", "iss_changeover"}


def test_merge_external_aliases() -> None:
    tickers: dict = {
        "SBER": {
            "canonical": "Сбербанк",
            "aliases": ["Sberbank"],
        }
    }
    seed = {
        "SBER": {
            "names": ["Сбербанк", "ПАО Сбербанк", "Sberbank"],
            "former_names": ["Сберегательный банк РФ"],
        },
        "_unavailable": ["something"],
        "UNKNOWN": {"names": ["x"]},
    }
    out = merge_external_aliases(tickers, seed)  # type: ignore[arg-type]
    assert out["SBER"]["aliases"] == [
        "Sberbank",
        "ПАО Сбербанк",
        "Сберегательный банк РФ",
    ]
    assert "UNKNOWN" not in out


def test_merge_external_aliases_case_insensitive_dedup() -> None:
    tickers: dict = {"SBER": {"canonical": "Сбербанк", "aliases": ["sberbank"]}}
    seed = {"SBER": {"names": ["Sberbank", "SBERBANK"], "former_names": []}}
    out = merge_external_aliases(tickers, seed)  # type: ignore[arg-type]
    assert out["SBER"]["aliases"] == ["sberbank"]
