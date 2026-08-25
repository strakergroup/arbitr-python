"""SDK unit tests — HTTP is mocked with httpx.MockTransport (no network)."""

from __future__ import annotations

import json
import tempfile
import zipfile
from io import BytesIO
from typing import Any

import httpx
import pytest

from arbitr import (
    SUPPORTED_FORMATS,
    ActionRequiredError,
    AmbiguousLocaleCodesError,
    ArbitrBaseError,
    ArbitrClient,
    ArbitrClientError,
    ArbitrError,
    AuthenticationError,
    BareLocaleCodeError,
    ClientInputError,
    DisallowedFileExtensionError,
    MissingApiKeyError,
    NotFoundError,
    ProjectWaitTimeoutError,
    RateLimitError,
    ResponseDecodeError,
    ResponseParseError,
    UnknownLocaleCodesError,
    ValidationError,
)
from payloads import human_review_json, project_json, project_list_json


def make_client(handler: Any) -> ArbitrClient:
    return ArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
    )


def test_auth_headers_sent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "py_test_abc123"
        assert request.headers["X-API-Version"] == "1"
        assert request.headers["User-Agent"].startswith("arbitr-python/")
        return httpx.Response(200, json={"balance": 100, "currency": "credits"})

    client = make_client(handler)
    assert client.credits.balance().balance == 100


def test_projects_iterate_follows_page_numbers() -> None:
    pages = {
        "1": project_list_json([project_json("p1")], number=1, has_more=True, limit=1),
        "2": project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        assert request.url.params.get("limit") == "1"
        assert page in pages
        return httpx.Response(200, json=pages[page])

    client = make_client(handler)
    ids = [p.id for p in client.projects.iterate(limit=1)]
    assert ids == ["p1", "p2"]


def test_projects_list_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("modified_after") == "2026-07-26T00:00:00Z"
        assert request.url.params.get("status") == "completed"
        assert request.url.params.get("page") == "2"
        return httpx.Response(
            200,
            json=project_list_json([], number=2, has_more=False, limit=50),
        )

    client = make_client(handler)
    client.projects.list(page=2, modified_after="2026-07-26T00:00:00Z", status="completed")


def test_submit_builds_multipart(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello world")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects"
        captured["content_type"] = request.headers["content-type"]
        captured["idem"] = request.headers.get("Idempotency-Key")
        captured["body"] = request.content
        return httpx.Response(201, json=project_json("proj-1", status="extracting"))

    client = make_client(handler)
    project = client.projects.submit(
        files=[doc],
        name="demo",
        target_language_codes=["ko-kr", "fr-fr"],
        idempotency_key="key-123",
    )

    assert project.id == "proj-1"
    assert captured["content_type"].startswith("multipart/form-data")
    assert captured["idem"] == "key-123"
    body = captured["body"]
    assert b'name="name"' in body and b"demo" in body
    assert b'name="target_language_codes"' in body
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in body
    assert b'name="source_language_code"' in body
    assert b"en-us" in body
    assert b'name="workflow"' in body
    assert json.dumps(["AI_TRANSLATION"]).encode() in body
    assert b'filename="hello.txt"' in body
    assert b"hello world" in body


def test_submit_rejects_disallowed_extension(tmp_path: Any) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(DisallowedFileExtensionError, match="allowlist") as de:
        client.projects.submit(files=[exe], name="x", target_language_codes=["ko-kr"])
    assert de.value.filename == "evil.exe"
    assert de.value.extension == ".exe"
    assert de.value.supported_formats == SUPPORTED_FORMATS
    assert ".docx" in de.value.supported_formats


def test_submit_rejects_disallowed_extension_on_bytes_tuple() -> None:
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(DisallowedFileExtensionError) as de:
        client.projects.submit(
            files=[("evil.exe", b"MZ")], name="x", target_language_codes=["ko-kr"]
        )
    assert de.value.extension == ".exe"


def test_submit_extension_check_off_allows_anything(tmp_path: Any) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    client = make_client(lambda r: httpx.Response(201, json=project_json("p")))
    project = client.projects.submit(
        files=[exe], name="x", target_language_codes=["ko-kr"], extension_check="off"
    )
    assert project.id == "p"


def test_submit_rejects_empty_file_list() -> None:
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(ClientInputError, match="at least one file"):
        client.projects.submit(files=[], name="x", target_language_codes=["ko-kr"])


def test_submit_rejects_disallowed_extension_on_file_object(tmp_path: Any) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    client = make_client(lambda r: httpx.Response(500))
    with exe.open("rb") as handle, pytest.raises(DisallowedFileExtensionError) as de:
        client.projects.submit(files=[handle], name="x", target_language_codes=["ko-kr"])
    assert de.value.extension == ".exe"


def test_submit_rejects_invalid_extension_check() -> None:
    client = make_client(lambda r: httpx.Response(500))
    bogus_check: Any = "skip"
    with pytest.raises(ClientInputError, match="extension_check"):
        client.projects.submit(
            files=[("a.txt", b"hi")],
            name="x",
            target_language_codes=["ko-kr"],
            extension_check=bogus_check,
        )


def test_submit_rejects_over_total_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arbitr._constants.MAX_UPLOAD_TOTAL_BYTES", 4)
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(ClientInputError, match="upload too large"):
        client.projects.submit(
            files=[("a.txt", b"hello")],
            name="x",
            target_language_codes=["ko-kr"],
        )


def test_submit_rejects_unsupported_file_input() -> None:
    client = make_client(lambda r: httpx.Response(500))
    bad_files: list[Any] = [123]
    with pytest.raises(ClientInputError, match="unsupported file input"):
        client.projects.submit(files=bad_files, name="x", target_language_codes=["ko-kr"])


def test_submit_rejects_malformed_file_tuple() -> None:
    client = make_client(lambda r: httpx.Response(500))
    malformed: list[Any] = [("a.txt",)]
    with pytest.raises(ClientInputError, match="file tuples"):
        client.projects.submit(files=malformed, name="x", target_language_codes=["ko-kr"])


def test_submit_missing_path_is_a_client_error() -> None:
    """A missing file must not leak FileNotFoundError past ArbitrBaseError."""
    client = make_client(lambda r: httpx.Response(500))
    with pytest.raises(ClientInputError, match="cannot read upload") as raised:
        client.projects.submit(
            files=["/no/such/arbitr-upload.txt"],
            name="x",
            target_language_codes=["ko-kr"],
        )
    assert isinstance(raised.value, ArbitrBaseError)
    assert isinstance(raised.value.__cause__, FileNotFoundError)


def test_submit_text_mode_handle_is_a_client_error(tmp_path: Any) -> None:
    """httpx TypeError on text-mode handles must not reach the caller."""
    path = tmp_path / "note.txt"
    path.write_text("hello")
    client = make_client(lambda r: httpx.Response(500))
    with path.open("r") as handle, pytest.raises(ClientInputError, match="binary mode"):
        client.projects.submit(files=[handle], name="x", target_language_codes=["ko-kr"])


def test_submit_unnamed_temporary_file() -> None:
    client = make_client(lambda r: httpx.Response(201, json=project_json("p")))
    with tempfile.TemporaryFile() as handle:
        handle.write(b"hello")
        handle.seek(0)
        project = client.projects.submit(
            files=[handle],
            name="x",
            target_language_codes=["ko-kr"],
            extension_check="off",
        )
    assert project.id == "p"


def test_submit_workflow_and_due_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        assert json.dumps(["AI_TRANSLATION", "TRANSLATION"]).encode() in body
        assert b'name="due_date"' in body and b"2026-08-01" in body
        return httpx.Response(201, json=project_json("p-3"))

    client = make_client(handler)
    client.projects.submit(
        files=[("a.txt", b"hi")],
        name="wf",
        target_language_codes=["ja-jp"],
        workflow=["AI_TRANSLATION", "TRANSLATION"],
        due_date="2026-08-01",
    )


def test_wait_polls_until_terminal() -> None:
    statuses = iter(["extracting", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


def test_wait_raises_on_agent_selection_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status="agent_selection"))

    client = make_client(handler)
    with pytest.raises(ActionRequiredError) as ar:
        client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert ar.value.status == "agent_selection"
    assert ar.value.project_id == "p"
    assert "Start Campaign" in str(ar.value)
    assert ar.value.ui_url == "https://test/projects/p/agents"


def test_wait_ignores_transient_agent_selection() -> None:
    statuses = iter(["agent_selection", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


def test_wait_through_gate_keeps_polling() -> None:
    statuses = iter(["agent_selection", "agent_selection", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01, on_action_required="wait")
    assert final.status == "completed"


def test_wait_awaiting_payment_mentions_credits() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status="awaiting_payment"))

    client = make_client(handler)
    with pytest.raises(ActionRequiredError, match="arbitr resume") as ar:
        client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert "credits" in str(ar.value)


def test_wait_rejects_bad_mode() -> None:
    client = make_client(lambda r: httpx.Response(200, json={}))
    bogus_mode: Any = "bogus"
    with pytest.raises(ClientInputError, match="on_action_required"):
        client.projects.wait("p", on_action_required=bogus_mode)


def test_wait_treats_cancelled_as_terminal() -> None:
    """Regression: `cancelled` was not terminal, so wait() polled to the timeout."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=project_json("p", status="cancelled"))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "cancelled"
    assert calls["n"] == 1


def test_submit_lowercases_locale_codes() -> None:
    """The API accepts lowercase BCP-47 tags only; mixed case must be folded."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(201, json=project_json("p"))

    client = make_client(handler)
    client.projects.submit(
        files=[("a.txt", b"hi")],
        name="x",
        target_language_codes=["KO-KR", "fr-FR"],
        source_language_code="EN-US",
    )
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in captured["body"]
    assert b"KO-KR" not in captured["body"]
    assert b"EN-US" not in captured["body"]


def test_submit_rejects_bare_locale_codes() -> None:
    client = make_client(lambda _request: httpx.Response(500))
    with pytest.raises(BareLocaleCodeError) as raised:
        client.projects.submit(
            files=[("a.txt", b"hi")],
            name="x",
            target_language_codes=["ko"],
        )
    assert raised.value.code == "ko"


def test_wait_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status="translating"))

    client = make_client(handler)
    with pytest.raises(ProjectWaitTimeoutError) as te:
        client.projects.wait("p", timeout=0.05, poll_interval=0.01)
    assert te.value.project_id == "p"
    assert te.value.status == "translating"


def test_download_zip(tmp_path: Any) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("out_ko.xliff", "<xliff/>")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects/p/deliverables"
        assert request.url.params.get("format") == "zip"
        return httpx.Response(
            200, content=buf.getvalue(), headers={"content-type": "application/zip"}
        )

    client = make_client(handler)
    dest = tmp_path / "deliv.zip"
    assert client.projects.download_zip("p", dest) == dest
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["out_ko.xliff"]


def test_failed_download_leaves_existing_dest(tmp_path: Any) -> None:
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"keep-me")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": "not_found", "message": "nope"}},
        )

    client = make_client(handler)
    with pytest.raises(NotFoundError):
        client.projects.download_deliverable("p", "d-1", dest)
    assert dest.read_bytes() == b"keep-me"


def test_redirect_is_not_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/elsewhere"})

    client = make_client(handler)
    with pytest.raises(ArbitrError) as exc:
        client.get_json("/v1/me")
    assert exc.value.status_code == 302


def test_error_envelope_maps_to_typed_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/missing":
            return httpx.Response(
                404,
                json={"error": {"code": "not_found", "message": "nope", "request_id": "r-1"}},
            )
        if request.url.path == "/bad":
            return httpx.Response(
                422,
                json={
                    "error": {
                        "code": "validation_error",
                        "message": "bad input",
                        "request_id": "r-2",
                        "field_errors": [{"field": "target_language_codes", "message": "required"}],
                    }
                },
            )
        return httpx.Response(
            429,
            json={"error": {"code": "rate_limited", "message": "slow down", "request_id": "r-3"}},
            headers={"Retry-After": "7"},
        )

    client = make_client(handler)

    with pytest.raises(NotFoundError) as nf:
        client.get_json("/missing")
    assert nf.value.request_id == "r-1"

    with pytest.raises(ValidationError) as ve:
        client.get_json("/bad")
    assert ve.value.field_errors == [{"field": "target_language_codes", "message": "required"}]

    with pytest.raises(RateLimitError) as rl:
        client.get_json("/limited")
    assert rl.value.retry_after == 7.0


def test_languages_resolve_normalizes_and_rejects() -> None:
    langs = {
        "languages": [
            {"bcp47": "ja-jp", "name": "Japanese"},
            {"bcp47": "fr-fr", "name": "French (France)"},
            {"bcp47": "fr-ca", "name": "French (Canada)"},
            {"bcp47": "en-us", "name": "English (US)"},
        ],
        "page": {"number": 1, "has_more": False, "limit": 4},
    }
    client = make_client(lambda r: httpx.Response(200, json=langs))

    assert client.languages.resolve(["JA-JP", "Fr-Fr"]) == ["ja-jp", "fr-fr"]
    assert client.languages.resolve(["ja"]) == ["ja-jp"]
    with pytest.raises(AmbiguousLocaleCodesError) as amb:
        client.languages.resolve(["fr"])
    assert amb.value.code == "fr"
    assert amb.value.matches == ["fr-ca", "fr-fr"]
    with pytest.raises(UnknownLocaleCodesError, match="unknown locale_codes") as ue:
        client.languages.resolve(["ja-jp", "xx-garbage"])
    assert ue.value.codes == ["xx-garbage"]


def test_key_mode_prefixes() -> None:
    assert ArbitrClient(api_key="py_live_x").key_mode == "live"
    assert ArbitrClient(api_key="abr_live_x").key_mode == "live"
    assert ArbitrClient(api_key="py_test_x").key_mode == "test"
    assert ArbitrClient(api_key="abr_test_x").key_mode == "test"
    assert ArbitrClient(api_key="whatever").key_mode == "unknown"


def test_me_and_v1_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/me"
        return httpx.Response(
            200,
            json={"org_id": "org-1", "mode": "live", "scopes": ["verify:read"]},
        )

    client = make_client(handler)
    assert client.me().scopes == ["verify:read"]


def test_download_single_deliverable(tmp_path: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects/p/deliverables/d-1"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx.Response(200, content=b"<xliff/>")

    client = make_client(handler)
    dest = tmp_path / "one.xliff"
    assert client.projects.download_deliverable("p", "d-1", dest) == dest
    assert dest.read_bytes() == b"<xliff/>"


def test_get_rejects_body_that_misses_required_fields() -> None:
    client = make_client(lambda r: httpx.Response(200, json={"id": "p"}))
    with pytest.raises(ResponseParseError, match="getProject"):
        client.projects.get("p")


def test_malformed_2xx_json_is_a_typed_error() -> None:
    client = make_client(lambda _request: httpx.Response(200, content=b"<html>nope</html>"))
    with pytest.raises(ResponseDecodeError, match="/v1/me") as raised:
        client.me()
    assert raised.value.operation == "/v1/me"
    assert isinstance(raised.value, ArbitrClientError)


def test_resume_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/review/resumptions"):
            return httpx.Response(200, json=human_review_json())
        return httpx.Response(200, json={"project_id": "p", "status": "completed"})

    client = make_client(handler)
    resumed = client.projects.resume("p")
    review = client.projects.resume_human_review("p")
    assert seen == [
        "/v1/projects/p/resumptions",
        "/v1/projects/p/review/resumptions",
    ]
    assert resumed.project_id == "p"
    assert resumed.status == "completed"
    assert review.status == "queued"


def test_insufficient_scope_carries_required_scope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "error": {
                    "code": "insufficient_scope",
                    "message": "missing scope",
                    "request_id": "r-1",
                    "required_scope": "verify:read",
                }
            },
        )

    client = make_client(handler)
    with pytest.raises(AuthenticationError) as ae:
        client.projects.get("p")
    assert ae.value.code == "insufficient_scope"
    assert ae.value.extra["required_scope"] == "verify:read"


def test_unsupported_upload_422_carries_supported_formats() -> None:
    formats = [".csv", ".docx", ".txt"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "validation_failed",
                    "message": "Unsupported file type: '.exe'",
                    "request_id": "r-2",
                    "supported_formats": formats,
                }
            },
        )

    client = make_client(handler)
    with pytest.raises(ValidationError) as ve:
        client.projects.submit(
            files=[("evil.exe", b"MZ")],
            name="x",
            target_language_codes=["ja-jp"],
            extension_check="off",
        )
    assert ve.value.supported_formats == formats


def test_ui_url_derivation() -> None:
    c = ArbitrClient(api_key="k", base_url="https://api-arbitr.straker.ai")
    assert c.ui_base_url == "https://arbitr.straker.ai"
    assert c.project_url("p1") == "https://arbitr.straker.ai/projects/p1"
    assert c.project_url("p1", view="agents") == "https://arbitr.straker.ai/projects/p1/agents"

    c2 = ArbitrClient(api_key="k", base_url="https://api.arbitr.com")
    assert c2.ui_base_url == "https://arbitr.com"

    c3 = ArbitrClient(api_key="k", base_url="https://api.test", ui_base_url="https://ui.custom")
    assert c3.ui_base_url == "https://ui.custom"


def test_from_env_reads_dotenv(tmp_path: Any, monkeypatch: Any) -> None:
    env = tmp_path / ".env"
    env.write_text("arbitr_api_key=py_test_fromfile\narbitr_api_domain=https://api.example\n")
    for var in ("ARBITR_API_KEY", "arbitr_api_key", "ARBITR_BASE_URL", "arbitr_api_domain"):
        monkeypatch.delenv(var, raising=False)
    client = ArbitrClient.from_env(env)
    assert client.api_key == "py_test_fromfile"
    assert client.base_url == "https://api.example"
    assert client.max_retries == 0


def test_from_env_reads_max_retries(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    env.write_text("ARBITR_API_KEY=k\nARBITR_MAX_RETRIES=4\n")
    monkeypatch.delenv("ARBITR_MAX_RETRIES", raising=False)
    client = ArbitrClient.from_env(env)
    assert client.max_retries == 4


def test_from_env_env_alias_beats_dotenv_canonical(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text("ARBITR_API_KEY=fromfile\n")
    monkeypatch.delenv("ARBITR_API_KEY", raising=False)
    monkeypatch.setenv("arbitr_api_key", "fromenv")
    client = ArbitrClient.from_env(env)
    assert client.api_key == "fromenv"


def test_from_env_without_key_raises_precise_error(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARBITR_API_KEY", raising=False)
    monkeypatch.delenv("arbitr_api_key", raising=False)
    with pytest.raises(MissingApiKeyError, match="ARBITR_API_KEY") as missing:
        ArbitrClient.from_env(tmp_path / "absent.env")
    assert "https://arbitr.straker.ai/settings/api-keys" in str(missing.value)


def test_empty_key_raises_precise_error() -> None:
    with pytest.raises(MissingApiKeyError, match="api_key is required"):
        ArbitrClient(api_key="")


def test_default_base_url_is_prod() -> None:
    client = ArbitrClient(api_key="k")
    assert client.base_url == "https://api-arbitr.straker.ai"


def test_client_input_errors_are_not_value_error() -> None:
    assert not issubclass(ClientInputError, ValueError)
    assert issubclass(ClientInputError, ArbitrClientError)
    assert issubclass(ActionRequiredError, ArbitrClientError)
    assert issubclass(ProjectWaitTimeoutError, TimeoutError)
    assert issubclass(ProjectWaitTimeoutError, ArbitrClientError)
    assert issubclass(ResponseParseError, ArbitrClientError)
    assert issubclass(ResponseDecodeError, ArbitrClientError)
