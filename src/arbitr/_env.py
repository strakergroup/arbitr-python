"""Dotenv + env-var loading for client construction (no network)."""

from __future__ import annotations

import os
from pathlib import Path


def _unquote(value: str) -> str:
    """Strip one matched pair of surrounding quotes.

    Only a matched pair is removed, so a value that merely ends in a quote
    keeps it.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_env_file(path: str | Path) -> dict[str, str]:
    """Parse a KEY=VALUE dotenv file; missing files yield an empty dict.

    Understands ``export KEY=VALUE`` and ignores blank and ``#`` comment
    lines. Values are not expanded and inline comments are not stripped —
    a ``#`` inside a value is part of the value.
    """
    file_path = Path(path)
    values: dict[str, str] = {}
    if not file_path.is_file():
        return values
    for line in file_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].lstrip()
        key, value = stripped.split("=", 1)
        values[key.strip()] = _unquote(value.strip())
    return values


def pick_env_value(*names: str, file_vals: dict[str, str]) -> str | None:
    """Return the first non-empty value from os.environ, then the dotenv file.

    Every alias is checked in the environment before any dotenv value, so a
    file ``ARBITR_API_KEY`` cannot override an env ``arbitr_api_key``.
    """
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    for name in names:
        if file_vals.get(name):
            return file_vals[name]
    return None
