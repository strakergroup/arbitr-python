"""Webhook signature verification tests."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from arbitr.webhooks import (
    KNOWN_EVENTS,
    WebhookEvent,
    WebhookVerificationError,
    compute_signature,
    parse_event,
    parse_webhook_event,
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


def test_non_ascii_signature_is_a_mismatch_not_a_type_error() -> None:
    _, ts = sign()
    with pytest.raises(WebhookVerificationError, match="mismatch"):
        verify_signature(body=BODY, signature="sha256=\u00e9" * 8, timestamp=ts, secret=SECRET)


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


def _envelope(**over: object) -> bytes:
    body: dict[str, object] = {
        "id": "dlv-1",
        "event_id": "evt-1",
        "event": "project.hold_ready",
        "created_at": "2026-10-29T01:02:03Z",
        "mode": "live",
        "data": {"project_id": "p-1"},
    }
    body.update(over)
    return json.dumps(body).encode()


def test_known_events_matches_exposed_list() -> None:
    exposed = {
        "project.created",
        "project.awaiting_payment",
        "project.hold_ready",
        "project.confirmed",
        "project.hold_expired",
        "project.completed",
        "project.failed",
        "project.cancelled",
        "project.published",
        "project.review_requested",
        "project.review_awaiting_payment",
        "project.review_completed",
        "webhook.test",
    }
    assert exposed == KNOWN_EVENTS


def test_parse_event() -> None:
    event = parse_event(BODY)
    assert event["event"] == "project.completed"
    with pytest.raises(WebhookVerificationError):
        parse_event(json.dumps({"no_event": True}))


def test_parse_event_still_returns_plain_dict() -> None:
    assert type(parse_event(_envelope())) is dict


def test_parse_webhook_event_hold_ready() -> None:
    event = parse_webhook_event(_envelope())
    assert isinstance(event, WebhookEvent)
    assert event.event == "project.hold_ready"
    assert event.event in KNOWN_EVENTS
    assert event.id == "dlv-1"
    assert event.event_id == "evt-1"
    assert event.mode == "live"
    assert event.created_at == datetime(2026, 10, 29, 1, 2, 3, tzinfo=UTC)
    assert event.data == {"project_id": "p-1"}
    with pytest.raises(ValueError):
        event.event = "other"  # ty: ignore[invalid-assignment] -- frozen; the attempt is the test


def test_parse_webhook_event_null_event_id_for_test_ping() -> None:
    event = parse_webhook_event(_envelope(event="webhook.test", event_id=None, mode="test"))
    assert event.event_id is None
    assert event.mode == "test"


def test_parse_webhook_event_unknown_event_still_parses() -> None:
    event = parse_webhook_event(_envelope(event="project.something_new"))
    assert event.event == "project.something_new"
    assert event.event not in KNOWN_EVENTS


def test_parse_webhook_event_malformed_envelope_is_a_package_error() -> None:
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(json.dumps({"no_event": True}))
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(b"[1, 2]")
    with pytest.raises(WebhookVerificationError):
        parse_webhook_event(_envelope(data="not-a-dict"))


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
