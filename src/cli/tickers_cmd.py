"""`momentum tickers *` — refresh dictionary, mark-unavailable."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from cli._app import tickers_app


@tickers_app.command("mark-unavailable")
def tickers_mark_unavailable(
    tickers_file: Path = typer.Option(Path("data/tickers.json"), "--tickers"),
    unavailable_file: Path = typer.Option(Path("data/tickers_unavailable.jsonl"), "--unavailable"),
    manifest_path: Path = typer.Option(Path("data/manifest.json"), "--manifest"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Move tickers with rows=0 from tickers.json to tickers_unavailable.jsonl.

    Source of truth is `data/manifest.json`. A ticker absent from `manifest.prices`
    is treated as "ISS returns no history" — moved to the unavailable file and
    removed from the main dictionary. Bootstrap then skips them at the listing stage.
    """
    import tickers as t_mod

    if not manifest_path.exists():
        typer.echo(f"{manifest_path} does not exist — run `momentum ingest prices` first")
        raise typer.Exit(1)

    tickers_dict = t_mod.load(tickers_file)
    unavailable = t_mod.load_unavailable(unavailable_file)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    have = set(manifest.get("prices", {}).keys())
    to_move = [t for t in tickers_dict if t not in have]

    if not to_move:
        typer.echo("nothing to move")
        return
    sample = ", ".join(to_move[:10])
    suffix = "..." if len(to_move) > 10 else ""
    typer.echo(f"will move {len(to_move)} tickers: {sample}{suffix}")
    if dry_run:
        return
    for t in to_move:
        unavailable[t] = {"reason": "ISS empty for all boards"}
        del tickers_dict[t]
    t_mod.validate_tickers(tickers_dict)
    t_mod.save(tickers_file, tickers_dict)
    t_mod.save_unavailable(unavailable_file, unavailable)
    typer.echo(f"moved {len(to_move)} → {unavailable_file}; tickers.json: {len(tickers_dict)}")


@tickers_app.command("refresh")
def tickers_refresh(
    output: Path = typer.Option(Path("data/tickers.json"), "--output", "-o"),
    unavailable_file: Path = typer.Option(Path("data/tickers_unavailable.jsonl"), "--unavailable"),
    seed_aliases: Path | None = typer.Option(None, "--seed-aliases"),
    cache_dir: Path = typer.Option(Path(".fill_cache/iss"), "--cache-dir"),
) -> None:
    """ISS bootstrap of the ticker dictionary.

    SECIDs from `tickers_unavailable.jsonl` are skipped at the listing stage and
    not returned to the main dictionary. All ISS responses are cached under
    `--cache-dir` (default `.fill_cache/iss/`). To force a refetch, delete cache-dir.
    """
    import tickers as t
    from ingest.dictionary import (
        bootstrap,
        make_iss_client,
        merge_external_aliases,
    )

    existing = t.load(output)
    skip = frozenset(t.load_unavailable(unavailable_file).keys())
    with make_iss_client() as client:
        updated = bootstrap(existing, client=client, cache_dir=cache_dir, skip_secids=skip)
    if seed_aliases is not None:
        seed = json.loads(seed_aliases.read_text(encoding="utf-8"))
        updated = merge_external_aliases(updated, seed)
    t.validate_tickers(updated)
    t.save(output, updated)
    typer.echo(f"saved {len(updated)} tickers → {output} (skipped {len(skip)} unavailable)")
