"""Fail if the packaged OpenAPI pin differs from live production.

Compares ``src/arbitr/openapi.json`` (via ``pinned_spec()``) to
``PROD_OPENAPI_URL``. Pytest stays offline; this script is the scheduled
CI entrypoint.

    uv run python scripts/check_pinned_spec.py
    uv run python scripts/check_pinned_spec.py --other-file /tmp/openapi.json

Exit 0 if they match after canonicalize, 1 on drift, 2 when the live
spec is unreadable (CI retries), 3 on unexpected script failures, 4 when
the packaged pin is unreadable (fail immediately; not a prod flake).
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

EXIT_MATCH = 0
EXIT_DRIFT = 1
EXIT_UNREADABLE = 2
EXIT_UNEXPECTED = 3
EXIT_PIN_UNREADABLE = 4


class SpecFetchError(Exception):
    """The live OpenAPI URL could not be fetched."""


class SpecReadError(Exception):
    """An OpenAPI JSON file could not be read from disk."""


def _print_cli_error(exc: BaseException) -> None:
    print(f"error: {exc}", file=sys.stderr)
    if exc.__cause__ is not None:
        print(f"cause: {exc.__cause__}", file=sys.stderr)


def _print_unexpected(exc: BaseException) -> None:
    print(f"error: unexpected failure: {exc}", file=sys.stderr)
    traceback.print_exc(file=sys.stderr)


def fetch_openapi_url(url: str) -> dict[str, object]:
    """GET ``url`` and parse it as an OpenAPI object.

    Raises:
        SpecFetchError: On transport or HTTP failure.
        OpenAPIDocumentError: If the body is not a JSON object.
    """
    try:
        response = httpx.get(url, timeout=_FETCH_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise SpecFetchError(f"failed to fetch {url}") from exc
    return parse_openapi_document(response.text, source=url)


def load_openapi_file(path: Path) -> dict[str, object]:
    """Read an OpenAPI JSON file.

    Raises:
        SpecReadError: If the file cannot be read.
        OpenAPIDocumentError: If the text is not a JSON object OpenAPI document.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SpecReadError(f"cannot read {path}") from exc
    return parse_openapi_document(raw, source=str(path))


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
            live = load_openapi_file(args.other_file)
        else:
            live = fetch_openapi_url(args.url or PROD_OPENAPI_URL)
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
    return EXIT_DRIFT


if __name__ == "__main__":
    raise SystemExit(main())
