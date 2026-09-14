"""Fail if the packaged OpenAPI pin differs from live production.

Compares ``src/arbitr/openapi.json`` (via ``pinned_spec()``) to
``PROD_OPENAPI_URL``. Pytest stays offline; this script is the scheduled
CI entrypoint.

    uv run python scripts/check_pinned_spec.py
    uv run python scripts/check_pinned_spec.py --other-file /tmp/openapi.json
    uv run python scripts/check_pinned_spec.py --write-pin

Exit 0 if they match after canonicalize, 1 on drift, 2 when the live
spec is unreadable (CI retries), 3 on unexpected script failures, 4 when
the packaged pin is unreadable (fail immediately; not a prod flake).

``--write-pin`` copies the live (or ``--other-file``) document onto
``src/arbitr/openapi.json`` when they differ, then exits 0 so CI can
regenerate models and open a pull request. Drift without ``--write-pin``
still exits 1 and does not touch the pin file.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import httpx

from arbitr._spec import (
    PROD_OPENAPI_URL,
    OpenAPIDocumentError,
    openapi_document_diff,
    parse_openapi_document,
    pinned_spec,
)

_DIFF_HEAD_LINES = 200
_FETCH_TIMEOUT_SECONDS = 30.0
_ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = _ROOT / "src" / "arbitr" / "openapi.json"

EXIT_MATCH = 0
EXIT_DRIFT = 1
EXIT_UNREADABLE = 2
EXIT_UNEXPECTED = 3
EXIT_PIN_UNREADABLE = 4


class SpecFetchError(Exception):
    """The live OpenAPI URL could not be fetched."""


class SpecReadError(Exception):
    """An OpenAPI JSON file could not be read from disk."""


class SpecWriteError(Exception):
    """The packaged OpenAPI pin file could not be written."""


def _print_cli_error(exc: BaseException) -> None:
    print(f"error: {exc}", file=sys.stderr)
    if exc.__cause__ is not None:
        print(f"cause: {exc.__cause__}", file=sys.stderr)


def _print_unexpected(exc: BaseException) -> None:
    print(f"error: unexpected failure: {exc}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)


def fetch_openapi_text(url: str) -> str:
    """GET ``url`` and return the response body.

    Raises:
        SpecFetchError: On transport or HTTP failure.
    """
    try:
        response = httpx.get(url, timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SpecFetchError(f"failed to fetch {url}") from exc
    return response.text


def read_openapi_text(path: Path) -> str:
    """Read OpenAPI JSON text from disk.

    Raises:
        SpecReadError: If the file cannot be read.
    """
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecReadError(f"cannot read {path}") from exc


def write_pin_file(path: Path, raw: str) -> None:
    """Replace ``path`` with ``raw`` (atomic replace).

    Raises:
        SpecWriteError: If the file cannot be written.
    """
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(raw, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise SpecWriteError(f"cannot write {path}") from exc


def _display_pin_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> int:
    """Compare the pin to a live URL or a local file. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--url",
        default=None,
        help=f"live OpenAPI URL (default: {PROD_OPENAPI_URL})",
    )
    source.add_argument(
        "--other-file",
        type=Path,
        default=None,
        help="compare the pin to this JSON file instead of fetching",
    )
    parser.add_argument(
        "--write-pin",
        action="store_true",
        help="on drift, replace src/arbitr/openapi.json with the live document and exit 0",
    )
    args = parser.parse_args(argv)

    try:
        pin = pinned_spec()
    except (OpenAPIDocumentError, OSError) as exc:
        _print_cli_error(exc)
        return EXIT_PIN_UNREADABLE
    except Exception as exc:
        _print_unexpected(exc)
        return EXIT_UNEXPECTED

    try:
        if args.other_file is not None:
            live_raw = read_openapi_text(args.other_file)
            live = parse_openapi_document(live_raw, source=str(args.other_file))
        else:
            url = args.url or PROD_OPENAPI_URL
            live_raw = fetch_openapi_text(url)
            live = parse_openapi_document(live_raw, source=url)
        diff = openapi_document_diff(pin, live)
    except (SpecFetchError, SpecReadError, OpenAPIDocumentError) as exc:
        _print_cli_error(exc)
        return EXIT_UNREADABLE
    except Exception as exc:
        _print_unexpected(exc)
        return EXIT_UNEXPECTED

    if diff is None:
        print("pinned spec matches live OpenAPI after canonicalize")
        return EXIT_MATCH

    lines = diff.splitlines(keepends=True)
    sys.stdout.write("".join(lines[:_DIFF_HEAD_LINES]))
    if len(lines) > _DIFF_HEAD_LINES:
        print(f"... ({len(lines) - _DIFF_HEAD_LINES} more diff lines truncated)")

    if not args.write_pin:
        return EXIT_DRIFT

    try:
        write_pin_file(PIN_PATH, live_raw)
    except SpecWriteError as exc:
        _print_cli_error(exc)
        return EXIT_UNEXPECTED
    except Exception as exc:
        _print_unexpected(exc)
        return EXIT_UNEXPECTED

    print(f"wrote {_display_pin_path(PIN_PATH)}")
    return EXIT_MATCH


if __name__ == "__main__":
    raise SystemExit(main())
