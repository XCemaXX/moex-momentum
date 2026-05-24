from __future__ import annotations

from cli.logging_setup import kv


def test_kv_basic() -> None:
    assert kv(ticker="SBER", rows=42) == "ticker=SBER rows=42"


def test_kv_quotes_value_with_space() -> None:
    assert kv(msg="hello world") == 'msg="hello world"'


def test_kv_escapes_quotes() -> None:
    assert kv(msg='he said "hi"') == r'msg="he said \"hi\""'
