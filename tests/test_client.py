"""SDK unit tests — HTTP is mocked with httpx2.MockTransport (no network)."""

from __future__ import annotations

import json
import tempfile
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from typing import Any

import httpx
import httpx2
import pytest

import arbitr
from arbitr import (
    DEFAULT_UI_URL,
    SUPPORTED_FORMATS,
    ActionRequiredError,
    AmbiguousLocaleCodesError,
    ApiMovedError,
    ArbitrBaseError,
    ArbitrClient,
    ArbitrClientError,
    ArbitrError,
    AuthenticationError,
    ClientInputError,
    ConnectionStatus,
    DisallowedFileExtensionError,
    FindingSeverity,
    FindingsKeysetError,
    FindingStatus,
    MissingApiKeyError,
    NotFoundError,
    ProjectWaitTimeoutError,
    QuotePair,
    QuoteStage,
    QuoteStatus,
    RateLimitError,
    Requester,
    RequesterSource,
    ResponseDecodeError,
    ResponseParseError,
    TextToTranslate,
    TextTranslationStatus,
    UnknownLocaleCodesError,
    UsageUnit,
    ValidationError,
)
from payloads import (
    agent_finding_json,
    balance_json,
    chain_of_custody_json,
    connection_json,
    finding_list_json,
    flag_finding_json,
    human_review_json,
    project_json,
    project_list_json,
    quote_json,
    text_translate_json,
    usage_list_json,
    webhook_json,
)
from webhook_cases import WEBHOOK_CALL_IDS, WEBHOOK_CALLS


def make_client(handler: Any) -> ArbitrClient:
    return ArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx2.MockTransport(handler),
    )


def test_auth_headers_sent() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["X-API-Key"] == "py_test_abc123"
        assert request.headers["X-API-Version"] == "1"
        assert request.headers["User-Agent"].startswith("arbitr-python/")
        return httpx2.Response(200, json=balance_json(100))

    client = make_client(handler)
    assert client.credits.balance().balance == 100


def test_projects_iterate_follows_page_numbers() -> None:
    pages = {
        "1": project_list_json([project_json("p1")], number=1, has_more=True, limit=1),
        "2": project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = request.url.params.get("page")
        assert request.url.params.get("limit") == "1"
        assert page in pages
        return httpx2.Response(200, json=pages[page])

    client = make_client(handler)
    ids = [p.id for p in client.projects.iterate(limit=1)]
    assert ids == ["p1", "p2"]


def test_iterate_projects_resumes_from_page() -> None:
    """``page`` starts the walk, mirroring ``iterate_findings(after=...)``."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("page") == "2"
        return httpx2.Response(
            200,
            json=project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
        )

    client = make_client(handler)
    ids = [p.id for p in client.projects.iterate(limit=1, page=2)]
    assert ids == ["p2"]


def test_projects_list_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("modified_after") == "2026-07-26T00:00:00Z"
        assert request.url.params.get("status") == "completed"
        assert request.url.params.get("page") == "2"
        return httpx2.Response(
            200,
            json=project_list_json([], number=2, has_more=False, limit=50),
        )

    client = make_client(handler)
    client.projects.list(page=2, modified_after="2026-07-26T00:00:00Z", status="completed")


def test_projects_list_requester_and_search_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("requester_tenant_id") == "E0789"
        assert request.url.params.get("requester_external_id") == "U0123"
        assert request.url.params.get("q") == "contract"
        return httpx2.Response(200, json=project_list_json([project_json("p1")]))

    client = make_client(handler)
    ids = [
        p.id
        for p in client.projects.iterate(
            requester_tenant_id="E0789", requester_external_id="U0123", q="contract"
        )
    ]
    assert ids == ["p1"]


@pytest.mark.parametrize(("tenant_id", "external_id"), [("E0789", None), (None, "U0123")])
def test_projects_list_rejects_half_a_requester(
    tenant_id: str | None, external_id: str | None
) -> None:
    client = make_client(lambda r: pytest.fail("no request expected"))
    with pytest.raises(ClientInputError, match="together"):
        client.projects.list(requester_tenant_id=tenant_id, requester_external_id=external_id)


def test_text_translate_posts_texts_and_parses_statuses() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/text/translate"
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=text_translate_json("r1"))

    client = make_client(handler)
    result = client.text.translate(
        [TextToTranslate(ref="r1", text="Hello", target_language_codes=["fr-fr"])],
        format="slack",
        usage_type="channel",
        requester=Requester(
            tenant_id="E0789", external_id="U0123", source=RequesterSource(app="slack")
        ),
    )
    assert captured["body"] == {
        "texts": [{"ref": "r1", "text": "Hello", "target_language_codes": ["fr-fr"]}],
        "format": "slack",
        "usage_type": "channel",
        "requester": {"tenant_id": "E0789", "external_id": "U0123", "source": {"app": "slack"}},
    }
    translation = result.results[0].translations[0]
    assert translation.status is TextTranslationStatus.translated
    assert translation.text == "Bonjour"


def test_text_translate_sends_only_the_texts_by_default() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=text_translate_json("r1", status="same_language"))

    client = make_client(handler)
    client.text.translate(
        [
            TextToTranslate(
                ref="r1",
                text="Bonjour",
                source_language_code="fr-fr",
                target_language_codes=["fr-ca"],
            )
        ]
    )
    assert captured["body"] == {
        "texts": [
            {
                "ref": "r1",
                "text": "Bonjour",
                "source_language_code": "fr-fr",
                "target_language_codes": ["fr-ca"],
            }
        ]
    }


def test_text_translate_sends_a_catalogue_tag_without_a_region() -> None:
    """``ar`` is a catalogue tag in its own right, unlike a bare ``fr``."""
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=text_translate_json("r1"))

    client = make_client(handler)
    client.text.translate([TextToTranslate(ref="r1", text="Hello", target_language_codes=["ar"])])
    assert captured["body"]["texts"][0]["target_language_codes"] == ["ar"]


def test_connection() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/connection"
        return httpx2.Response(200, json=connection_json())

    client = make_client(handler)
    connection = client.connection()
    assert connection.tenant_id == "slack:E0789"
    assert connection.status is ConnectionStatus.active


def test_usage_list_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/usage"
        assert request.url.params.get("from") == "2026-10-01T00:00:00Z"
        assert request.url.params.get("to") == "2026-11-01T00:00:00Z"
        assert request.url.params.get("page") == "2"
        assert request.url.params.get("limit") == "10"
        return httpx2.Response(200, json=usage_list_json(number=2))

    client = make_client(handler)
    usage = client.usage.list(
        from_="2026-10-01T00:00:00Z", to="2026-11-01T00:00:00Z", page=2, limit=10
    )
    assert usage.usage[0].unit is UsageUnit.character


def test_submit_builds_multipart(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello world")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects"
        captured["content_type"] = request.headers["content-type"]
        captured["idem"] = request.headers.get("Idempotency-Key")
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("proj-1", status="extracting"))

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
    client = make_client(lambda r: httpx2.Response(500))
    with pytest.raises(DisallowedFileExtensionError, match="allowlist") as de:
        client.projects.submit(files=[exe], name="x", target_language_codes=["ko-kr"])
    assert de.value.filename == "evil.exe"
    assert de.value.extension == ".exe"
    assert de.value.supported_formats == SUPPORTED_FORMATS
    assert ".docx" in de.value.supported_formats


def test_submit_rejects_disallowed_extension_on_bytes_tuple() -> None:
    client = make_client(lambda r: httpx2.Response(500))
    with pytest.raises(DisallowedFileExtensionError) as de:
        client.projects.submit(
            files=[("evil.exe", b"MZ")], name="x", target_language_codes=["ko-kr"]
        )
    assert de.value.extension == ".exe"


def test_submit_extension_check_off_allows_anything(tmp_path: Any) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    client = make_client(lambda r: httpx2.Response(201, json=project_json("p")))
    project = client.projects.submit(
        files=[exe], name="x", target_language_codes=["ko-kr"], extension_check="off"
    )
    assert project.id == "p"


def test_submit_rejects_empty_file_list() -> None:
    client = make_client(lambda r: httpx2.Response(500))
    with pytest.raises(ClientInputError, match="at least one file"):
        client.projects.submit(files=[], name="x", target_language_codes=["ko-kr"])


def test_submit_rejects_disallowed_extension_on_file_object(tmp_path: Any) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    client = make_client(lambda r: httpx2.Response(500))
    with exe.open("rb") as handle, pytest.raises(DisallowedFileExtensionError) as de:
        client.projects.submit(files=[handle], name="x", target_language_codes=["ko-kr"])
    assert de.value.extension == ".exe"


def test_submit_rejects_invalid_extension_check() -> None:
    client = make_client(lambda r: httpx2.Response(500))
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
    client = make_client(lambda r: httpx2.Response(500))
    with pytest.raises(ClientInputError, match="upload too large"):
        client.projects.submit(
            files=[("a.txt", b"hello")],
            name="x",
            target_language_codes=["ko-kr"],
        )


def test_submit_rejects_unsupported_file_input() -> None:
    client = make_client(lambda r: httpx2.Response(500))
    bad_files: list[Any] = [123]
    with pytest.raises(ClientInputError, match="unsupported file input"):
        client.projects.submit(files=bad_files, name="x", target_language_codes=["ko-kr"])


def test_submit_rejects_malformed_file_tuple() -> None:
    client = make_client(lambda r: httpx2.Response(500))
    malformed: list[Any] = [("a.txt",)]
    with pytest.raises(ClientInputError, match="file tuples"):
        client.projects.submit(files=malformed, name="x", target_language_codes=["ko-kr"])


def test_submit_missing_path_is_a_client_error() -> None:
    """A missing file must not leak FileNotFoundError past ArbitrBaseError."""
    client = make_client(lambda r: httpx2.Response(500))
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
    client = make_client(lambda r: httpx2.Response(500))
    with path.open("r") as handle, pytest.raises(ClientInputError, match="binary mode"):
        client.projects.submit(files=[handle], name="x", target_language_codes=["ko-kr"])


def test_submit_unnamed_temporary_file() -> None:
    client = make_client(lambda r: httpx2.Response(201, json=project_json("p")))
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
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = request.content
        assert json.dumps(["AI_TRANSLATION", "TRANSLATION"]).encode() in body
        assert b'name="due_date"' in body and b"2026-08-01" in body
        return httpx2.Response(201, json=project_json("p-3"))

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

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


def test_wait_raises_on_agent_selection_gate() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="agent_selection"))

    client = make_client(handler)
    with pytest.raises(ActionRequiredError) as ar:
        client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert ar.value.status == "agent_selection"
    assert ar.value.project_id == "p"
    assert "Start Campaign" in str(ar.value)
    assert ar.value.ui_url == "https://test/projects/p/agents"


def test_wait_ignores_transient_agent_selection() -> None:
    statuses = iter(["agent_selection", "translating", "completed"])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


def test_wait_through_gate_keeps_polling() -> None:
    statuses = iter(["agent_selection", "agent_selection", "translating", "completed"])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01, on_action_required="wait")
    assert final.status == "completed"


def test_wait_awaiting_payment_mentions_credits() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="awaiting_payment"))

    client = make_client(handler)
    with pytest.raises(ActionRequiredError, match="arbitr resume") as ar:
        client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert "credits" in str(ar.value)


def test_wait_rejects_bad_mode() -> None:
    client = make_client(lambda r: httpx2.Response(200, json={}))
    bogus_mode: Any = "bogus"
    with pytest.raises(ClientInputError, match="on_action_required"):
        client.projects.wait("p", on_action_required=bogus_mode)


def test_wait_treats_cancelled_as_terminal() -> None:
    """Regression: `cancelled` was not terminal, so wait() polled to the timeout."""
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(200, json=project_json("p", status="cancelled"))

    client = make_client(handler)
    final = client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "cancelled"
    assert calls["n"] == 1


def test_submit_lowercases_locale_codes() -> None:
    """The API accepts lowercase BCP-47 tags only; mixed case must be folded."""
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

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


def test_submit_sends_a_catalogue_tag_without_a_region() -> None:
    """``ar`` is a catalogue tag in its own right; the API judges a bare ``ko``."""
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

    client = make_client(handler)
    client.projects.submit(files=[("a.txt", b"hi")], name="x", target_language_codes=["AR"])
    assert json.dumps(["ar"]).encode() in captured["body"]


def test_wait_times_out() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="translating"))

    client = make_client(handler)
    with pytest.raises(ProjectWaitTimeoutError) as te:
        client.projects.wait("p", timeout=0.05, poll_interval=0.01)
    assert te.value.project_id == "p"
    assert te.value.status == "translating"


def test_download_zip(tmp_path: Any) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("out_ko.xliff", "<xliff/>")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/deliverables"
        assert request.url.params.get("format") == "zip"
        return httpx2.Response(
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

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            404,
            json={"error": {"code": "not_found", "message": "nope"}},
        )

    client = make_client(handler)
    with pytest.raises(NotFoundError):
        client.projects.download_deliverable("p", "d-1", dest)
    assert dest.read_bytes() == b"keep-me"


def test_redirect_is_not_success() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(302, headers={"location": "/elsewhere"})

    client = make_client(handler)
    with pytest.raises(ArbitrError) as exc:
        client.get_json("/v1/me")
    assert exc.value.status_code == 302


def test_redirects_are_never_followed() -> None:
    """Following a redirect would forward X-API-Key to whatever host it names."""
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(301, headers={"location": "https://evil.example/v1/me"})

    client = make_client(handler)
    with pytest.raises(ApiMovedError) as raised:
        client.get_json("/v1/me")
    assert raised.value.moved_to == "https://evil.example"
    assert seen == ["https://api.test/v1/me"]


def test_streamed_download_from_a_moved_host_names_the_new_one(tmp_path: Any) -> None:
    """Downloads stream the body, so the error path must read it before parsing."""
    dest = tmp_path / "out.zip"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            301,
            headers={"location": "https://api.arbitr.ai/v1/projects/p/deliverables/d-1"},
            stream=httpx2.ByteStream(b"<html>moved</html>"),
        )

    client = make_client(handler)
    with pytest.raises(ApiMovedError) as raised:
        client.projects.download_deliverable("p", "d-1", dest)
    assert raised.value.moved_to == "https://api.arbitr.ai"
    assert not dest.exists()


def test_streamed_download_error_body_is_read_before_parsing(tmp_path: Any) -> None:
    dest = tmp_path / "out.zip"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            404,
            stream=httpx2.ByteStream(b'{"error": {"code": "not_found", "message": "gone"}}'),
            headers={"content-type": "application/json"},
        )

    client = make_client(handler)
    with pytest.raises(NotFoundError, match="gone"):
        client.projects.download_deliverable("p", "d-1", dest)


def test_error_envelope_maps_to_typed_errors() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/missing":
            return httpx2.Response(
                404,
                json={"error": {"code": "not_found", "message": "nope", "request_id": "r-1"}},
            )
        if request.url.path == "/bad":
            return httpx2.Response(
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
        return httpx2.Response(
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
    client = make_client(lambda r: httpx2.Response(200, json=langs))

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
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/me"
        return httpx2.Response(
            200,
            json={"org_id": "org-1", "mode": "live", "scopes": ["verify:read"]},
        )

    client = make_client(handler)
    assert client.me().scopes == ["verify:read"]


def test_download_single_deliverable(tmp_path: Any) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/deliverables/d-1"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx2.Response(200, content=b"<xliff/>")

    client = make_client(handler)
    dest = tmp_path / "one.xliff"
    assert client.projects.download_deliverable("p", "d-1", dest) == dest
    assert dest.read_bytes() == b"<xliff/>"


def test_findings_page_and_filters() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/findings"
        assert request.url.params.get("limit") == "10"
        assert request.url.params.get("severity") == "critical"
        assert request.url.params.get("status") == "open"
        assert request.url.params.get("category") == "terminology"
        assert "page" not in request.url.params
        return httpx2.Response(
            200,
            json=finding_list_json([flag_finding_json()], has_more=False, limit=10),
        )

    client = make_client(handler)
    body = client.projects.findings(
        "p",
        limit=10,
        severity=FindingSeverity.critical,
        status=FindingStatus.open,
        category="terminology",
    )
    assert [item.kind for item in body.findings] == ["flag"]
    assert body.page.number == 1
    assert body.page.after is None


def test_iterate_findings_walks_after() -> None:
    pages = {
        None: finding_list_json(
            [flag_finding_json("flag-1")], has_more=True, limit=1, after="0:0:flag-1"
        ),
        "0:0:flag-1": finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/findings"
        assert "page" not in request.url.params
        token = request.url.params.get("after")
        assert token in pages
        return httpx2.Response(200, json=pages[token])

    client = make_client(handler)
    kinds = [item.kind for item in client.projects.iterate_findings("p", limit=1)]
    assert kinds == ["flag", "agent_finding"]


def test_findings_filters_accept_plain_strings() -> None:
    """The enums are a hint, not a gate — a new server-side value still works."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("severity") == "critical"
        assert request.url.params.get("status") == "open"
        return httpx2.Response(200, json=finding_list_json([flag_finding_json()]))

    client = make_client(handler)
    body = client.projects.findings("p", severity="critical", status="open")
    assert [item.kind for item in body.findings] == ["flag"]


def test_iterate_findings_continues_on_empty_page() -> None:
    """A skipped window can still have more pages — do not stop on an empty list."""
    pages = {
        None: finding_list_json([], has_more=True, limit=1, after="skip-1"),
        "skip-1": finding_list_json([flag_finding_json("flag-1")], has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        token = request.url.params.get("after")
        assert token in pages
        return httpx2.Response(200, json=pages[token])

    client = make_client(handler)
    ids = [item.id for item in client.projects.iterate_findings("p", limit=1)]
    assert ids == ["flag-1"]


def test_iterate_findings_resumes_from_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("after") == "0:0:flag-1"
        return httpx2.Response(
            200,
            json=finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
        )

    client = make_client(handler)
    kinds = [
        item.kind for item in client.projects.iterate_findings("p", limit=1, after="0:0:flag-1")
    ]
    assert kinds == ["agent_finding"]


def test_iterate_findings_raises_when_after_does_not_advance() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=finding_list_json(
                [flag_finding_json("flag-1")], has_more=True, limit=1, after="same"
            ),
        )

    client = make_client(handler)
    got: list[str] = []
    with pytest.raises(FindingsKeysetError, match="did not advance"):
        for item in client.projects.iterate_findings("p", limit=1):
            got.append(item.id)
    assert got == ["flag-1", "flag-1"]


def test_iterate_findings_raises_when_has_more_without_after() -> None:
    client = make_client(
        lambda _r: httpx2.Response(
            200,
            json=finding_list_json([flag_finding_json("flag-1")], has_more=True, limit=1),
        )
    )
    got: list[str] = []
    with pytest.raises(FindingsKeysetError, match="did not advance") as raised:
        for item in client.projects.iterate_findings("p"):
            got.append(item.id)
    assert got == ["flag-1"]
    assert raised.value.after is None
    assert raised.value.previous is None


def test_chain_of_custody() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/chain-of-custody"
        return httpx2.Response(200, json=chain_of_custody_json("p", created_via="ui"))

    client = make_client(handler)
    body = client.projects.chain_of_custody("p")
    assert body.created_via == "ui"
    assert body.created_by_api_key_id is None
    assert body.source_files[0].id == "file-1"


def test_chain_of_custody_reads_naive_timestamps_as_utc() -> None:
    """Live CoC has omitted the offset on timestamp-without-time-zone columns.

    The caller still gets an aware value, so comparing it against an aware
    ``datetime`` cannot raise.
    """
    payload = chain_of_custody_json("p")
    payload["created_at"] = "2026-08-20T00:05:55.093379"
    payload["deliverables"][0]["created_at"] = "2026-08-20T00:06:53.096363"

    client = make_client(lambda _r: httpx2.Response(200, json=payload))
    body = client.projects.chain_of_custody("p")
    assert body.created_at == datetime(2026, 8, 20, 0, 5, 55, 93379, tzinfo=UTC)
    assert body.deliverables[0].created_at.tzinfo is UTC


def test_offset_timestamps_are_normalized_to_utc() -> None:
    payload = chain_of_custody_json("p")
    payload["created_at"] = "2026-08-20T12:05:55+12:00"

    client = make_client(lambda _r: httpx2.Response(200, json=payload))
    body = client.projects.chain_of_custody("p")
    assert body.created_at == datetime(2026, 8, 20, 0, 5, 55, tzinfo=UTC)
    assert body.created_at.tzinfo is UTC


def test_get_rejects_body_that_misses_required_fields() -> None:
    client = make_client(lambda r: httpx2.Response(200, json={"id": "p"}))
    with pytest.raises(ResponseParseError, match="getProject"):
        client.projects.get("p")


def test_malformed_2xx_json_is_a_typed_error() -> None:
    client = make_client(lambda _request: httpx2.Response(200, content=b"<html>nope</html>"))
    with pytest.raises(ResponseDecodeError, match="/v1/me") as raised:
        client.me()
    assert raised.value.operation == "/v1/me"
    assert isinstance(raised.value, ArbitrClientError)


def test_resume_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/review/resumptions"):
            return httpx2.Response(200, json=human_review_json())
        return httpx2.Response(200, json={"project_id": "p", "status": "completed"})

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


def test_path_ids_are_percent_encoded(tmp_path: Any) -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.raw_path)
        return httpx2.Response(
            404, json={"error": {"code": "not_found", "message": "nope", "request_id": "r"}}
        )

    client = make_client(handler)
    calls = [
        lambda: client.projects.get("../credits/balance"),
        lambda: client.projects.get(".."),
        lambda: client.projects.deliverables("a/b"),
        lambda: client.projects.deliverable("p", "d?x=1"),
        lambda: client.projects.download_deliverable("p", "../d", tmp_path / "out"),
        lambda: client.projects.resume("."),
        lambda: client.projects.quote("a/b"),
        lambda: client.projects.adjust_quote("../x", quote_version=1, remove=[]),
        lambda: client.projects.confirm(".."),
        lambda: client.webhooks.get(".."),
        lambda: client.webhooks.redeliver("../x", "a/b"),
    ]
    for call in calls:
        with pytest.raises(NotFoundError):
            call()
    assert seen == [
        b"/v1/projects/..%2Fcredits%2Fbalance",
        b"/v1/projects/%2E%2E",
        b"/v1/projects/a%2Fb/deliverables",
        b"/v1/projects/p/deliverables/d%3Fx%3D1",
        b"/v1/projects/p/deliverables/..%2Fd",
        b"/v1/projects/%2E/resumptions",
        b"/v1/projects/a%2Fb/quote",
        b"/v1/projects/..%2Fx/quote/adjustments",
        b"/v1/projects/%2E%2E/confirmations",
        b"/v1/webhooks/%2E%2E",
        b"/v1/webhooks/..%2Fx/deliveries/a%2Fb/redeliver",
    ]


def test_httpx_transport_is_a_client_input_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200))
    with pytest.raises(ClientInputError, match="httpx2"):
        ArbitrClient(api_key="k", transport=transport)  # ty: ignore[invalid-argument-type]


def test_insufficient_scope_carries_required_scope() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
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

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
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
    c = ArbitrClient(api_key="k", base_url="https://api-foo.example.com")
    assert c.ui_base_url == "https://foo.example.com"
    assert c.project_url("p1") == "https://foo.example.com/projects/p1"
    assert c.project_url("p1", view="agents") == "https://foo.example.com/projects/p1/agents"

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


def test_from_env_env_key_ignores_hosts_only_in_dotenv(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "ARBITR_API_KEY=fromfile\n"
        "ARBITR_BASE_URL=https://api.dotenv.example\n"
        "ARBITR_UI_URL=https://ui.dotenv.example\n"
    )
    monkeypatch.setenv("ARBITR_API_KEY", "fromenv")
    client = ArbitrClient.from_env(env)
    assert client.api_key == "fromenv"
    assert client.base_url == "https://api.arbitr.ai"
    assert client.ui_base_url == DEFAULT_UI_URL

    explicit = ArbitrClient.from_env(env, api_key="explicit")
    assert explicit.base_url == "https://api.arbitr.ai"

    monkeypatch.setenv("ARBITR_BASE_URL", "https://api.env.example")
    assert ArbitrClient.from_env(env).base_url == "https://api.env.example"
    assert ArbitrClient.from_env(env, base_url="https://api.arg").base_url == "https://api.arg"


def test_from_env_without_key_raises_precise_error(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ARBITR_API_KEY", raising=False)
    monkeypatch.delenv("arbitr_api_key", raising=False)
    with pytest.raises(MissingApiKeyError, match="ARBITR_API_KEY") as missing:
        ArbitrClient.from_env(tmp_path / "absent.env")
    assert f"{DEFAULT_UI_URL}/settings/api-keys" in str(missing.value)


def test_empty_key_raises_precise_error() -> None:
    with pytest.raises(MissingApiKeyError, match="api_key is required"):
        ArbitrClient(api_key="")


def test_default_hosts_are_the_production_pair() -> None:
    """The API host and the UI host it deep-links to must move together."""
    client = ArbitrClient(api_key="k")
    assert client.base_url == "https://api.arbitr.ai"
    assert client.ui_base_url == "https://app.arbitr.ai"


def test_client_input_errors_are_not_value_error() -> None:
    assert not issubclass(ClientInputError, ValueError)
    assert issubclass(ClientInputError, ArbitrClientError)
    assert issubclass(ActionRequiredError, ArbitrClientError)
    assert issubclass(ProjectWaitTimeoutError, TimeoutError)
    assert issubclass(ProjectWaitTimeoutError, ArbitrClientError)
    assert issubclass(ResponseParseError, ArbitrClientError)
    assert issubclass(ResponseDecodeError, ArbitrClientError)


def test_user_agent_suffix() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers["User-Agent"])
        return httpx2.Response(200, json=balance_json(1))

    client = ArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx2.MockTransport(handler),
        user_agent="slack-service",
    )
    client.credits.balance()
    assert seen == [f"arbitr-python/{arbitr.__version__} slack-service"]


REQUESTER = Requester(tenant_id="E1", external_id="U1", email="ann@example.com")
REQUESTER_JSON = {"tenant_id": "E1", "external_id": "U1", "email": "ann@example.com"}


def test_submit_sends_hold_fields_and_requester(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p", status="extracting"))

    make_client(handler).projects.submit(
        files=[doc],
        name="demo",
        target_language_codes=["fr-fr"],
        requester=REQUESTER,
        hold_for_quote=True,
        archive_on_completion=True,
        notes="rush",
        reference="JOB-42",
    )
    body = captured["body"]
    assert b'name="reference"\r\n\r\nJOB-42' in body
    assert b'name="hold_for_quote"\r\n\r\ntrue' in body
    assert b'name="archive_on_completion"\r\n\r\ntrue' in body
    assert b'name="notes"\r\n\r\nrush' in body
    assert b'name="requester"' in body
    assert json.dumps(REQUESTER_JSON).encode() in body


def test_submit_omits_hold_fields_by_default(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

    make_client(handler).projects.submit(files=[doc], name="d", target_language_codes=["fr-fr"])
    for field in ("hold_for_quote", "archive_on_completion", "notes", "requester", "reference"):
        assert f'name="{field}"'.encode() not in captured["body"]


def test_quote_parses_response() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, request.url.path))
        return httpx2.Response(200, json=quote_json("p", version=2))

    quote = make_client(handler).projects.quote("p")
    assert seen == [("GET", "/v1/projects/p/quote")]
    assert quote.version == 2
    assert quote.status == QuoteStatus.ready
    assert quote.lines[0].target_language_code == "fr-fr"
    assert quote.lines[0].stage == QuoteStage.AI_TRANSLATION
    assert quote.fees[0].kind == "pdf_conversion"


def test_adjust_quote_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        seen["idem"] = request.headers.get("Idempotency-Key")
        return httpx2.Response(201, json=quote_json("p", version=2))

    quote = make_client(handler).projects.adjust_quote(
        "p", quote_version=1, remove=[QuotePair(file_id="f-1", target_language_code="FR-fr")]
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/v1/projects/p/quote/adjustments"
    assert seen["body"] == {
        "quote_version": 1,
        "remove": [{"file_id": "f-1", "target_language_code": "FR-fr"}],
    }
    assert seen["idem"] is None
    assert quote.version == 2


def test_confirm_body_omits_none() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/confirmations"
        bodies.append(json.loads(request.content) if request.content else {})
        return httpx2.Response(201, json=quote_json("p", status="confirmed"))

    client = make_client(handler)
    client.projects.confirm("p")
    confirmed = client.projects.confirm("p", quote_version=3, requester=REQUESTER)
    assert bodies[0] == {}
    assert bodies[1] == {"quote_version": 3, "requester": REQUESTER_JSON}
    assert confirmed.status == QuoteStatus.confirmed


def test_wait_on_held_project_mentions_confirm() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="agent_selection"))

    with pytest.raises(ActionRequiredError, match=r"projects\.confirm"):
        make_client(handler).projects.wait("p", timeout=10, poll_interval=0.01)


@pytest.mark.parametrize(
    ("call", "method", "path", "body", "query", "status", "response", "parsed"),
    WEBHOOK_CALLS,
    ids=WEBHOOK_CALL_IDS,
)
def test_webhook_methods(
    call: Any,
    method: str,
    path: str,
    body: Any,
    query: dict[str, str],
    status: int,
    response: Any,
    parsed: type,
) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params)
        seen["body"] = json.loads(request.content) if request.content else None
        return httpx2.Response(status, json=response)

    result = call(make_client(handler))
    assert (seen["method"], seen["path"], seen["query"], seen["body"]) == (
        method,
        path,
        query,
        body,
    )
    assert isinstance(result, parsed)


def test_webhook_update_sends_only_what_was_given() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=webhook_json())

    client = make_client(handler)
    client.webhooks.update("w-1", event_types=["project.failed"])
    client.webhooks.update("w-1", description="")
    assert bodies == [{"event_types": ["project.failed"]}, {"description": ""}]
