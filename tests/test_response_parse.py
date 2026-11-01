"""Response-schema parsing — 2xx JSON that does not match must raise."""

from __future__ import annotations

import json

import httpx2
import pytest

from arbitr import ProjectResponse, ResponseDecodeError, ResponseParseError
from arbitr._parse import decode_json_body, parse_response
from arbitr.generated.models import (
    AgentFinding,
    FindingListResponse,
    FindingType,
    FlagFinding,
    HumanReviewResponse,
    HumanReviewStatus,
    UnknownFinding,
)
from payloads import agent_finding_json, flag_finding_json, human_review_json, project_json


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
    resp = httpx2.Response(200, json={"ok": True})
    assert decode_json_body(resp, operation="getCurrentKey") == {"ok": True}


def test_decode_json_body_treats_empty_as_none() -> None:
    resp = httpx2.Response(200, content=b"")
    assert decode_json_body(resp, operation="getCurrentKey") is None


def test_malformed_json_is_a_typed_decode_error() -> None:
    resp = httpx2.Response(200, content=b"<html>nope</html>")
    with pytest.raises(ResponseDecodeError, match="getCurrentKey") as raised:
        decode_json_body(resp, operation="getCurrentKey")
    assert raised.value.operation == "getCurrentKey"
    assert isinstance(raised.value.__cause__, json.JSONDecodeError)


def test_agent_finding_accepts_repaired_type() -> None:
    model = AgentFinding.model_validate(agent_finding_json(finding_type="repaired"))
    assert model.finding_type is FindingType.repaired


def test_agent_finding_accepts_rewrite_type() -> None:
    model = AgentFinding.model_validate(agent_finding_json(finding_type="rewrite"))
    assert model.finding_type is FindingType.rewrite


def test_agent_finding_accepts_rule_violation_type() -> None:
    model = AgentFinding.model_validate(agent_finding_json(finding_type="rule_violation"))
    assert model.finding_type is FindingType.rule_violation
    assert FindingType.is_known("rule_violation")


def test_human_review_accepts_skipped_status() -> None:
    model = HumanReviewResponse.model_validate(human_review_json(status="skipped"))
    assert model.status is HumanReviewStatus.skipped
    assert HumanReviewStatus.is_known("skipped")


def test_human_review_accepts_restoring_formatting_status() -> None:
    model = HumanReviewResponse.model_validate(human_review_json(status="restoring_formatting"))
    assert model.status is HumanReviewStatus.restoring_formatting
    assert HumanReviewStatus.is_known("restoring_formatting")


def test_agent_finding_accepts_a_finding_type_this_build_does_not_know() -> None:
    model = AgentFinding.model_validate(agent_finding_json(finding_type="teleportation"))
    assert model.finding_type == "teleportation"
    assert FindingType.is_known(model.finding_type) is False


def test_one_unknown_finding_type_does_not_fail_the_whole_page() -> None:
    page = parse_response(
        FindingListResponse,
        {
            "findings": [
                agent_finding_json("find-1", finding_type="teleportation"),
                agent_finding_json("find-2", finding_type="substitution"),
            ],
            "page": {"has_more": False, "limit": 50, "after": None},
        },
        operation="listProjectFindings",
    )
    assert [finding.id for finding in page.findings] == ["find-1", "find-2"]
    known = page.findings[1]
    assert isinstance(known, AgentFinding)
    assert known.finding_type is FindingType.substitution


def test_a_finding_kind_this_build_does_not_know_parses_beside_known_ones() -> None:
    page = parse_response(
        FindingListResponse,
        {
            "findings": [
                flag_finding_json("flag-1"),
                {"kind": "suggestion", "id": "find-2", "note": "consider this"},
                agent_finding_json("find-3"),
            ],
            "page": {"has_more": False, "limit": 50, "after": None},
        },
        operation="listProjectFindings",
    )
    flag, unknown, agent = page.findings
    assert isinstance(flag, FlagFinding)
    assert isinstance(agent, AgentFinding)
    assert isinstance(unknown, UnknownFinding)
    assert unknown.kind == "suggestion"
    assert unknown.id == "find-2"
    assert unknown.model_extra == {"note": "consider this"}


def test_a_malformed_finding_of_a_known_kind_still_fails_the_page() -> None:
    body = flag_finding_json()
    del body["severity"]
    with pytest.raises(ResponseParseError):
        parse_response(
            FindingListResponse,
            {"findings": [body], "page": {"has_more": False, "limit": 50, "after": None}},
            operation="listProjectFindings",
        )


def test_flag_finding_accepts_an_unknown_severity_and_status() -> None:
    model = FlagFinding.model_validate(
        flag_finding_json(severity="catastrophic", status="escalated")
    )
    assert model.severity == "catastrophic"
    assert model.status == "escalated"
