"""Opt-in retry policy, Retry-After handling, and rate-limit visibility."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from arbitr import (
    ArbitrClient,
    ArbitrError,
    AsyncArbitrClient,
    ClientInputError,
    ConnectionFailedError,
    RateLimitError,
    ServerError,
)
from arbitr._http import is_retryable_method, retry_delay
from payloads import project_json

BALANCE: dict[str, Any] = {"balance": 5}


def sync_client(handler: Any, **kwargs: Any) -> ArbitrClient:
    return ArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def async_client(handler: Any, **kwargs: Any) -> AsyncArbitrClient:
    return AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def no_real_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retry backoff is capped in seconds; never actually wait in tests."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    slept: list[float] = []

    async def fake_async_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr("asyncio.sleep", fake_async_sleep)


def responses(*statuses: int, headers: dict[str, str] | None = None) -> tuple[Any, list[int]]:
    """A handler that walks `statuses`, then 200s forever. Returns (handler, call log)."""
    calls: list[int] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if queue:
            status = queue.pop(0)
            calls.append(status)
            return httpx.Response(
                status,
                json={"error": {"code": "retry_me", "message": "later", "request_id": "r"}},
                headers=headers or {},
            )
        calls.append(200)
        return httpx.Response(200, json=BALANCE)

    return handler, calls


def test_retries_are_off_by_default() -> None:
    handler, calls = responses(503)
    with sync_client(handler) as client:
        assert client.max_retries == 0
        with pytest.raises(ServerError):
            client.credits.balance()
    assert calls == [503]


def test_retryable_status_is_retried_until_success() -> None:
    handler, calls = responses(503, 502, 429)
    with sync_client(handler, max_retries=3) as client:
        assert client.credits.balance().balance == 5
    assert calls == [503, 502, 429, 200]


def test_retries_give_up_and_raise_the_last_error() -> None:
    handler, calls = responses(429, 429, 429, 429)
    with sync_client(handler, max_retries=2) as client, pytest.raises(RateLimitError):
        client.credits.balance()
    assert calls == [429, 429, 429]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422])
def test_non_retryable_statuses_fail_immediately(status: int) -> None:
    handler, calls = responses(status, status, status)
    with sync_client(handler, max_retries=5) as client, pytest.raises(ArbitrError) as raised:
        client.credits.balance()
    assert raised.value.status_code == status
    assert calls == [status]


def test_transport_failures_are_retried_then_translated() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=BALANCE)

    with sync_client(handler, max_retries=3) as client:
        assert client.credits.balance().balance == 5
    assert attempts["n"] == 3


def test_transport_failures_stop_at_the_retry_limit() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("refused", request=request)

    with sync_client(handler, max_retries=2) as client, pytest.raises(ConnectionFailedError):
        client.credits.balance()
    assert attempts["n"] == 3


def test_submit_is_never_retried_automatically() -> None:
    """A multipart body streams file handles that cannot be safely replayed."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"code": "x", "message": "y"}})
        return httpx.Response(201, json=project_json("p"))

    with sync_client(handler, max_retries=5) as client, pytest.raises(ServerError):
        client.projects.submit(files=[("a.txt", b"hi")], name="x", target_language_codes=["ko-kr"])
    assert calls == ["POST"]


def test_resumption_posts_are_never_retried() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(503, json={"error": {"code": "x", "message": "y"}})

    with sync_client(handler, max_retries=5) as client, pytest.raises(ServerError):
        client.projects.resume("p")
    assert calls == ["POST"]


def test_only_get_is_replayable() -> None:
    assert is_retryable_method("GET")
    assert is_retryable_method("get")
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert not is_retryable_method(method)


def test_retry_after_header_drives_the_429_delay() -> None:
    resp = httpx.Response(429, headers={"Retry-After": "7"})
    assert retry_delay(resp, attempt=0) == 7.0


def test_retry_after_is_capped_and_floored() -> None:
    assert retry_delay(httpx.Response(429, headers={"Retry-After": "99999"}), 0) == 60.0
    assert retry_delay(httpx.Response(429, headers={"Retry-After": "-5"}), 0) == 0.0


def test_malformed_retry_after_falls_back_to_backoff() -> None:
    assert retry_delay(httpx.Response(429, headers={"Retry-After": "soon"}), 0) == 0.5


def test_missing_retry_after_falls_back_to_backoff() -> None:
    assert retry_delay(httpx.Response(429), 0) == 0.5


def test_server_errors_use_exponential_backoff() -> None:
    delays = [retry_delay(httpx.Response(503), attempt) for attempt in range(5)]
    assert delays == [0.5, 1.0, 2.0, 4.0, 8.0]


def test_backoff_is_capped() -> None:
    assert retry_delay(httpx.Response(503), attempt=40) == 60.0


def test_non_retryable_status_has_no_delay() -> None:
    assert retry_delay(httpx.Response(404), 0) is None
    assert retry_delay(httpx.Response(200), 0) is None


@pytest.mark.parametrize("bad", [-1, "3", 1.5, True])
def test_max_retries_is_validated(bad: Any) -> None:
    with pytest.raises(ClientInputError, match="max_retries"):
        ArbitrClient(api_key="k", max_retries=bad)


def test_rate_limit_headers_are_exposed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=BALANCE,
            headers={
                "X-RateLimit-Limit": "100",
                "X-RateLimit-Remaining": "97",
                "X-RateLimit-Reset": "42",
            },
        )

    with sync_client(handler) as client:
        assert client.rate_limit == {}
        client.credits.balance()
        assert client.rate_limit == {"limit": "100", "remaining": "97", "reset": "42"}


def test_rate_limit_snapshot_survives_a_response_without_the_headers() -> None:
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        headers = {"X-RateLimit-Remaining": "5"} if seen["n"] == 1 else {}
        return httpx.Response(200, json=BALANCE, headers=headers)

    with sync_client(handler) as client:
        client.credits.balance()
        client.credits.balance()
        assert client.rate_limit == {"remaining": "5"}


async def test_async_retries_retryable_statuses() -> None:
    handler, calls = responses(503, 429)
    async with async_client(handler, max_retries=3) as client:
        assert (await client.credits.balance()).balance == 5
    assert calls == [503, 429, 200]


async def test_async_retries_give_up_and_raise() -> None:
    handler, calls = responses(503, 503, 503)
    async with async_client(handler, max_retries=1) as client:
        with pytest.raises(ServerError):
            await client.credits.balance()
    assert calls == [503, 503]


async def test_async_transport_failures_are_retried() -> None:
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=BALANCE)

    async with async_client(handler, max_retries=2) as client:
        assert (await client.credits.balance()).balance == 5
    assert attempts["n"] == 2


async def test_async_exposes_rate_limit_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=BALANCE, headers={"X-RateLimit-Remaining": "12"})

    async with async_client(handler) as client:
        await client.credits.balance()
        assert client.rate_limit == {"remaining": "12"}


async def test_async_max_retries_is_validated() -> None:
    with pytest.raises(ClientInputError, match="max_retries"):
        AsyncArbitrClient(api_key="k", max_retries=-3)


def zip_then_error_handler(*statuses: int, payload: bytes = b"PKZIP") -> tuple[Any, list[int]]:
    """Walk `statuses` as error responses, then 200 with `payload`."""
    calls: list[int] = []
    queue = list(statuses)

    def handler(request: httpx.Request) -> httpx.Response:
        if queue:
            status = queue.pop(0)
            calls.append(status)
            return httpx.Response(
                status,
                json={"error": {"code": "retry_me", "message": "later", "request_id": "r"}},
            )
        calls.append(200)
        return httpx.Response(200, content=payload, headers={"X-RateLimit-Remaining": "4"})

    return handler, calls


def test_download_retries_a_503(tmp_path: Any) -> None:
    handler, calls = zip_then_error_handler(503)
    with sync_client(handler, max_retries=1) as client:
        dest = tmp_path / "out.zip"
        client.projects.download_zip("p", dest)
        assert dest.read_bytes() == b"PKZIP"
        assert client.rate_limit == {"remaining": "4"}
    assert calls == [503, 200]


def test_download_gives_up_after_max_retries(tmp_path: Any) -> None:
    handler, calls = zip_then_error_handler(503, 503)
    with sync_client(handler, max_retries=1) as client, pytest.raises(ServerError):
        client.projects.download_zip("p", tmp_path / "out.zip")
    assert calls == [503, 503]


async def test_async_download_retries_a_503(tmp_path: Any) -> None:
    handler, calls = zip_then_error_handler(503)
    async with async_client(handler, max_retries=1) as client:
        dest = tmp_path / "out.zip"
        await client.projects.download_zip("p", dest)
        assert dest.read_bytes() == b"PKZIP"
        assert client.rate_limit == {"remaining": "4"}
    assert calls == [503, 200]
