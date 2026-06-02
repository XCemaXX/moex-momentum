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


@corporate_app.command("apply-conflicts")
def corporate_apply_conflicts(
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    conflicts_file: Path = typer.Option(
        Path("data/dividends/_conflicts_resolved.json"), "--conflicts"
    ),
) -> None:
    """Apply `_conflicts_resolved.json` (drop/replace/augment) to dividend files.

    Idempotent. Drops known ISS near-dups outside the near-dup window and applies
    curated corrections. Run after `ingest dividends`."""
    from ingest.dividends.conflicts import apply_conflicts_to_universe

    results = apply_conflicts_to_universe(dividends_dir, conflicts_file)
    applied = sum(r.applied for r in results.values())
    touched = sum(1 for r in results.values() if r.applied)
    typer.echo(f"conflicts: {applied} change(s) across {touched} ticker(s)")
