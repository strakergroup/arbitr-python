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
