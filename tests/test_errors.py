"""Error hierarchy, status mapping, and transport-error translation."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from arbitr import (
    ActionRequiredError,
    AmbiguousLocaleCodesError,
    ArbitrBaseError,
    ArbitrClient,
    ArbitrClientError,
    ArbitrError,
    AsyncArbitrClient,
    AuthenticationError,
    BareLocaleCodeError,
    ClientInputError,
    ConflictError,
    ConnectionFailedError,
    DisallowedFileExtensionError,
    GoneError,
    MissingApiKeyError,
    NotFoundError,
    PaymentRequiredError,
    ProjectWaitTimeoutError,
    RateLimitError,
    RequestTimeoutError,
    ResponseDecodeError,
    ResponseParseError,
    ServerError,
    TransportError,
    UnknownLocaleCodesError,
    ValidationError,
    WebhookVerificationError,
)

EVERY_ERROR = [
    ActionRequiredError,
    AmbiguousLocaleCodesError,
    ArbitrClientError,
    ArbitrError,
    AuthenticationError,
    BareLocaleCodeError,
    ClientInputError,
    ConflictError,
    ConnectionFailedError,
    DisallowedFileExtensionError,
    GoneError,
    MissingApiKeyError,
    NotFoundError,
    PaymentRequiredError,
    ProjectWaitTimeoutError,
    RateLimitError,
    RequestTimeoutError,
    ResponseDecodeError,
    ResponseParseError,
    ServerError,
    TransportError,
    UnknownLocaleCodesError,
    ValidationError,
    WebhookVerificationError,
]


def make_client(handler: Any) -> ArbitrClient:
    return ArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize("error_type", EVERY_ERROR)
def test_every_public_error_derives_from_one_base(error_type: type[Exception]) -> None:
    """`except ArbitrBaseError` must be enough to catch anything this package raises."""
    assert issubclass(error_type, ArbitrBaseError)


def test_the_two_subtrees_stay_distinguishable() -> None:
    assert issubclass(ArbitrError, ArbitrBaseError)
    assert issubclass(ArbitrClientError, ArbitrBaseError)
    assert not issubclass(ArbitrError, ArbitrClientError)
    assert not issubclass(ArbitrClientError, ArbitrError)


def test_timeout_errors_are_also_builtin_timeouts() -> None:
    assert issubclass(RequestTimeoutError, TimeoutError)
    assert issubclass(ProjectWaitTimeoutError, TimeoutError)


def error_response(status: int, code: str, **extra: Any) -> Any:
    body = {"error": {"code": code, "message": "boom", "request_id": "r-1", **extra}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthenticationError),
        (402, PaymentRequiredError),
        (403, AuthenticationError),
        (404, NotFoundError),
        (409, ConflictError),
        (410, GoneError),
        (422, ValidationError),
        (429, RateLimitError),
        (500, ServerError),
        (503, ServerError),
        (418, ArbitrError),
    ],
)
def test_status_maps_to_typed_error(status: int, expected: type[ArbitrError]) -> None:
    handler = error_response(status, "some_code")
    with make_client(handler) as client, pytest.raises(expected) as raised:
        client.me()
    assert raised.value.status_code == status
    assert type(raised.value) is expected


def test_payment_required_exposes_credit_shortfall() -> None:
    handler = error_response(402, "payment_required", required=100, available=10.5, shortfall=89.5)
    with make_client(handler) as client, pytest.raises(PaymentRequiredError) as raised:
        client.projects.resume("p")
    assert raised.value.required == 100.0
    assert raised.value.available == 10.5
    assert raised.value.shortfall == 89.5


def test_payment_required_tolerates_missing_credit_fields() -> None:
    handler = error_response(402, "payment_required")
    with make_client(handler) as client, pytest.raises(PaymentRequiredError) as raised:
        client.projects.resume("p")
    assert raised.value.required is None
    assert raised.value.shortfall is None


def test_payment_required_ignores_non_numeric_credit_fields() -> None:
    handler = error_response(402, "payment_required", required="lots", available=True)
    with make_client(handler) as client, pytest.raises(PaymentRequiredError) as raised:
        client.projects.resume("p")
    assert raised.value.required is None
    assert raised.value.available is None


def test_insufficient_scope_exposes_required_scope() -> None:
    handler = error_response(403, "insufficient_scope", required_scope="verify:submit")
    with make_client(handler) as client, pytest.raises(AuthenticationError) as raised:
        client.me()
    assert raised.value.required_scope == "verify:submit"


def test_required_scope_is_none_when_absent() -> None:
    handler = error_response(403, "forbidden")
    with make_client(handler) as client, pytest.raises(AuthenticationError) as raised:
        client.me()
    assert raised.value.required_scope is None


def raising_transport(exc: Exception) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


TRANSPORT_CASES = [
    (httpx.ConnectError("refused"), ConnectionFailedError),
    (httpx.ReadError("reset"), ConnectionFailedError),
    (httpx.ConnectTimeout("too slow"), RequestTimeoutError),
    (httpx.ReadTimeout("too slow"), RequestTimeoutError),
    (httpx.ProtocolError("bad framing"), ConnectionFailedError),
]


@pytest.mark.parametrize(("raised", "expected"), TRANSPORT_CASES)
def test_sync_transport_failures_are_translated(
    raised: Exception, expected: type[TransportError]
) -> None:
    """httpx exceptions must never reach the caller (they are not part of our API)."""
    with make_client(raising_transport(raised)) as client, pytest.raises(expected) as caught:
        client.me()
    assert isinstance(caught.value, ArbitrBaseError)
    assert not isinstance(caught.value, httpx.HTTPError)
    assert caught.value.method == "GET"
    assert caught.value.url.endswith("/v1/me")
    assert isinstance(caught.value.__cause__, httpx.HTTPError)


@pytest.mark.parametrize(("raised", "expected"), TRANSPORT_CASES)
async def test_async_transport_failures_are_translated(
    raised: Exception, expected: type[TransportError]
) -> None:
    async with AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(raising_transport(raised)),
    ) as client:
        with pytest.raises(expected) as caught:
            await client.me()
    assert not isinstance(caught.value, httpx.HTTPError)
    assert caught.value.method == "GET"


def test_transport_failure_during_download_is_translated(tmp_path: Any) -> None:
    handler = raising_transport(httpx.ConnectError("refused"))
    with make_client(handler) as client, pytest.raises(ConnectionFailedError):
        client.projects.download_zip("p", tmp_path / "out.zip")


async def test_async_transport_failure_during_download_is_translated(tmp_path: Any) -> None:
    async with AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(raising_transport(httpx.ConnectError("refused"))),
    ) as client:
        with pytest.raises(ConnectionFailedError):
            await client.projects.download_zip("p", tmp_path / "out.zip")


def test_transport_error_message_names_the_request() -> None:
    handler = raising_transport(httpx.ConnectError("refused"))
    expected = r"GET https://api\.test/v1/me: refused"
    with make_client(handler) as client, pytest.raises(ConnectionFailedError, match=expected):
        client.me()


def test_missing_api_key_is_still_an_input_error() -> None:
    with pytest.raises(MissingApiKeyError) as raised:
        ArbitrClient(api_key="")
    assert isinstance(raised.value, ClientInputError)
    assert isinstance(raised.value, ArbitrBaseError)
