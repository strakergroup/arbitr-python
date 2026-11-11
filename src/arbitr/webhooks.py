"""Inbound webhook signature verification (no subscription-management calls)."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from arbitr._datetime import UtcDatetime
from arbitr.errors import ArbitrClientError

# Informational: a delivery may carry a name not listed here (a newer API
# release). ``parse_event`` accepts any event name.
KNOWN_EVENTS = frozenset(
    {
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
)


class WebhookVerificationError(ArbitrClientError):
    """Raised when a delivery fails signature or timestamp verification."""


def compute_signature(body: bytes, timestamp: int | str, secret: str) -> str:
    """Return the ``sha256=<hex>`` signature for a body + timestamp."""
    if not secret:
        raise WebhookVerificationError("missing webhook secret")
    try:
        ts = int(timestamp)
    except (TypeError, ValueError) as exc:
        raise WebhookVerificationError("malformed timestamp") from exc
    payload = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(
    *,
    body: bytes,
    signature: str | None,
    timestamp: str | int | None,
    secret: str,
    tolerance_seconds: float | None = 300,
) -> None:
    """Verify a delivery. Raises WebhookVerificationError on any failure.

    ``tolerance_seconds`` guards against replay. Pass None to disable.
    """
    if not secret:
        raise WebhookVerificationError("missing webhook secret")
    if not signature or not signature.startswith("sha256="):
        raise WebhookVerificationError("missing or malformed X-Arbitr-Signature")
    if timestamp is None:
        raise WebhookVerificationError("missing X-Arbitr-Timestamp")
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        raise WebhookVerificationError("malformed X-Arbitr-Timestamp") from None

    if tolerance_seconds is not None:
        if not math.isfinite(tolerance_seconds):
            raise WebhookVerificationError("tolerance_seconds must be a finite number or None")
        if abs(time.time() - ts) > tolerance_seconds:
            raise WebhookVerificationError(
                f"timestamp outside ±{tolerance_seconds:.0f}s tolerance (replay protection)"
            )

    expected = compute_signature(body, ts, secret)
    # Bytes, not str: compare_digest raises TypeError on a non-ASCII str.
    if not hmac.compare_digest(expected.encode(), signature.encode("utf-8", "surrogateescape")):
        raise WebhookVerificationError("signature mismatch")


class WebhookEvent(BaseModel):
    """The envelope of a delivered webhook."""

    model_config = ConfigDict(frozen=True, extra="allow")

    id: str
    # Null for ``webhook.test`` and for redeliveries of rows that predate it.
    event_id: str | None = None
    event: str
    created_at: UtcDatetime
    mode: Literal["live", "test"]
    data: dict[str, Any]


def parse_event(body: bytes | str) -> dict[str, Any]:
    """Parse the event envelope: ``{"event": <type>, ...payload}``."""
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebhookVerificationError("body is not valid JSON") from exc
    if not isinstance(event, dict) or "event" not in event:
        raise WebhookVerificationError("body is not an Arbitr event envelope")
    return event


def parse_webhook_event(body: bytes | str) -> WebhookEvent:
    """Parse a delivered body into a typed ``WebhookEvent``.

    Does not verify the signature; call ``verify_signature`` first.
    """
    raw = parse_event(body)
    try:
        return WebhookEvent.model_validate(raw)
    except ValidationError as exc:
        raise WebhookVerificationError("body is not an Arbitr event envelope") from exc
