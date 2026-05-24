"""CLI entry point. Subcommand modules are imported here to register their
typer decorators against the shared apps in `cli._app`.
"""

# Side-effect imports — each module registers commands on its typer subapp.
from cli import (  # noqa: F401, E402
    adjust_cmd,
    ingest_cmd,
    momentum_cmd,
    site_cmd,
    tickers_cmd,
)
from cli._app import app

__all__ = ["app"]


if __name__ == "__main__":
    app()
