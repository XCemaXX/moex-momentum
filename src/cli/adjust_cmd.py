"""`momentum corporate *` — corporate-action detector."""

from __future__ import annotations

from pathlib import Path

import typer

from cli._app import corporate_app


@corporate_app.command("detect")
def corporate_detect(
    prices_iss_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-iss-dir"),
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    splits_dir: Path = typer.Option(Path("data/splits"), "--splits-dir"),
    acked_file: Path = typer.Option(Path("data/splits/_acked.json"), "--acked"),
    suspicious_file: Path = typer.Option(Path("data/splits/_suspicious.json"), "--out"),
    strict: bool = typer.Option(False, "--strict"),
) -> None:
    """Run the corporate-action detector. `--strict` exits non-zero if any suspicion remains."""
    from adjustments.detect import run_all, save_suspicious

    suspicions = run_all(
        prices_iss_dir=prices_iss_dir,
        dividends_dir=dividends_dir,
        splits_dir=splits_dir,
        acked_path=acked_file,
    )
    save_suspicious(suspicious_file, suspicions)
    for s in suspicions:
        typer.echo(
            f"{s.ticker} {s.date} ret={s.raw_return:+.3f} value={s.daily_value_rub:.0f} RUB",
            err=True,
        )
    typer.echo(f"detect: {len(suspicions)} suspicion(s) → {suspicious_file}")
    if strict and suspicions:
        raise typer.Exit(1)
