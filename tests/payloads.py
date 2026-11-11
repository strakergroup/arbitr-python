"""Minimal JSON bodies that satisfy published required fields."""

from __future__ import annotations

from typing import Any


def balance_json(balance: float = 1, **over: Any) -> dict[str, Any]:
    """A CreditBalanceResponse-shaped dict. Extra keys override defaults."""
    body: dict[str, Any] = {
        "balance": balance,
        "intelligence_credits": balance,
        "trust_credits": 0,
    }
    body.update(over)
    return body


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


def text_translate_json(ref: str = "r1", *, status: str = "translated") -> dict[str, Any]:
    """A TextTranslateResponse-shaped dict with one text and one target."""
    return {
        "results": [
            {
                "ref": ref,
                "detected_language_code": "en-us",
                "translations": [
                    {
                        "target_language_code": "fr-fr",
                        "status": status,
                        "text": "Bonjour",
                        "intelligence_credits": 1,
                    }
                ],
            }
        ]
    }


def connection_json(**over: Any) -> dict[str, Any]:
    """A ConnectionResponse-shaped dict."""
    body: dict[str, Any] = {
        "id": "conn-1",
        "provider": "slack",
        "tenant_id": "slack:E0789",
        "tenant_kind": "enterprise",
        "tenant_name": "Example",
        "scopes": ["verify:read"],
        "status": "active",
    }
    body.update(over)
    return body


def usage_list_json(*, number: int = 1, has_more: bool = False) -> dict[str, Any]:
    """A UsageListResponse-shaped dict with one text-translation charge."""
    return {
        "usage": [
            {
                "id": "tx-1",
                "created_at": "2026-10-01T00:00:00Z",
                "project_id": None,
                "usage_type": "channel",
                "target_language_codes": ["fr-fr"],
                "unit": "character",
                "quantity": 120,
            }
        ],
        "page": {"number": number, "has_more": has_more, "limit": 50},
    }


def quote_json(project_id: str = "p", *, version: int = 1, **over: Any) -> dict[str, Any]:
    """A QuoteResponse-shaped dict. Extra keys override defaults."""
    body: dict[str, Any] = {
        "project_id": project_id,
        "status": "ready",
        "version": version,
        "lines": [
            {
                "file_id": "f-1",
                "file_name": "a.docx",
                "target_language_code": "fr-fr",
                "stage": "AI_TRANSLATION",
                "unit": "character",
                "quantity": 1200,
                "intelligence_credits": 3.5,
            }
        ],
        "fees": [
            {
                "file_id": "f-1",
                "file_name": "a.pdf",
                "kind": "pdf_conversion",
                "unit": "page",
                "quantity": 2,
                "intelligence_credits": 1.0,
            }
        ],
        "intelligence_credits": 4.5,
        "expires_at": "2026-10-22T10:00:00Z",
    }
    body.update(over)
    return body


def webhook_json(webhook_id: str = "w-1", **over: Any) -> dict[str, Any]:
    """A WebhookResponse-shaped dict. Extra keys override defaults."""
    body: dict[str, Any] = {
        "id": webhook_id,
        "url": "https://example.com/hooks",
        "event_types": ["project.completed"],
        "mode": "live",
        "status": "active",
        "consecutive_failures": 0,
        "created_at": "2026-11-01T00:00:00Z",
    }
    body.update(over)
    return body


def webhook_delivery_json(delivery_id: str = "d-1", **over: Any) -> dict[str, Any]:
    """A WebhookDelivery-shaped dict, built from the published required fields."""
    body: dict[str, Any] = {
        "id": delivery_id,
        "event_id": "e-1",
        "event": "project.completed",
        "status": "failed",
        "attempts": 1,
        "created_at": "2026-11-01T00:00:00Z",
    }
    body.update(over)
    return body
