"""Access to the OpenAPI snapshot this release was generated from."""

from __future__ import annotations

import json
from collections.abc import Mapping
from difflib import unified_diff
from importlib import resources
from typing import Any

from arbitr._constants import DEFAULT_BASE_URL
from arbitr.errors import ArbitrClientError

_SPEC_RESOURCE = "openapi.json"

# Public production OpenAPI. The pin is a snapshot of this document.
PROD_OPENAPI_URL = f"{DEFAULT_BASE_URL}/openapi.json"


class OpenAPIDocumentError(ArbitrClientError):
    """The input is not a JSON object OpenAPI document."""


def pinned_spec() -> dict[str, Any]:
    """The OpenAPI snapshot the shipped models and methods were generated from.

    Packaged alongside the module so callers can introspect the exact contract
    a given release targets — useful for diffing against a live
    ``/openapi.json`` to detect drift before it surfaces as a
    ``ResponseParseError``.
    """
    raw = resources.files("arbitr").joinpath(_SPEC_RESOURCE).read_text(encoding="utf-8")
    return parse_openapi_document(raw, source=_SPEC_RESOURCE)


def parse_openapi_document(raw: str, *, source: str = "document") -> dict[str, Any]:
    """Parse OpenAPI JSON text into an object.

    Raises:
        OpenAPIDocumentError: If the text is not a JSON object with required OpenAPI fields.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpenAPIDocumentError(f"{source} is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise OpenAPIDocumentError(f"{source} is not a JSON object")
    if (
        not isinstance(parsed.get("openapi"), str)
        or not isinstance(parsed.get("info"), dict)
        or not isinstance(parsed.get("paths"), dict)
    ):
        raise OpenAPIDocumentError(f"{source} is not an OpenAPI document")
    return parsed


def _canonicalize_numbers(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _canonicalize_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonicalize_numbers(v) for v in obj]
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


def canonical_openapi_json(doc: Mapping[str, Any]) -> str:
    """Stable JSON text for comparing OpenAPI documents (sorted keys, int-floats)."""
    normalized = _canonicalize_numbers(dict(doc))
    return json.dumps(normalized, sort_keys=True, indent=2) + "\n"


def openapi_document_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> str | None:
    """Unified diff of two OpenAPI documents, or None if they match after canonicalize.

    ``left`` is the pin; ``right`` is the live (or other) document. Key order
    and ``1`` vs ``1.0`` are not drift.
    """
    a = canonical_openapi_json(left).splitlines(keepends=True)
    b = canonical_openapi_json(right).splitlines(keepends=True)
    if a == b:
        return None
    return "".join(unified_diff(a, b, fromfile="pin", tofile="live", n=3))
