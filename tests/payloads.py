"""Minimal JSON bodies that satisfy published required fields."""

from __future__ import annotations

from typing import Any


def project_json(
    project_id: str = "p",
    *,
    status: str = "completed",
    **over: Any,
) -> dict[str, Any]:
    """A ProjectResponse-shaped dict. Extra keys override defaults."""
    body: dict[str, Any] = {
        "id": project_id,
        "org_id": "org-1",
        "created_by": "user-1",
        "name": "demo",
        "source_language_code": "en-us",
        "status": status,
    }
    body.update(over)
    return body


def project_list_json(
    projects: list[dict[str, Any]],
    *,
    number: int = 1,
    has_more: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """A ProjectListResponse-shaped dict."""
    return {
        "projects": projects,
        "page": {"number": number, "has_more": has_more, "limit": limit},
    }


def language_list_json() -> dict[str, Any]:
    """A LanguageListResponse-shaped dict with an ambiguous `fr` prefix."""
    languages = [
        {"bcp47": "ja-jp", "name": "Japanese"},
        {"bcp47": "fr-fr", "name": "French (France)"},
        {"bcp47": "fr-ca", "name": "French (Canada)"},
        {"bcp47": "en-us", "name": "English (US)"},
    ]
    return {
        "languages": languages,
        "page": {"number": 1, "has_more": False, "limit": len(languages)},
    }


def flag_finding_json(
    finding_id: str = "flag-1",
    *,
    segment_id: str = "seg-1",
    **over: Any,
) -> dict[str, Any]:
    """A FlagFinding-shaped dict."""
    body: dict[str, Any] = {
        "kind": "flag",
        "id": finding_id,
        "segment_id": segment_id,
        "segment_index": 0,
        "locale_code": "ja-jp",
        "severity": "critical",
        "category": "terminology",
        "description": "bad term",
        "status": "open",
    }
    body.update(over)
    return body


def agent_finding_json(
    finding_id: str = "find-1",
    *,
    segment_id: str = "seg-1",
    **over: Any,
) -> dict[str, Any]:
    """An AgentFinding-shaped dict."""
    body: dict[str, Any] = {
        "kind": "agent_finding",
        "id": finding_id,
        "segment_id": segment_id,
        "segment_index": 0,
        "locale_code": "ja-jp",
        "agent_code": "term-check",
        "finding_type": "substitution",
        "term": "widget",
        "replacement": "gadget",
    }
    body.update(over)
    return body


def finding_list_json(
    findings: list[dict[str, Any]],
    *,
    has_more: bool = False,
    limit: int = 50,
    after: str | None = None,
) -> dict[str, Any]:
    """A FindingListResponse-shaped dict. page.number is always 1."""
    return {
        "findings": findings,
        "page": {"number": 1, "has_more": has_more, "limit": limit, "after": after},
    }


def chain_of_custody_json(
    project_id: str = "p",
    *,
    created_via: str = "api",
    **over: Any,
) -> dict[str, Any]:
    """A ChainOfCustodyResponse-shaped dict."""
    body: dict[str, Any] = {
        "id": project_id,
        "name": "demo",
        "created_via": created_via,
        "created_by": "user-1",
        "created_by_api_key_id": "key-1" if created_via == "api" else None,
        "created_at": "2026-08-20T00:00:00Z",
        "source_files": [
            {
                "id": "file-1",
                "file_name": "hello.txt",
                "file_type": "txt",
                "word_count": 2,
                "character_count": 12,
                "segment_count": 1,
            }
        ],
        "deliverables": [
            {
                "id": "deliv-1",
                "source_file_id": "file-1",
                "locale_code": "ja-jp",
                "file_type": "verified_doc",
                "name": "hello_Japanese.txt",
                "created_at": "2026-08-20T00:01:00Z",
                "superseded_at": None,
            }
        ],
    }
    body.update(over)
    return body


def human_review_json(**over: Any) -> dict[str, Any]:
    """A HumanReviewResponse-shaped dict."""
    body: dict[str, Any] = {
        "status": "queued",
        "service_plan": ["TRANSLATION"],
        "charged_tc": 0,
        "requested_at": "2026-08-01T00:00:00Z",
    }
    body.update(over)
    return body
