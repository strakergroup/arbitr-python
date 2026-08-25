"""Parse 2xx JSON bodies into generated response models (no I/O)."""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from arbitr.errors import ResponseDecodeError, ResponseParseError

T = TypeVar("T", bound=BaseModel)


def decode_json_body(resp: httpx.Response, *, operation: str) -> Any:
    """Parse a 2xx response body as JSON.

    An empty body becomes ``None``. Malformed JSON is a typed client error,
    never a raw ``json.JSONDecodeError``.

    Raises:
        ResponseDecodeError: If the body is not valid JSON.
    """
    if not resp.content:
        return None
    try:
        return resp.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ResponseDecodeError(operation, exc) from exc


def parse_response(model: type[T], data: object, *, operation: str) -> T:
    """Parse a 2xx JSON body as ``model``.

    Raises:
        ResponseParseError: If the body does not match the published schema.
    """
    try:
        return model.model_validate(data)
    except PydanticValidationError as exc:
        raise ResponseParseError(operation, exc) from exc
