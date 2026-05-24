"""`momentum site build` — render GitHub Pages site."""

from __future__ import annotations

from pathlib import Path

import typer

from cli._app import site_app


@site_app.command("build")
def site_build(
    signal: str = typer.Option("curve_fit", "--signal", help="curve_fit|simple"),
    computed_dir: Path = typer.Option(Path("data/momentum"), "--computed-dir"),
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    out_dir: Path = typer.Option(Path("docs/pages"), "--out"),
    methodology_md: Path | None = typer.Option(
        None, "--methodology", help="Path to methodology.md (default: docs/methodology.md)"
    ),
    bundle: Path | None = typer.Option(
        None, "--bundle", help="Path to plotly.min.js (default: docs/pages/plotly.min.js)"
    ),
) -> None:
    """Render the GitHub Pages site into `--out`.

    Pages written: index.html, q1_q4_dynamics.html, q1_minus_mcftrr.html,
    transitions.html, q_history.html, methodology.html, and compare.html
    (when both signals + sweep are present). Plus data.json (per-month
    Q-составы) and plotly.min.js (shared bundle).
    """
    from viz.site_builder import (
        build_site,
        default_bundle_path,
        default_methodology_path,
    )

    q_path = computed_dir / signal / "q_values.csv"
    holdings_dir = computed_dir / signal / "holdings"
    if not q_path.exists():
        typer.echo(f"{q_path} not found — run `momentum compute backtest --signal {signal}` first")
        raise typer.Exit(1)
    if not holdings_dir.exists():
        typer.echo(f"{holdings_dir} not found — backtest output incomplete")
        raise typer.Exit(1)

    md = methodology_md or default_methodology_path()
    if not md.exists():
        typer.echo(f"{md} not found")
        raise typer.Exit(1)
    bundle_src = bundle or default_bundle_path()
    if not bundle_src.exists():
        typer.echo(f"{bundle_src} not found — run scripts/build_plotly_bundle/build.sh")
        raise typer.Exit(1)

    # Explorer page (compare.html) is signal-independent: needs both signals +
    # the weight-sweep. Rendered only when all three exist (CI computes them).
    simple_q = computed_dir / "simple" / "q_values.csv"
    curve_fit_q = computed_dir / "curve_fit" / "q_values.csv"
    sweep_q = computed_dir / "sweep" / "q1_nav.csv"
    compare_ready = simple_q.exists() and curve_fit_q.exists() and sweep_q.exists()
    if not compare_ready:
        typer.echo(
            "note: compare.html skipped — needs data/momentum/{simple,curve_fit}/q_values.csv "
            "+ sweep/q1_nav.csv (run `momentum compute backtest` for both signals and "
            "`python scripts/compute_weight_sweep.py`)"
        )

    # Pending-inclusion block + universe cutoff (task 008): pending.json is only
    # written by the curve_fit backtest. universe_meta is written per-signal-dir,
    # but its content is signal-independent (read from the active signal's dir).
    pending_path = computed_dir / signal / "pending.json"
    universe_meta_path = computed_dir / signal / "universe_meta.csv"

    pages = build_site(
        q_values_path=q_path,
        holdings_dir=holdings_dir,
        tickers_path=tickers_file,
        methodology_md=md,
        bundle_src=bundle_src,
        out_dir=out_dir,
        signal=signal,
        compare_simple_path=simple_q if compare_ready else None,
        compare_curve_fit_path=curve_fit_q if compare_ready else None,
        compare_sweep_path=sweep_q if compare_ready else None,
        pending_path=pending_path if pending_path.exists() else None,
        universe_meta_path=universe_meta_path if universe_meta_path.exists() else None,
    )
    typer.echo(f"site {signal}: {len(pages)} artefacts → {out_dir}")
