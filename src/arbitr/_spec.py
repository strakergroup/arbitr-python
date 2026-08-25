"""Access to the OpenAPI snapshot this release was generated from."""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

_SPEC_RESOURCE = "openapi.json"


def pinned_spec() -> dict[str, Any]:
    """The OpenAPI snapshot the shipped models and methods were generated from.

    Packaged alongside the module so callers can introspect the exact contract
    a given release targets — useful for diffing against a live
    ``/openapi.json`` to detect drift before it surfaces as a
    ``ResponseParseError``.
    """
    raw = resources.files("arbitr").joinpath(_SPEC_RESOURCE).read_text(encoding="utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise TypeError(f"{_SPEC_RESOURCE} is not a JSON object")
    return parsed
