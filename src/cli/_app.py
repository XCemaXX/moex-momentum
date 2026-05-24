"""Typer app instances + root callback + version. Shared by cli/*_cmd.py."""

from __future__ import annotations

from importlib.metadata import version as _pkg_version

import typer

from cli.logging_setup import setup_logging

__version__ = _pkg_version("moex-momentum")

app = typer.Typer(no_args_is_help=True, add_completion=False)
ingest_app = typer.Typer(no_args_is_help=True, help="Pull raw data from MOEX and other sources.")
corporate_app = typer.Typer(
    no_args_is_help=True, help="Dividends/splits — detector and application."
)
compute_app = typer.Typer(no_args_is_help=True, help="Signal computation and backtest.")
site_app = typer.Typer(no_args_is_help=True, help="Build static assets for GitHub Pages.")
tickers_app = typer.Typer(no_args_is_help=True, help="Ticker dictionary.")

app.add_typer(ingest_app, name="ingest")
app.add_typer(corporate_app, name="corporate")
app.add_typer(compute_app, name="compute")
app.add_typer(site_app, name="site")
app.add_typer(tickers_app, name="tickers")


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    setup_logging(verbose=verbose)


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)
