"""`momentum ingest *` subcommands: prices, splits, dividends, fill-dividends, indices."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from cli._app import ingest_app
from config import ISS_DIVIDEND_REFRESH_MONTHS


@ingest_app.command("prices")
def ingest_prices(
    output_dir: Path = typer.Option(Path("data/prices_iss"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    since: str | None = typer.Option(None, "--since"),
    refetch_from: str | None = typer.Option(
        None,
        "--refetch-from",
        help="Re-pull this date onward and replace the stored rows. Unlike --since "
        "it may reach back below the stored tail. Refuses to write if a day "
        "vanished or changed board.",
    ),
    refetch_till: str | None = typer.Option(
        None, "--refetch-till", help="Upper bound of the refetch window."
    ),
    allow_missing: bool = typer.Option(
        False, "--allow-missing", help="Apply a refetch even if stored days vanished."
    ),
    allow_board_change: bool = typer.Option(
        False,
        "--allow-board-change",
        help="Apply a refetch even where a date now resolves to a different board.",
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Re-fetch instead of reading the cache. The key carries the date "
        "window, so a plain re-run already picks up new days; this is for "
        "retrying the same day after a bad response.",
    ),
    max_concurrency: int = typer.Option(10, "--concurrency"),
) -> None:
    """Async ingest of daily quotes. Idempotent: a rerun pulls only the delta."""
    import asyncio

    import tickers as t_mod
    from ingest.prices import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)

    selected = list(ticker) if ticker else None
    since_d = date.fromisoformat(since) if since else None
    refetch_from_d = date.fromisoformat(refetch_from) if refetch_from else None
    refetch_till_d = date.fromisoformat(refetch_till) if refetch_till else None
    if refetch_from_d and since_d:
        typer.echo("--since and --refetch-from are mutually exclusive", err=True)
        raise typer.Exit(1)
    if refetch_till_d and not refetch_from_d:
        typer.echo("--refetch-till needs --refetch-from", err=True)
        raise typer.Exit(1)

    result = asyncio.run(
        ingest(
            tickers_dict,
            output_dir=output_dir,
            cache_dir=cache_dir,
            ticker_filter=selected,
            since=since_d,
            force=force_refresh,
            refetch_from=refetch_from_d,
            refetch_till=refetch_till_d,
            allow_missing=allow_missing,
            allow_board_change=allow_board_change,
            max_concurrency=max_concurrency,
        )
    )

    typer.echo(f"prices ingested: {sum(1 for m in result.values() if m.rows > 0)} tickers")

    if refetch_from_d is not None:
        reports = {t: m.refetch for t, m in result.items() if m.refetch is not None}
        added = sum(r.added for r in reports.values())
        changed = sum(r.changed for r in reports.values())
        refused = sorted(t for t, r in reports.items() if r.refused)
        moved = sum(len(r.board_changed) for r in reports.values())
        typer.echo(
            f"refetch: {added} row(s) added, {changed} changed, {moved} moved to another board"
        )
        for t_ in refused:
            r = reports[t_]
            typer.echo(
                f"  {t_}: refused — {len(r.missing)} vanished, "
                f"{len(r.board_changed)} changed board",
                err=True,
            )
        if refused:
            typer.echo(
                f"{len(refused)} ticker(s) left untouched; inspect them, then re-run with "
                "--allow-missing / --allow-board-change to accept",
                err=True,
            )
            raise typer.Exit(1)

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
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Re-fetch the ISS splits endpoint. Its cache key has no date, so a plain "
        "re-run replays the first snapshot ever taken.",
    ),
) -> None:
    """Ingest splits from MOEX ISS + bonus issues from tickers_manual.json. Idempotent."""
    import tickers as t_mod
    from ingest.splits import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)
    manual = t_mod.load_manual(manual_file)

    counts = ingest(
        tickers_dict,
        manual,
        output_dir=output_dir,
        cache_dir=cache_dir,
        force_refresh=force_refresh,
    )

    typer.echo(f"splits ingested: {len(counts)} tickers")


def since_from_months(months: int, today: date) -> date | None:
    """First day of the month `months` back from `today`. 0 or less → no bound."""
    if months <= 0:
        return None
    mo = today.month - months
    yr = today.year
    while mo <= 0:
        mo += 12
        yr -= 1
    return date(yr, mo, 1)


@ingest_app.command("dividends")
def ingest_dividends(
    output_dir: Path = typer.Option(Path("data/dividends"), "--output-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
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

    import tickers as t_mod
    from adjustments.dividend_gaps import compute_gaps, load_acked, save_gaps
    from ingest.dividends.iss import ingest

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)

    since_d = since_from_months(months, date.today())

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

    n_fetched = sum(m.fetched for m in result.values())
    n_missing = sum(1 for m in result.values() if m.block_missing)

    if selected is None:
        acked = load_acked(acked_file)
        gaps = compute_gaps(prices_dir, output_dir, acked=acked)
        save_gaps(gaps_file, gaps)
        typer.echo(
            f"dividends fetched: {n_fetched} rows over {len(result)} tickers; "
            f"gaps: {len(gaps)} → {gaps_file}"
        )
    else:
        typer.echo(
            f"dividends fetched: {n_fetched} rows over {len(selected)} ticker(s); "
            "gaps regen skipped (partial run)"
        )

    # A missing block is a source failure, not an empty history, so it must not
    # pass as a successful run — see task 054.
    if result and n_missing == len(result):
        typer.echo(
            f"ISS returned no dividends block for any of {len(result)} tickers — "
            "the endpoint is gone, nothing was ingested "
            "(the cache holds the broken response; retry with --force-refresh)",
            err=True,
        )
        raise typer.Exit(1)
    if n_missing:
        typer.echo(
            f"warning: no dividends block for {n_missing}/{len(result)} tickers",
            err=True,
        )


@ingest_app.command("fill-dividends")
def ingest_fill_dividends(
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    manual_file: Path = typer.Option(Path("data/tickers_manual.json"), "--manual"),
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    prices_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-dir"),
    splits_dir: Path = typer.Option(Path("data/splits"), "--splits-dir"),
    cache_dir: Path = typer.Option(Path(".fill_cache"), "--cache-dir"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    sources: str = typer.Option(
        "dohod,smartlab",
        "--sources",
        help="Comma-separated subset of {dohod, smartlab} in tier order. "
        "yahoo/tbank land in task 012 phase 2.",
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Re-fetch source pages instead of reusing the no-TTL cache. "
        "Required on a monthly run — a stale snapshot hides newly declared payouts.",
    ),
) -> None:
    """Augment `data/dividends/{T}.csv` from dohod.

    Records earlier than `predecessor_cutoff(ticker)` are dropped — see task 005.
    Idempotent: stored records are never rewritten. A fetched row that disagrees
    with a stored one is reported as a conflict, not written.
    """
    import time

    import httpx

    import tickers as t_mod
    from config import FILL_HTTP_TIMEOUT_SECONDS, FILL_REQUEST_DELAY_SECONDS, FILL_USER_AGENT
    from ingest.dividends.conflicts import _load_conflicts
    from ingest.dividends.dohod import DohodFetcher
    from ingest.dividends.fill import fill_dividends
    from ingest.dividends.iss import _merge
    from ingest.dividends.smartlab import SmartLabFetcher
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
        time.sleep(FILL_REQUEST_DELAY_SECONDS)
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

    ignore_entries = [
        c
        for c in _load_conflicts(dividends_dir / "_conflicts_resolved.json")
        if c.get("action") == "ignore"
    ]

    source_set = {s.strip() for s in sources.split(",") if s.strip()}
    fetchers: list[object] = []
    if "dohod" in source_set:
        fetchers.append(DohodFetcher(http_get, cache_dir=cache_dir, force_refresh=force_refresh))
    if "smartlab" in source_set:
        fetchers.append(SmartLabFetcher(http_get, cache_dir=cache_dir, force_refresh=force_refresh))

    try:
        for tk in ticker:
            result = fill_dividends(
                tk,
                fetchers=fetchers,  # type: ignore[arg-type]
                tickers_dict=tickers_dict,
                tickers_manual=manual,
                prices_dir=prices_dir,
                dividends_dir=dividends_dir,
                splits_dir=splits_dir,
                ignore_entries=ignore_entries,
            )
            typer.echo(
                f"{tk}: cutoff={result.cutoff or '-'} new={result.n_new} "
                f"pre_cutoff_dropped={result.n_pre_cutoff_dropped} "
                f"duplicates_dropped={result.n_duplicates_dropped} "
                f"future_dropped={result.n_future_dropped} "
                f"foreign_dropped={result.n_foreign_dropped} "
                f"conflicts={len(result.conflicts)} "
                f"conflicts_ignored={result.n_conflicts_ignored} "
                f"by_source={result.by_source}"
            )
            for c in result.conflicts:
                typer.echo(
                    f"  CONFLICT {tk} {c['registry_close']} {c['amount']} "
                    f"{c.get('currency') or 'RUB'} {c.get('source')} "
                    f"— resolve in data/dividends/_conflicts_resolved.json"
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
    secid: list[str] = typer.Option(["MCFTRR"], "--secid", "-s"),
    since: str | None = typer.Option(None, "--since"),
    refetch_from: str | None = typer.Option(
        None,
        "--refetch-from",
        help="Re-pull this date onward and replace the stored rows. Unlike --since "
        "it may reach back below the stored tail. Refuses to write if a day vanished.",
    ),
    refetch_till: str | None = typer.Option(
        None, "--refetch-till", help="Upper bound of the refetch window."
    ),
    allow_missing: bool = typer.Option(
        False, "--allow-missing", help="Apply a refetch even if stored days vanished."
    ),
    force_refresh: bool = typer.Option(
        False,
        "--force-refresh",
        help="Re-fetch instead of reading the cache. The key carries the date "
        "window, so a plain re-run already picks up new days; this is for "
        "retrying the same day after a bad response.",
    ),
) -> None:
    """Ingest MOEX index series (default: MCFTRR). Idempotent: rerun pulls only the delta."""
    import asyncio

    from ingest.indices import ingest

    since_d = date.fromisoformat(since) if since else None
    refetch_from_d = date.fromisoformat(refetch_from) if refetch_from else None
    refetch_till_d = date.fromisoformat(refetch_till) if refetch_till else None
    if refetch_from_d and since_d:
        typer.echo("--since and --refetch-from are mutually exclusive", err=True)
        raise typer.Exit(1)
    result = asyncio.run(
        ingest(
            list(secid),
            output_dir=output_dir,
            cache_dir=cache_dir,
            since=since_d,
            force=force_refresh,
            refetch_from=refetch_from_d,
            refetch_till=refetch_till_d,
            allow_missing=allow_missing,
        )
    )

    typer.echo(f"indices ingested: {sum(1 for m in result.values() if m.rows > 0)} series")
