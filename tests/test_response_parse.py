"""Response-schema parsing — 2xx JSON that does not match must raise."""

from __future__ import annotations

import json

import httpx
import pytest

from arbitr import ProjectResponse, ResponseDecodeError, ResponseParseError
from arbitr._parse import decode_json_body, parse_response
from payloads import project_json


def test_parse_response_accepts_required_fields() -> None:
    parsed = parse_response(
        ProjectResponse, project_json("proj-1", status="extracting"), operation="createProject"
    )
    assert parsed.id == "proj-1"
    assert parsed.status == "extracting"


def test_parse_response_keeps_unknown_fields() -> None:
    parsed = parse_response(
        ProjectResponse,
        project_json("proj-1", extra_flag=True),
        operation="getProject",
    )
    assert parsed.model_extra is not None
    assert parsed.model_extra["extra_flag"] is True


def test_parse_response_missing_required_field_is_typed() -> None:
    with pytest.raises(ResponseParseError, match="getProject") as parse_err:
        parse_response(ProjectResponse, {"id": "only-id"}, operation="getProject")
    assert parse_err.value.operation == "getProject"
    assert parse_err.value.errors


def test_decode_json_body_parses_an_object() -> None:
    resp = httpx.Response(200, json={"ok": True})
    assert decode_json_body(resp, operation="getCurrentKey") == {"ok": True}


def test_decode_json_body_treats_empty_as_none() -> None:
    resp = httpx.Response(200, content=b"")
    assert decode_json_body(resp, operation="getCurrentKey") is None


def test_malformed_json_is_a_typed_decode_error() -> None:
    resp = httpx.Response(200, content=b"<html>nope</html>")
    with pytest.raises(ResponseDecodeError, match="getCurrentKey") as raised:
        decode_json_body(resp, operation="getCurrentKey")
    assert raised.value.operation == "getCurrentKey"
    assert isinstance(raised.value.__cause__, json.JSONDecodeError)
