"""Webhook signature verification tests."""

from __future__ import annotations

import json
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbitr.webhooks import (
    WebhookVerificationError,
    compute_signature,
    parse_event,
    verify_signature,
)

SECRET = "whsec_test_secret"
BODY = b'{"event":"project.completed","data":{"project_id":"p-1"}}'


def sign(body: bytes = BODY, ts: int | None = None) -> tuple[str, str]:
    ts = ts or int(time.time())
    return compute_signature(body, ts, SECRET), str(ts)


def test_roundtrip_valid_signature() -> None:
    sig, ts = sign()
    verify_signature(body=BODY, signature=sig, timestamp=ts, secret=SECRET)


def test_tampered_body_fails() -> None:
    sig, ts = sign()
    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_signature(body=BODY + b" ", signature=sig, timestamp=ts, secret=SECRET)


def test_stale_timestamp_fails() -> None:
    old = int(time.time()) - 3600
    sig, ts = sign(ts=old)
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_signature(body=BODY, signature=sig, timestamp=ts, secret=SECRET)


def test_empty_secret_is_rejected() -> None:
    sig, ts = sign()
    with pytest.raises(WebhookVerificationError, match="secret"):
        verify_signature(body=BODY, signature=sig, timestamp=ts, secret="")


def test_nan_tolerance_is_rejected() -> None:
    sig, ts = sign()
    with pytest.raises(WebhookVerificationError, match="finite"):
        verify_signature(
            body=BODY,
            signature=sig,
            timestamp=ts,
            secret=SECRET,
            tolerance_seconds=float("nan"),
        )


def test_parse_event() -> None:
    event = parse_event(BODY)
    assert event["event"] == "project.completed"
    with pytest.raises(WebhookVerificationError):
        parse_event(json.dumps({"no_event": True}))


def test_parse_event_invalid_json_is_a_package_error() -> None:
    with pytest.raises(WebhookVerificationError, match="valid JSON") as raised:
        parse_event(b"not-json{")
    assert isinstance(raised.value.__cause__, json.JSONDecodeError)


def test_compute_signature_rejects_malformed_timestamp() -> None:
    with pytest.raises(WebhookVerificationError, match="malformed timestamp"):
        compute_signature(BODY, "1.5", SECRET)


_secrets = st.text(alphabet=st.characters(blacklist_categories=("Cs",)), min_size=1, max_size=128)
_bodies = st.binary(max_size=4096)
_timestamps = st.integers(min_value=0, max_value=2**40)


@given(body=_bodies, ts=_timestamps, secret=_secrets)
def test_signature_roundtrip_always_verifies(body: bytes, ts: int, secret: str) -> None:
    sig = compute_signature(body, ts, secret)
    verify_signature(body=body, signature=sig, timestamp=ts, secret=secret, tolerance_seconds=None)


@given(body=_bodies, ts=_timestamps, secret=_secrets)
def test_tampered_body_never_verifies(body: bytes, ts: int, secret: str) -> None:
    sig = compute_signature(body, ts, secret)
    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_signature(
            body=body + b"\x00",
            signature=sig,
            timestamp=ts,
            secret=secret,
            tolerance_seconds=None,
        )
