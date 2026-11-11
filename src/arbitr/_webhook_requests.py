"""Webhook management request bodies, query params and paths (no I/O)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import RootModel

from arbitr._http import path_segment
from arbitr.generated.models import WebhookDeliveryStatus, WebhookStatus

WEBHOOKS_PATH = "/v1/webhooks"


def webhook_path(webhook_id: str, *rest: str) -> str:
    """``/v1/webhooks/{id}[/...]`` with every id percent-encoded."""
    return "/".join([WEBHOOKS_PATH, path_segment(webhook_id), *rest])


def webhook_create_body(
    *, url: str, event_types: Sequence[str], description: str | None
) -> dict[str, Any]:
    """JSON body for POST /v1/webhooks; ``description`` is left out when None."""
    body: dict[str, Any] = {"url": url, "event_types": list(event_types)}
    if description is not None:
        body["description"] = description
    return body


def webhook_update_body(
    *,
    event_types: Sequence[str] | None,
    status: WebhookStatus | str | None,
    description: str | None,
) -> dict[str, Any]:
    """JSON body for PATCH /v1/webhooks/{id}; fields left as None are not sent, so they stay."""
    body: dict[str, Any] = {}
    if event_types is not None:
        body["event_types"] = list(event_types)
    if status is not None:
        body["status"] = str(status)
    if description is not None:
        body["description"] = description
    return body


def webhook_deliveries_params(
    *,
    status: WebhookDeliveryStatus | str | None,
    event: str | None,
    after: str | None,
    limit: int | None,
) -> dict[str, Any]:
    """Query params for GET /v1/webhooks/{id}/deliveries; unset filters are left out."""
    params: dict[str, Any] = {}
    if status is not None:
        params["status"] = str(status)
    if event is not None:
        params["event"] = event
    if after is not None:
        params["after"] = after
    if limit is not None:
        params["limit"] = limit
    return params


class WebhookTestBody(RootModel[dict[str, Any]]):
    """POST /v1/webhooks/{id}/test answers with a free-form JSON object."""
