"""`momentum ingest *` subcommands: prices, splits, dividends, fill-dividends, indices."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cli._app import ingest_app
from config import ISS_DIVIDEND_REFRESH_MONTHS


@ingest_app.command("prices")
def ingest_prices(
    output_dir: Path = typer.Option(Path("data/prices_iss"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    since: str | None = typer.Option(None, "--since"),
    max_concurrency: int = typer.Option(10, "--concurrency"),
) -> None:
    """Async ingest of daily quotes. Idempotent: a rerun pulls only the delta."""
    import asyncio
    from datetime import date

    import tickers as t_mod
    from ingest.prices import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)

    selected = list(ticker) if ticker else None
    since_d = date.fromisoformat(since) if since else None

    result = asyncio.run(
        ingest(
            tickers_dict,
            output_dir=output_dir,
            cache_dir=cache_dir,
            ticker_filter=selected,
            since=since_d,
            max_concurrency=max_concurrency,
        )
    )

    manifest: dict[str, dict[str, dict[str, object]]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    prices_section = manifest.setdefault("prices", {})
    for t, m in result.items():
        if m.rows == 0:
            continue
        entry: dict[str, object] = {
            "first": m.first,
            "last": m.last,
            "rows": m.rows,
        }
        if m.fallback_boards:
            entry["fallback_boards"] = m.fallback_boards
        if m.segments_empty:
            entry["segments_empty"] = m.segments_empty
        prices_section[t] = entry
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)
    typer.echo(f"prices ingested: {sum(1 for m in result.values() if m.rows > 0)} tickers")

    # Auto-invoke detector on full ingest (WARN-only). Skip if splits not yet ingested.
    if selected is None:
        splits_dir = Path("data/splits")
        has_splits = splits_dir.exists() and any(splits_dir.glob("*.csv"))
        if has_splits:
            from adjustments.detect import run_all, save_suspicious

            suspicions = run_all(
                prices_iss_dir=output_dir,
                dividends_dir=Path("data/dividends"),
                splits_dir=splits_dir,
                acked_path=Path("data/splits/_acked.json"),
            )
            save_suspicious(Path("data/splits/_suspicious.json"), suspicions)
            if suspicions:
                typer.echo(
                    f"detector: {len(suspicions)} suspicion(s) — see data/splits/_suspicious.json",
                    err=True,
                )


@ingest_app.command("splits")
def ingest_splits(
    output_dir: Path = typer.Option(Path("data/splits"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    manual_file: Path = typer.Option(Path("data/tickers_manual.json"), "--manual"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
) -> None:
    """Ingest splits from MOEX ISS + bonus issues from tickers_manual.json. Idempotent."""
    import tickers as t_mod
    from ingest.splits import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)
    manual = t_mod.load_manual(manual_file)

    counts = ingest(tickers_dict, manual, output_dir=output_dir, cache_dir=cache_dir)

    manifest: dict[str, dict[str, dict[str, object]]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    section = manifest.setdefault("splits", {})
    for tk, n in counts.items():
        section[tk] = {"rows": n}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)
    typer.echo(f"splits ingested: {len(counts)} tickers")


@ingest_app.command("dividends")
def ingest_dividends(
    output_dir: Path = typer.Option(Path("data/dividends"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
    acked_file: Path = typer.Option(Path("data/dividends/_acked_no_div.json"), "--acked-no-div"),
    gaps_file: Path = typer.Option(Path("data/dividends/_gaps.json"), "--gaps"),
    prices_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-dir"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    months: int = typer.Option(
        ISS_DIVIDEND_REFRESH_MONTHS,
        "--months",
        help="Merge only ISS rows with registry_close within the last N months "
        "(0 = full history). Keeps a re-run from re-introducing old ISS near-dups "
        "that curation already dropped.",
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", help="Re-fetch past the dividends cache (no TTL)."
    ),
    max_concurrency: int = typer.Option(10, "--concurrency"),
) -> None:
    """Async ingest of dividends from MOEX ISS. Idempotent.

    Without `--ticker` (full ingest), `_gaps.json` is regenerated from prices vs
    dividends ranges, filtered by `_acked_no_div.json`. ISS lags months behind on
    dividends; recent payouts come from `fill-dividends` + `corporate apply-conflicts`.
    """
    import asyncio
    from datetime import date

    import tickers as t_mod
    from adjustments.dividend_gaps import compute_gaps, load_acked, save_gaps
    from ingest.dividends.iss import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)

    since_d: date | None = None
    if months > 0:
        today = date.today()
        mo = today.month - months
        yr = today.year
        while mo <= 0:
            mo += 12
            yr -= 1
        since_d = date(yr, mo, 1)

    selected = list(ticker) if ticker else None
    result = asyncio.run(
        ingest(
            tickers_dict,
            output_dir=output_dir,
            cache_dir=cache_dir,
            ticker_filter=selected,
            since=since_d,
            force=force_refresh,
            max_concurrency=max_concurrency,
        )
    )

    manifest: dict[str, dict[str, dict[str, object]]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    section = manifest.setdefault("dividends", {})
    for tk, m in result.items():
        if m.rows == 0:
            continue
        section[tk] = {"first": m.first, "last": m.last, "rows": m.rows}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)

    if selected is None:
        acked = load_acked(acked_file)
        gaps = compute_gaps(prices_dir, output_dir, acked=acked)
        save_gaps(gaps_file, gaps)
        typer.echo(
            f"dividends ingested: {sum(1 for m in result.values() if m.rows > 0)} tickers; "
            f"gaps: {len(gaps)} → {gaps_file}"
        )
    else:
        typer.echo(
            f"dividends ingested for {len(selected)} ticker(s); gaps regen skipped (partial run)"
        )


@ingest_app.command("fill-dividends")
def ingest_fill_dividends(
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    manual_file: Path = typer.Option(Path("data/tickers_manual.json"), "--manual"),
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    prices_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache"), "--cache-dir"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    sources: str = typer.Option(
        "dohod",
        "--sources",
        help="Comma-separated subset of {dohod} in tier order. "
        "yahoo/tbank land in task 012 phase 2.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Augment `data/dividends/{T}.csv` from dohod.

    Records earlier than `predecessor_cutoff(ticker)` are dropped — see task 005.
    Idempotent: existing records win on dedup-key collision.
    """
    import httpx

    import tickers as t_mod
    from config import FILL_HTTP_TIMEOUT_SECONDS, FILL_USER_AGENT
    from ingest.dividends.dohod import DohodFetcher
    from ingest.dividends.fill import fill_dividends
    from ingest.dividends.iss import _merge
    from storage.records import read_records, write_records_atomic
    from storage.schemas import DIV_CASTS, DIV_FIELDS

    if not ticker:
        typer.echo("--ticker is required (one or more)", err=True)
        raise typer.Exit(1)
    tickers_dict = t_mod.load(tickers_file)
    manual = t_mod.load_manual(manual_file)

    client = httpx.Client(
        timeout=FILL_HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": FILL_USER_AGENT},
        follow_redirects=True,
    )

    def http_get(url: str) -> str | None:
        try:
            resp = client.get(url)
        except httpx.HTTPError as exc:
            typer.echo(f"HTTP error {url}: {exc}", err=True)
            return None
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            typer.echo(f"HTTP {resp.status_code} {url}", err=True)
            return None
        return resp.text

    source_set = {s.strip() for s in sources.split(",") if s.strip()}
    fetchers: list[object] = []
    if "dohod" in source_set:
        fetchers.append(DohodFetcher(http_get, cache_dir=cache_dir))

    try:
        for tk in ticker:
            result = fill_dividends(
                tk,
                fetchers=fetchers,  # type: ignore[arg-type]
                tickers_dict=tickers_dict,
                tickers_manual=manual,
                prices_dir=prices_dir,
                dividends_dir=dividends_dir,
            )
            typer.echo(
                f"{tk}: cutoff={result.cutoff or '-'} new={result.n_new} "
                f"pre_cutoff_dropped={result.n_pre_cutoff_dropped} "
                f"near_dup_dropped={result.n_near_dup_dropped} "
                f"by_source={result.by_source}"
            )
            if dry_run or result.n_new == 0:
                continue
            out_path = dividends_dir / f"{tk}.csv"
            existing = read_records(out_path, casts=DIV_CASTS)
            new_recs = result.records
            merged = _merge(existing, new_recs)
            write_records_atomic(out_path, merged, fieldnames=DIV_FIELDS)
    finally:
        client.close()


@ingest_app.command("indices")
def ingest_indices(
    output_dir: Path = typer.Option(Path("data/indices"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
    secid: list[str] = typer.Option(["MCFTRR"], "--secid", "-s"),
    since: str | None = typer.Option(None, "--since"),
) -> None:
    """Ingest MOEX index series (default: MCFTRR). Idempotent: rerun pulls only the delta."""
    import asyncio
    from datetime import date

    from ingest.indices import ingest

    since_d = date.fromisoformat(since) if since else None
    result = asyncio.run(
        ingest(
            list(secid),
            output_dir=output_dir,
            cache_dir=cache_dir,
            since=since_d,
        )
    )

    manifest: dict[str, dict[str, dict[str, object]]] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    section = manifest.setdefault("indices", {})
    for s, m in result.items():
        if m.rows == 0:
            continue
        section[s] = {"first": m.first, "last": m.last, "rows": m.rows}
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(manifest_path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(manifest_path)
    typer.echo(f"indices ingested: {sum(1 for m in result.values() if m.rows > 0)} series")
