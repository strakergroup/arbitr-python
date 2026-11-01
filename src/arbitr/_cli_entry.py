"""Console-script entry point for ``arbitr``. Typer is the optional ``cli`` extra, so
this imports the CLI lazily and names the extra when it isn't installed."""

from __future__ import annotations

import sys

_MISSING_CLI_EXTRA = (
    "The arbitr command needs the CLI extra. Install it with:\n    pip install 'arbitr-sdk[cli]'"
)


def entrypoint() -> None:
    try:
        from arbitr.cli import app
    except ModuleNotFoundError as exc:
        if exc.name != "typer" and not (exc.name or "").startswith("typer."):
            raise
        print(_MISSING_CLI_EXTRA, file=sys.stderr)
        raise SystemExit(1) from None
    app()
