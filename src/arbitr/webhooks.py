"""Inbound webhook signature verification (no subscription-management calls)."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
from typing import Any

from arbitr.errors import ArbitrClientError

KNOWN_EVENTS = frozenset(
    {
        "project.completed",
        "project.published",
        "project.failed",
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
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("signature mismatch")


def parse_event(body: bytes | str) -> dict[str, Any]:
    """Parse the event envelope: ``{"event": <type>, ...payload}``."""
    try:
        event = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebhookVerificationError("body is not valid JSON") from exc
    if not isinstance(event, dict) or "event" not in event:
        raise WebhookVerificationError("body is not an Arbitr event envelope")
    return event
