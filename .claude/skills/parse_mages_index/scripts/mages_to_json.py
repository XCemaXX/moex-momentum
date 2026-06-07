"""Индекс Магов txt -> per-quarter JSON + matching report.

Batch + idempotent. Reads every raw_sources/mages_index/mages_index_<YYYY-MM>*.txt,
writes data/mages/<YYYY-Qn>.json and data/mages/matching_report.md, and extends
data/tickers.json aliases for any blog name that resolves to a known SECID.

Name resolution order (first hit wins):
  1. SHARE_TO_TICKER / OTHER_KIND / EXTERNAL  — authoritative tables below.
  2. existing data/mages/*.json               — reuse a name already resolved before.
  3. resolve_alias(data/tickers.json)         — dict canonical/alias exact match.
An unresolved name aborts the run: add it to a table here, then re-run.

A resolved share with canonical=null (real ticker, no price series) is emitted into
`other` with type="otc" — not investable, so it stays out of `shares` and the weights.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / "data" / "tickers.json").exists():
            return p
    raise SystemExit("repo root not found (no data/tickers.json above script)")


ROOT = find_root(Path(__file__).resolve())
sys.path.insert(0, str(ROOT / "src"))
import tickers as T  # noqa: E402, N812

IN_DIR = ROOT / "raw_sources" / "mages_index"
OUT_DIR = ROOT / "data" / "mages"
DICT_PATH = ROOT / "data" / "tickers.json"
SOURCES_PATH = IN_DIR / "sources.json"
REPORT_PATH = OUT_DIR / "matching_report.md"

MONTH_TO_Q = {"01": 1, "04": 2, "07": 3, "10": 4}

# Non-equities: kept in `other`, never matched or re-normalized.
OTHER_KIND = {
    "CNY": "fx",
    "EUR": "fx",
    "USD": "fx",
    "LQDT": "fund",
    "ОФЗ 26238": "bond",
    "ОФЗ 26248": "bond",
    "ОФЗ 26254": "bond",
    "ОФЗ 52002": "bond",
    "Газпром Капитал БО-003р-14": "bond",
    "Айдеко БО-01": "bond",
    "БорецКЗО26": "bond",
    "Новатэк 001Р-04": "bond",
    "МКБ ЗО-2027": "bond",
    "Полипласт П2Б5": "bond",
    "ВУШ 001Р-03": "bond",
    "Сегежа 002Р-05R": "bond",
    "Сегежа3Р7R": "bond",
    "Сегежа3P1R": "bond",
    "Сегежа3Р1R": "bond",
}

# Real MOEX tickers absent from data/tickers.json (OTC / outside price universe).
EXTERNAL = {"Новошип ао": "NOMP", "Новошип ап": "NOMPP", "ВМТП": "VMTP", "БЭСК ап": "BESKP"}

# Authoritative blog-name -> SECID. Reviewed by hand (incl. Аренадата=DATA, not DIAS).
SHARE_TO_TICKER = {
    "Сбербанк ао": "SBER",
    "Сбербанк ап": "SBERP",
    "OZON": "OZON",
    "Роснефть": "ROSN",
    "Сургутнефтегаз ао": "SNGS",
    "Сургутнефтегаз ап": "SNGSP",
    "Транснефть ап": "TRNFP",
    "Яндекс": "YDEX",
    "Башнефть ап": "BANEP",
    "НоваБев": "BELU",
    "Белуга": "BELU",
    "ВТБ": "VTBR",
    "Ренессанс Страхование": "RENI",
    "Россети ЦП": "MRKP",
    "Совкомбанк": "SVCB",
    "Совкомфлот": "FLOT",
    "Магнит": "MGNT",
    "Газпром": "GAZP",
    "Газпром нефть": "SIBN",
    "Лента": "LENT",
    "Ленэнерго ап": "LSNGP",
    "Россети-ФСК": "FEES",
    "Хедхантер": "HEAD",
    "ЮГК": "UGLD",
    "Аренадата": "DATA",
    "ЛУКойл": "LKOH",
    "ЛУКОЙЛ": "LKOH",
    "НЛМК": "NLMK",
    "Русагро": "RAGR",
    "Юнипро": "UPRO",
    "SFI": "SFIN",
    "WHOOSH": "WUSH",
    "X5 Group": "X5",
    "КЦ ИКС 5": "X5",
    "БСП": "BSPB",
    "БСП ао": "BSPB",
    "БСП ап": "BSPBP",
    "Европлан": "LEAS",
    "ИнтерРАО": "IRAO",
    "МТС": "MTSS",
    "Новатэк": "NVTK",
    "НОВАТЭК": "NVTK",
    "Распадская": "RASP",
    "Т-Технологии": "T",
    "ТКС": "T",
    "Т-Банк": "T",
    "ТМК": "TRMK",
    "Форвард Энерго": "TGKJ",
    "Черкизово": "GCHE",
    "АФК Система": "AFKS",
    "Аэрофлот": "AFLT",
    "НМТП": "NMTP",
    "Россети Волга": "MRKV",
    "Россети Центр": "MRKC",
    "Россети Урал": "MRKU",
    "МРСК Урала": "MRKU",
    "Россети МР": "MSRS",
    "АЛРОСА": "ALRS",
    "Алроса": "ALRS",
    "Займер": "ZAYM",
    "НКНХ ап": "NKNCP",
    "ОВК": "UWGN",
    "Позитив": "POSI",
    "Полюс": "PLZL",
    "Ростелеком ао": "RTKM",
    "Ростелеком ап": "RTKMP",
    "СПб Биржа": "SPBE",
    "Самолёт": "SMLT",
    "Софтлайн": "SOFL",
    "ЯТЭК": "YAKG",
    "Астра": "ASTR",
    "ВК": "VKCO",
    "ВСМПО-Ависма": "VSMO",
    "Глобалтранс": "GLTR",
    "ДОМ.РФ": "DOMRF",
    "М.Видео": "MVID",
    "Норильский никель": "GMKN",
    "ГМК НорНикель": "GMKN",
    "Промомед": "PRMD",
    "Русал": "RUAL",
    "Русснефть": "RNFT",
    "Сегежа": "SGZH",
    "ТГК-14": "TGKN",
    "ЭЛ5-Энерго": "ELFV",
    "ЭН плюс": "ENPG",
    "CIAN": "CNRU",
    "GEMC": "GEMC",
    "ДВМП": "FESH",
    "Диасофт": "DIAS",
    "ЕвроТранс": "EUTR",
    "Кармани": "CARM",
    "Куйбышев Азот ао": "KAZT",
    "Мечел ао": "MTLR",
    "Мечел ап": "MTLRP",
    "Мосбиржа": "MOEX",
    "ПермЭнСб ао": "PMSB",
    "Северсталь": "CHMF",
    "Селигдар": "SELG",
    "ТЗА": "TUZA",
    "Фосагро": "PHOR",
    "ЦМТ ао": "WTCM",
    **EXTERNAL,
}


def parse_pct(cell: str) -> float:
    return float(cell.strip().rstrip("%").replace(",", "."))


def quarter_of(period: str) -> str:
    year, month = period.split("-")
    if month not in MONTH_TO_Q:
        raise SystemExit(f"period {period}: month must be 01/04/07/10 (quarter start)")
    return f"{year}-Q{MONTH_TO_Q[month]}"


def read_rows(path: Path) -> list[tuple[float, str]]:
    rows = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln or ln.startswith("доля,") or "Итого" in ln:
            continue
        pct, _, name = ln.partition("\t")
        rows.append((parse_pct(pct), name.strip()))
    return rows


def load_learned() -> tuple[dict[str, str], dict[str, str]]:
    """name -> ticker (shares) and name -> type (other), from prior JSON output."""
    shares: dict[str, str] = {}
    other: dict[str, str] = {}
    for f in sorted(OUT_DIR.glob("*.json")):
        q = json.loads(f.read_text(encoding="utf-8"))
        for s in q.get("shares", ()):
            shares.setdefault(s["raw_name"], s["ticker"])
        for o in q.get("other", ()):
            # otc is a share that lost its price; keep resolving it via the share
            # path so canonical=null re-routes it, don't pin it as a plain `other` kind.
            if o.get("type") == "otc":
                if o.get("ticker"):  # hand-edited entry may lack it
                    shares.setdefault(o["raw_name"], o["ticker"])
                continue
            other.setdefault(o["raw_name"], o["type"])
    return shares, other


def classify(name: str, d: T.TickersDict, learned_sh: dict, learned_ot: dict):
    """-> ('other', kind) | ('share', ticker) | ('share', None) when unresolved."""
    kind = OTHER_KIND.get(name) or learned_ot.get(name)
    if kind:
        return "other", kind
    ticker = SHARE_TO_TICKER.get(name) or learned_sh.get(name) or T.resolve_alias(d, name)
    return "share", ticker


def build_quarter(path: Path, period: str, src: str, d, learned_sh, learned_ot) -> dict:
    shares, other, unknown = [], [], []
    for pct, name in read_rows(path):
        group, val = classify(name, d, learned_sh, learned_ot)
        if group == "other":
            other.append({"raw_name": name, "pct": pct, "type": val})
        elif val is None:
            unknown.append(name)
        else:
            canonical = d[val]["canonical"] if val in d else None
            if canonical is None:  # resolved ticker, no price series -> OTC, not investable
                other.append({"ticker": val, "raw_name": name, "pct": pct, "type": "otc"})
            else:
                shares.append({"ticker": val, "canonical": canonical, "raw_name": name, "pct": pct})
    if unknown:
        raise SystemExit(
            f"{path.name}: unresolved names {unknown}\n"
            "Add each to SHARE_TO_TICKER / OTHER_KIND / EXTERNAL in this script, then re-run."
        )
    total = sum(s["pct"] for s in shares)
    for s in shares:
        s["pct_shares_only"] = round(s["pct"] / total * 100, 2)
    return {
        "quarter": quarter_of(period),
        "period": period,
        "source": src,
        "shares": shares,
        "other": other,
    }


def augment_aliases(d: T.TickersDict) -> list[str]:
    log = []
    if "Аренадата" in d.get("DIAS", {}).get("aliases", []):  # belongs to DATA, not DIAS
        d["DIAS"]["aliases"].remove("Аренадата")
        log.append("DIAS: removed wrong alias 'Аренадата'")
    for name, ticker in SHARE_TO_TICKER.items():
        entry = d.get(ticker)
        if entry is None:
            continue
        aliases = entry.setdefault("aliases", [])
        if name.casefold() == entry["canonical"].casefold():
            continue
        if any(name.casefold() == a.casefold() for a in aliases):
            continue
        aliases.append(name)
        log.append(f"{ticker}: +alias {name!r}")
    return log


def write_report(quarters: list[dict]) -> None:
    seen: dict[str, dict] = {}
    for q in quarters:
        for s in q["shares"]:
            seen.setdefault(
                s["raw_name"],
                {"group": "share", "ticker": s["ticker"], "canonical": s["canonical"]},
            )
        for o in q["other"]:
            seen.setdefault(
                o["raw_name"], {"group": o["type"], "ticker": o.get("ticker"), "canonical": None}
            )
    lines = [
        "# Индекс Магов — name matching",
        "",
        "raw_name из txt → SECID + main (canonical из data/tickers.json).",
        "`—` = нет в словаре. Облигации/валюта/фонд/otc не идут в shares.",
        "",
        "| raw_name | группа | тикер | main (словарь) | прим. |",
        "|---|---|---|---|---|",
    ]
    for name in sorted(seen):
        m = seen[name]
        note = "вне ценового универса (OTC)" if m["group"] == "otc" else ""
        lines.append(
            f"| {name} | {m['group']} | {m['ticker'] or '—'} | {m['canonical'] or '—'} | {note} |"
        )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    d = T.load(DICT_PATH)
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    learned_sh, learned_ot = load_learned()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    quarters = []
    for path in sorted(IN_DIR.glob("mages_index_*.txt")):
        period = re.search(r"(\d{4}-\d{2})", path.name).group(1)
        if period not in sources:
            raise SystemExit(f"{path.name}: add {period!r} -> URL to {SOURCES_PATH.name}")
        q = build_quarter(path, period, sources[period], d, learned_sh, learned_ot)
        (OUT_DIR / f"{q['quarter']}.json").write_text(
            json.dumps(q, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        quarters.append(q)
        sh = sum(s["pct"] for s in q["shares"])
        print(
            f"{q['quarter']}.json: shares={len(q['shares'])} (Σ{sh:.2f}%) "
            f"other={len(q['other'])} src={q['source'][:48]}"
        )

    write_report(quarters)
    print(f"report -> {REPORT_PATH.relative_to(ROOT)}")

    log = augment_aliases(d)
    if log:
        T.validate_tickers(d)
        T.save(DICT_PATH, d)
        print(f"\ntickers.json: {len(log)} alias change(s)")
        for line in log:
            print(" ", line)
    else:
        print("\ntickers.json: no alias changes")


if __name__ == "__main__":
    main()
