"""The webhook management calls, shared by the sync and async client tests.

Each case: the call, the method, path, JSON body and query it must send, the
status and body the server answers with, and the type it must parse into.
"""

from __future__ import annotations

from typing import Any

from arbitr import (
    WebhookCreateResponse,
    WebhookDelivery,
    WebhookDeliveryListResponse,
    WebhookDeliveryStatus,
    WebhookListResponse,
    WebhookResponse,
    WebhookStatus,
)
from payloads import webhook_delivery_json, webhook_json

WEBHOOK_CALLS: list[tuple[Any, str, str, Any, dict[str, str], int, Any, type]] = [
    (
        lambda c: c.webhooks.list(),
        "GET",
        "/v1/webhooks",
        None,
        {},
        200,
        {
            "webhooks": [webhook_json()],
            "page": {"number": 1, "limit": 50, "total": 1, "has_more": False},
        },
        WebhookListResponse,
    ),
    (
        lambda c: c.webhooks.create(
            "https://example.com/hooks", ["project.completed"], description="ops"
        ),
        "POST",
        "/v1/webhooks",
        {
            "url": "https://example.com/hooks",
            "event_types": ["project.completed"],
            "description": "ops",
        },
        {},
        201,
        webhook_json(plaintext_secret="whsec_x"),
        WebhookCreateResponse,
    ),
    (
        lambda c: c.webhooks.get("w-1"),
        "GET",
        "/v1/webhooks/w-1",
        None,
        {},
        200,
        webhook_json(),
        WebhookResponse,
    ),
    (
        lambda c: c.webhooks.update("w-1", status=WebhookStatus.disabled),
        "PATCH",
        "/v1/webhooks/w-1",
        {"status": "disabled"},
        {},
        200,
        webhook_json(status="disabled"),
        WebhookResponse,
    ),
    (
        lambda c: c.webhooks.delete("w-1"),
        "DELETE",
        "/v1/webhooks/w-1",
        None,
        {},
        200,
        webhook_json(status="disabled"),
        WebhookResponse,
    ),
    (
        lambda c: c.webhooks.test("w-1"),
        "POST",
        "/v1/webhooks/w-1/test",
        None,
        {},
        200,
        {"delivery_id": "d-1"},
        dict,
    ),
    (
        lambda c: c.webhooks.deliveries(
            "w-1", status=WebhookDeliveryStatus.failed, after="t", limit=10
        ),
        "GET",
        "/v1/webhooks/w-1/deliveries",
        None,
        {"status": "failed", "after": "t", "limit": "10"},
        200,
        {"deliveries": [webhook_delivery_json()], "page": {"has_more": False, "limit": 10}},
        WebhookDeliveryListResponse,
    ),
    (
        lambda c: c.webhooks.redeliver("w-1", "d-1"),
        "POST",
        "/v1/webhooks/w-1/deliveries/d-1/redeliver",
        None,
        {},
        202,
        webhook_delivery_json(status="pending"),
        WebhookDelivery,
    ),
]

WEBHOOK_CALL_IDS = ["list", "create", "get", "update", "delete", "test", "deliveries", "redeliver"]
