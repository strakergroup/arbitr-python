"""HTTP helpers shared by the sync and async clients (no client I/O)."""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

import httpx

from arbitr._constants import (
    RETRY_BACKOFF_BASE_SECONDS,
    RETRY_BACKOFF_MAX_SECONDS,
    RETRY_STATUS_CODES,
)
from arbitr._version import __version__
from arbitr.errors import ClientInputError, from_response


def default_headers(api_key: str, api_version: str) -> dict[str, str]:
    """Auth, version, and User-Agent headers for every request."""
    return {
        "X-API-Key": api_key,
        "X-API-Version": api_version,
        "User-Agent": f"arbitr-python/{__version__}",
    }


def raise_for_status(resp: httpx.Response) -> None:
    """Raise a typed ArbitrError on any non-2xx response."""
    if not resp.is_success:
        raise from_response(resp)


def is_retryable_method(method: str) -> bool:
    """Whether ``method`` may be replayed automatically.

    Only GET is retried. The one idempotent POST (``/v1/projects``) streams
    file handles that cannot be rewound reliably, so a replay could send a
    truncated body — callers retry it themselves using ``idempotency_key``.
    """
    return method.upper() == "GET"


def parse_max_retries(value: int) -> int:
    """Validate the ``max_retries`` constructor argument."""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ClientInputError("max_retries must be a non-negative integer")
    return value


def transport_retry_delay(attempt: int) -> float:
    """Capped exponential backoff after a transport failure. ``attempt`` is 0-based."""
    return min(RETRY_BACKOFF_BASE_SECONDS * (2**attempt), RETRY_BACKOFF_MAX_SECONDS)


def retry_wait_seconds(resp: httpx.Response, *, attempt: int, retries: int) -> float | None:
    """Seconds to wait before another attempt, or ``None`` if this response is final.

    ``None`` means the caller should ``raise_for_status`` and either return the
    body or raise. A number means close the response, sleep, and retry.
    """
    if attempt >= retries:
        return None
    return retry_delay(resp, attempt)


def retry_delay(resp: httpx.Response, attempt: int) -> float | None:
    """Seconds to wait before retrying ``resp``, or None if it must not be retried.

    Honours ``Retry-After`` on 429 (the API documents it in seconds) and falls
    back to capped exponential backoff for the retryable 5xx codes. ``attempt``
    is 0-based.
    """
    if resp.status_code not in RETRY_STATUS_CODES:
        return None
    backoff = transport_retry_delay(attempt)
    if resp.status_code != 429:
        return backoff
    raw = resp.headers.get("retry-after")
    if raw is None:
        return backoff
    try:
        after = float(raw)
    except ValueError:
        return backoff
    return min(max(after, 0.0), RETRY_BACKOFF_MAX_SECONDS)


def rate_limit_snapshot(resp: httpx.Response) -> dict[str, str]:
    """The ``X-RateLimit-*`` headers present on ``resp``, keyed without the prefix."""
    prefix = "x-ratelimit-"
    return {
        key[len(prefix) :].replace("-", "_"): value
        for key, value in resp.headers.items()
        if key.lower().startswith(prefix)
    }


def _open_part_file(dest: Path) -> tuple[Path, BinaryIO]:
    """Create a sibling ``.part`` file for ``dest`` and return it open for writing."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    return Path(name), os.fdopen(fd, "wb")


def write_download_file(dest: Path, chunks: Iterator[bytes]) -> None:
    """Write ``chunks`` to ``dest`` via a temp file so failures do not truncate."""
    try:
        tmp_path, handle = _open_part_file(dest)
    except OSError as exc:
        raise ClientInputError(f"cannot write {dest}: {exc}") from exc
    try:
        with handle:
            for chunk in chunks:
                handle.write(chunk)
        tmp_path.replace(dest)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        raise ClientInputError(f"cannot write {dest}: {exc}") from exc
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


async def awrite_download_file(dest: Path, chunks: AsyncIterator[bytes]) -> None:
    """Async variant: buffer the stream, then write in one worker-thread call."""
    parts: list[bytes] = []
    try:
        async for chunk in chunks:
            parts.append(chunk)
    except OSError as exc:
        raise ClientInputError(f"cannot write {dest}: {exc}") from exc
    await asyncio.to_thread(write_download_file, dest, iter(parts))


def derive_ui_url(api_base: str) -> str:
    """Best-effort UI host from the API host.

    Strips a leading ``api-`` or ``api.`` from the hostname
    (``api-arbitr.straker.ai`` → ``arbitr.straker.ai``).
    Override with ``ui_base_url`` / ``ARBITR_UI_URL`` when the UI lives elsewhere.
    """
    parts = urlsplit(api_base)
    host = parts.netloc
    if "-api-" in host:
        host = host.replace("-api-", "-", 1)
    else:
        for prefix in ("api.", "api-"):
            if host.startswith(prefix):
                host = host[len(prefix) :]
                break
    return urlunsplit((parts.scheme, host, "", "", ""))


def project_ui_url(ui_base_url: str, project_id: str, *, view: str = "project") -> str:
    """Deep link to a project in the Arbitr UI."""
    url = f"{ui_base_url.rstrip('/')}/projects/{project_id}"
    return f"{url}/agents" if view == "agents" else url
