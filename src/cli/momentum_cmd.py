"""`momentum compute *` — signal computation + backtest."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import typer

from cli._app import compute_app
from config import UNIVERSE_TOP_N_LIQUID

if TYPE_CHECKING:
    import pandas as pd

    from momentum.topn_fan import Panels
    from tickers import TickersDict


@compute_app.command("monthly")
def compute_monthly(
    prices_iss_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-iss-dir"),
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    splits_dir: Path = typer.Option(Path("data/splits"), "--splits-dir"),
    output_dir: Path = typer.Option(Path("data/momentum/monthly"), "--output-dir"),
    ticker: list[str] = typer.Option([], "--ticker", "-t"),
    from_scratch: bool = typer.Option(
        False,
        "--from-scratch",
        help="Skip pre-tail hash gate, rebless baseline. Use after dividend/split backfill.",
    ),
    as_of: str | None = typer.Option(
        None,
        "--as-of",
        help="YYYY-MM-DD cutoff for the in-progress month. Default: derived from the price tree.",
    ),
) -> None:
    """Build per-ticker monthly total-return CSV. Pre-tail safety gate active by default."""
    import pandas as pd

    from momentum.pipeline import IncrementalDriftError, compute_all

    selected = list(ticker) if ticker else None
    as_of_ts = pd.Timestamp(as_of) if as_of else None
    try:
        result = compute_all(
            prices_iss_dir=prices_iss_dir,
            dividends_dir=dividends_dir,
            splits_dir=splits_dir,
            output_dir=output_dir,
            ticker_filter=selected,
            from_scratch=from_scratch,
            as_of=as_of_ts,
        )
    except IncrementalDriftError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
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
        with_pending=(signal == "curve_fit"),
    )
    out = output_dir / signal
    # pending.json (task 008) only for curve_fit: the block compares against
    # curve_fit boundaries and sits under the curve_fit holdings columns.
    write_backtest(result, output_dir=out, write_pending=(signal == "curve_fit"))
    typer.echo(
        f"backtest {signal}: {len(result.q_values)} months, "
        f"{len(result.holdings)} rebalances → {out}"
    )


def _research_inputs(
    tickers_file: Path, monthly_dir: Path
) -> tuple[TickersDict, Panels, pd.Period]:
    import pandas as pd

    import tickers as t_mod
    from config import ANALYSIS_START_DATE
    from momentum.universe import load_panel

    tickers_dict = t_mod.load(tickers_file)
    if not tickers_dict:
        typer.echo(f"{tickers_file} is empty — run `momentum tickers refresh` first", err=True)
        raise typer.Exit(1)
    panels = load_panel(monthly_dir)
    if panels[0].empty:
        typer.echo(f"no monthly panel at {monthly_dir} — run `momentum compute monthly`", err=True)
        raise typer.Exit(1)
    return tickers_dict, panels, pd.Period(ANALYSIS_START_DATE, freq="M")


@compute_app.command("sweep")
def compute_sweep(
    monthly_dir: Path = typer.Option(Path("data/momentum/monthly"), "--monthly-dir"),
    indices_dir: Path = typer.Option(Path("data/indices"), "--indices-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    out_file: Path = typer.Option(Path("data/momentum/sweep/q1_nav.csv"), "--out-file"),
) -> None:
    """Q1 NAV across the a/b weight grid, for the Experiments page."""
    from momentum.research import A_WEIGHTS, weight_sweep, write_nav_csv

    tickers_dict, panels, start = _research_inputs(tickers_file, monthly_dir)
    frame = weight_sweep(
        panels, tickers_dict, monthly_dir=monthly_dir, indices_dir=indices_dir, start=start
    )
    n = write_nav_csv(out_file, frame)
    typer.echo(f"sweep: {n} months × {len(A_WEIGHTS)} weights → {out_file}")


@compute_app.command("fan")
def compute_fan(
    monthly_dir: Path = typer.Option(Path("data/momentum/monthly"), "--monthly-dir"),
    indices_dir: Path = typer.Option(Path("data/indices"), "--indices-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    reference_q_values: Path = typer.Option(
        Path("data/momentum/curve_fit/q_values.csv"),
        "--reference-q-values",
        help="Published curve_fit q_values.csv; the baseline run must reproduce its Q1.",
    ),
    out_file: Path = typer.Option(
        Path("data/momentum/topn_fan/fan_concentration.csv"), "--out-file"
    ),
) -> None:
    """Top-K concentration fan over the fixed liquid universe."""
    import pandas as pd

    from momentum.research import concentration_fan, write_nav_csv

    tickers_dict, panels, start = _research_inputs(tickers_file, monthly_dir)
    reference = (
        pd.read_csv(reference_q_values).set_index("month")["Q1"]
        if reference_q_values.exists()
        else None
    )
    try:
        frame = concentration_fan(
            panels,
            tickers_dict,
            monthly_dir=monthly_dir,
            indices_dir=indices_dir,
            start=start,
            reference_q1=reference,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    n = write_nav_csv(out_file, frame)
    typer.echo(f"fan: {n} months × {len(frame.columns) - 1} curves → {out_file}")
