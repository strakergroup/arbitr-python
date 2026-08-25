"""Project submit form, list query construction, and resumption body (no I/O)."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from arbitr._constants import DEFAULT_WORKFLOW
from arbitr.errors import BareLocaleCodeError, ClientInputError


class ProjectResumptionResponse(BaseModel):
    """2xx body for POST /v1/projects/{id}/resumptions.

    The published OpenAPI snapshot does not declare a 200 schema. Sandbox keys
    return ``project_id`` and ``status``; live keys pass through the
    orchestrator. Extra fields are kept.
    """

    model_config = ConfigDict(extra="allow")

    project_id: str | None = None
    status: str | None = None
    id: str | None = None


def normalize_locale_code(code: str) -> str:
    """Lowercase and trim one locale code for the wire.

    The API accepts lowercase BCP-47 tags only; the tags are case-insensitive
    by spec, so folding ``fr-FR`` to ``fr-fr`` is safe. Bare language codes
    such as ``fr`` are rejected here — only ``languages.resolve()`` may expand
    those, and guessing a region would pick one on the caller's behalf.

    Raises:
        ClientInputError: If the code is empty after trimming.
        BareLocaleCodeError: If the code has no subtag (no hyphen).
    """
    normalized = code.strip().lower()
    if not normalized:
        raise ClientInputError("locale code must not be empty")
    if "-" not in normalized:
        raise BareLocaleCodeError(code.strip())
    return normalized


def project_submit_form(
    *,
    name: str,
    target_language_codes: list[str],
    source_language_code: str,
    workflow: list[str] | None,
    due_date: str | None,
) -> dict[str, str]:
    """Multipart form fields for POST /v1/projects (files are attached separately)."""
    data = {
        "name": name,
        "target_language_codes": json.dumps(
            [normalize_locale_code(code) for code in target_language_codes]
        ),
        "source_language_code": normalize_locale_code(source_language_code),
        "workflow": json.dumps(list(workflow or list(DEFAULT_WORKFLOW))),
    }
    if due_date is not None:
        data["due_date"] = due_date
    return data


def project_list_params(
    *,
    limit: int,
    page: int,
    modified_after: str | None,
    status: str | None,
) -> dict[str, Any]:
    """Query params for GET /v1/projects."""
    params: dict[str, Any] = {"limit": limit, "page": page}
    if modified_after:
        params["modified_after"] = modified_after
    if status:
        params["status"] = status
    return params


def idempotency_headers(idempotency_key: str | None) -> dict[str, str] | None:
    """Idempotency-Key header map, or None when the caller omitted a key."""
    return {"Idempotency-Key": idempotency_key} if idempotency_key else None
