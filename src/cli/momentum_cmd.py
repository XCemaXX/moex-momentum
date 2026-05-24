"""`momentum compute *` — signal computation + backtest."""

from __future__ import annotations

from pathlib import Path

import typer

from cli._app import compute_app
from config import UNIVERSE_TOP_N_LIQUID


@compute_app.command("monthly")
def compute_monthly(
    prices_iss_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-iss-dir"),
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    splits_dir: Path = typer.Option(Path("data/splits"), "--splits-dir"),
    output_dir: Path = typer.Option(Path("data/momentum/monthly"), "--output-dir"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    from_scratch: bool = typer.Option(
        False,
        "--from-scratch",
        help="Skip pre-tail hash gate, rebless baseline. Use after dividend/split backfill.",
    ),
) -> None:
    """Build per-ticker monthly total-return JSONL. Pre-tail safety gate active by default."""
    from momentum.pipeline import IncrementalDriftError, compute_all, write_manifest_section

    selected = list(ticker) if ticker else None
    try:
        result = compute_all(
            prices_iss_dir=prices_iss_dir,
            dividends_dir=dividends_dir,
            splits_dir=splits_dir,
            output_dir=output_dir,
            ticker_filter=selected,
            from_scratch=from_scratch,
        )
    except IncrementalDriftError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    write_manifest_section(manifest_path, result)
    written = sum(1 for m in result.values() if m.rows > 0)
    typer.echo(f"monthly computed: {written} tickers → {output_dir}")


@compute_app.command("backtest")
def compute_backtest(
    signal: str = typer.Option("curve_fit", "--signal", help="curve_fit|simple"),
    monthly_dir: Path = typer.Option(Path("data/momentum/monthly"), "--monthly-dir"),
    indices_dir: Path = typer.Option(Path("data/indices"), "--indices-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    output_dir: Path = typer.Option(Path("data/momentum"), "--output-dir"),
    start: str | None = typer.Option(None, "--start", help="YYYY-MM inclusive"),
    end: str | None = typer.Option(None, "--end", help="YYYY-MM inclusive"),
    top_n: int = typer.Option(
        UNIVERSE_TOP_N_LIQUID,
        "--top-n",
        help="Universe = the N most liquid names each month. 0 keeps all eligible names.",
    ),
) -> None:
    """Run the quartile backtest for the given signal. Writes
    `<output_dir>/<signal>/q_values.csv`, per-month holdings JSON, and
    `universe_meta.csv` (per-month name count + effective liquidity cut)."""
    import pandas as pd

    import tickers as t_mod
    from config import ANALYSIS_START_DATE
    from momentum.backtest import backtest, write_backtest
    from momentum.signals import SIGNALS

    if signal not in SIGNALS:
        typer.echo(f"unknown signal {signal!r}; valid: {sorted(SIGNALS)}")
        raise typer.Exit(2)
    sig = SIGNALS[signal]

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first")
        raise typer.Exit(1)

    start_p = pd.Period(start, freq="M") if start else pd.Period(ANALYSIS_START_DATE, freq="M")
    end_p = pd.Period(end, freq="M") if end else None

    result = backtest(
        sig,
        monthly_dir=monthly_dir,
        indices_dir=indices_dir,
        tickers_dict=tickers_dict,
        start=start_p,
        end=end_p,
        universe_top_n=top_n if top_n > 0 else None,
    )
    out = output_dir / signal
    # pending.json (task 008) only for curve_fit: the block compares against
    # curve_fit boundaries and sits under the curve_fit holdings columns.
    write_backtest(result, output_dir=out, write_pending=(signal == "curve_fit"))
    typer.echo(
        f"backtest {signal}: {len(result.q_values)} months, "
        f"{len(result.holdings)} rebalances → {out}"
    )
