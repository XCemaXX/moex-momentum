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

    # The journal is a sequence of mutations, so two verdicts touching one row can
    # depend on their order — an augment re-adding what a later replace rewrote,
    # for one. A settled journal changes nothing on a second pass; anything else
    # is a contradiction that would corrupt the data a row at a time.
    recheck = apply_conflicts_to_universe(dividends_dir, conflicts_file)
    unsettled = sorted(t for t, r in recheck.items() if r.applied)
    if unsettled:
        typer.echo(
            f"conflicting verdicts for {', '.join(unsettled)} — the second pass still "
            f"changes the data, so the journal contradicts itself",
            err=True,
        )
        raise typer.Exit(1)


@corporate_app.command("check-registers")
def corporate_check_registers(
    dividends_dir: Path = typer.Option(Path("data/dividends"), "--dividends-dir"),
    prices_dir: Path = typer.Option(Path("data/prices_iss"), "--prices-dir"),
    acked_file: Path = typer.Option(Path("data/dividends/_acked_no_div.json"), "--acked-no-div"),
    since: str = typer.Option("2013-01-01", "--since"),
    until: str | None = typer.Option(None, "--until", help="Defaults to today."),
    strict: bool = typer.Option(False, "--strict"),
) -> None:
    """Report dividend registers MOEX recorded that we have no payout for.

    ISS no longer serves dividends, so a silent source failure now looks exactly
    like a share that stopped paying. This is the check that tells them apart.
    """
    from datetime import date

    import httpx

    from adjustments.dividend_gaps import load_acked
    from config import FILL_HTTP_TIMEOUT_SECONDS, FILL_USER_AGENT
    from ingest.dividends.register import REGISTER_URL, missing_payouts, parse_register

    try:
        resp = httpx.get(
            REGISTER_URL,
            timeout=FILL_HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": FILL_USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        typer.echo(f"register export unavailable: {exc}", err=True)
        raise typer.Exit(1) from exc

    register = parse_register(resp.content)
    if not register:
        typer.echo("register export parsed to zero rows — the format changed", err=True)
        raise typer.Exit(1)

    missing = missing_payouts(
        register,
        dividends_dir,
        prices_dir,
        acked=load_acked(acked_file),
        since=since,
        until=until or date.today().isoformat(),
    )
    for m in missing:
        typer.echo(f"  {m['record_date']}  {m['ticker']}", err=True)
    typer.echo(f"register closings without a stored payout: {len(missing)} of {len(register)}")
    if strict and missing:
        raise typer.Exit(1)
