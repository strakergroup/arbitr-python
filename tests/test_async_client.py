"""Async client tests — same MockTransport seam as the sync suite.

Mirrors `test_client.py` so a method added to one client but not the other,
or wired differently, fails here.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import httpx2
import pytest

import arbitr
from arbitr import (
    SUPPORTED_FORMATS,
    ActionRequiredError,
    AlreadyConfirmedError,
    AmbiguousLocaleCodesError,
    ApiMovedError,
    AsyncArbitrClient,
    ClientInputError,
    ConflictError,
    ConnectionStatus,
    DisallowedFileExtensionError,
    FindingSeverity,
    FindingsKeysetError,
    HoldExpiredError,
    MissingApiKeyError,
    NotFoundError,
    NotOnHoldError,
    ProjectWaitTimeoutError,
    QuoteChangedError,
    QuoteNotReadyError,
    QuotePair,
    QuoteStage,
    QuoteStatus,
    RateLimitError,
    Requester,
    ResponseDecodeError,
    ResponseParseError,
    TextToTranslate,
    TextTranslationStatus,
    UnknownLocaleCodesError,
    UsageUnit,
    ValidationError,
    new_idempotency_key,
)
from payloads import (
    agent_finding_json,
    balance_json,
    chain_of_custody_json,
    connection_json,
    finding_list_json,
    flag_finding_json,
    human_review_json,
    language_list_json,
    project_json,
    project_list_json,
    quote_json,
    text_translate_json,
    usage_list_json,
    webhook_json,
)
from webhook_cases import WEBHOOK_CALL_IDS, WEBHOOK_CALLS


def make_client(handler: Any) -> AsyncArbitrClient:
    return AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx2.MockTransport(handler),
    )


async def test_async_credits_and_headers() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["X-API-Key"] == "py_test_abc123"
        assert request.headers["X-API-Version"] == "1"
        assert request.headers["User-Agent"].startswith("arbitr-python/")
        return httpx2.Response(200, json=balance_json(7))

    async with make_client(handler) as client:
        assert (await client.credits.balance()).balance == 7


async def test_async_me_uses_v1_prefix() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/me"
        return httpx2.Response(200, json={"org_id": "o", "mode": "test", "scopes": ["verify:read"]})

    async with make_client(handler) as client:
        assert (await client.me()).scopes == ["verify:read"]


async def test_async_iterate_follows_page_numbers() -> None:
    pages = {
        "1": project_list_json([project_json("p1")], number=1, has_more=True, limit=1),
        "2": project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        page = request.url.params.get("page")
        assert request.url.params.get("limit") == "1"
        return httpx2.Response(200, json=pages[page])

    async with make_client(handler) as client:
        ids = [p.id async for p in client.projects.iterate(limit=1)]
    assert ids == ["p1", "p2"]


async def test_async_iterate_projects_resumes_from_page() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("page") == "2"
        return httpx2.Response(
            200,
            json=project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
        )

    async with make_client(handler) as client:
        ids = [p.id async for p in client.projects.iterate(limit=1, page=2)]
    assert ids == ["p2"]


async def test_async_list_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("modified_after") == "2026-07-26T00:00:00Z"
        assert request.url.params.get("status") == "completed"
        assert request.url.params.get("page") == "3"
        return httpx2.Response(200, json=project_list_json([], number=3, has_more=False, limit=50))

    async with make_client(handler) as client:
        await client.projects.list(
            page=3, modified_after="2026-07-26T00:00:00Z", status="completed"
        )


async def test_async_list_requester_and_search_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("requester_tenant_id") == "E0789"
        assert request.url.params.get("requester_external_id") == "U0123"
        assert request.url.params.get("q") == "contract"
        return httpx2.Response(200, json=project_list_json([project_json("p1")]))

    async with make_client(handler) as client:
        ids = [
            p.id
            async for p in client.projects.iterate(
                requester_tenant_id="E0789", requester_external_id="U0123", q="contract"
            )
        ]
    assert ids == ["p1"]


async def test_async_list_rejects_half_a_requester() -> None:
    async with make_client(lambda r: pytest.fail("no request expected")) as client:
        with pytest.raises(ClientInputError, match="together"):
            await client.projects.list(requester_tenant_id="E0789")


async def test_async_text_translate() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/text/translate"
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=text_translate_json("r1"))

    async with make_client(handler) as client:
        result = await client.text.translate(
            [TextToTranslate(ref="r1", text="Hello", target_language_codes=["fr-fr"])],
            format="html",
            requester=Requester(tenant_id="E0789", external_id="U0123"),
        )
    assert captured["body"] == {
        "texts": [{"ref": "r1", "text": "Hello", "target_language_codes": ["fr-fr"]}],
        "format": "html",
        "requester": {"tenant_id": "E0789", "external_id": "U0123"},
    }
    assert result.results[0].translations[0].status is TextTranslationStatus.translated


async def test_async_text_translate_sends_a_catalogue_tag_without_a_region() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = json.loads(request.content)
        return httpx2.Response(200, json=text_translate_json("r1"))

    async with make_client(handler) as client:
        await client.text.translate(
            [TextToTranslate(ref="r1", text="Hello", target_language_codes=["ar"])]
        )
    assert captured["body"]["texts"][0]["target_language_codes"] == ["ar"]


async def test_async_connection() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/connection"
        return httpx2.Response(200, json=connection_json())

    async with make_client(handler) as client:
        connection = await client.connection()
    assert connection.status is ConnectionStatus.active


async def test_async_usage_list_params() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/usage"
        assert request.url.params.get("from") == "2026-10-01T00:00:00Z"
        assert request.url.params.get("to") == "2026-11-01T00:00:00Z"
        return httpx2.Response(200, json=usage_list_json())

    async with make_client(handler) as client:
        usage = await client.usage.list(from_="2026-10-01T00:00:00Z", to="2026-11-01T00:00:00Z")
    assert usage.usage[0].unit is UsageUnit.character


async def test_async_submit_builds_multipart(tmp_path: Path) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello world")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects"
        captured["content_type"] = request.headers["content-type"]
        captured["idem"] = request.headers.get("Idempotency-Key")
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("proj-1", status="extracting"))

    async with make_client(handler) as client:
        project = await client.projects.submit(
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
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in body
    assert json.dumps(["AI_TRANSLATION"]).encode() in body
    assert b'filename="hello.txt"' in body
    assert b"hello world" in body


async def test_async_submit_workflow_and_due_date() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = request.content
        assert json.dumps(["AI_TRANSLATION", "TRANSLATION"]).encode() in body
        assert b'name="due_date"' in body and b"2026-08-01" in body
        return httpx2.Response(201, json=project_json("p-3"))

    async with make_client(handler) as client:
        await client.projects.submit(
            files=[("a.txt", b"hi")],
            name="wf",
            target_language_codes=["ja-jp"],
            workflow=["AI_TRANSLATION", "TRANSLATION"],
            due_date="2026-08-01",
        )


async def test_async_submit_lowercases_locale_codes() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

    async with make_client(handler) as client:
        await client.projects.submit(
            files=[("a.txt", b"hi")],
            name="x",
            target_language_codes=["KO-KR", "Fr-Fr"],
            source_language_code="EN-US",
        )
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in captured["body"]
    assert b"EN-US" not in captured["body"]


async def test_async_submit_sends_a_catalogue_tag_without_a_region() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

    async with make_client(handler) as client:
        await client.projects.submit(
            files=[("a.txt", b"hi")], name="x", target_language_codes=["AR"]
        )
    assert json.dumps(["ar"]).encode() in captured["body"]


async def test_async_submit_rejects_disallowed_extension(tmp_path: Path) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    async with make_client(lambda r: httpx2.Response(500)) as client:
        with pytest.raises(DisallowedFileExtensionError) as raised:
            await client.projects.submit(files=[exe], name="x", target_language_codes=["ko-kr"])
    assert raised.value.extension == ".exe"
    assert raised.value.supported_formats == SUPPORTED_FORMATS


async def test_async_submit_rejects_empty_file_list() -> None:
    async with make_client(lambda r: httpx2.Response(500)) as client:
        with pytest.raises(ClientInputError, match="at least one file"):
            await client.projects.submit(files=[], name="x", target_language_codes=["ko-kr"])


async def test_async_submit_rejects_over_total_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arbitr._constants.MAX_UPLOAD_TOTAL_BYTES", 4)
    async with make_client(lambda r: httpx2.Response(500)) as client:
        with pytest.raises(ClientInputError, match="upload too large"):
            await client.projects.submit(
                files=[("a.txt", b"hello")], name="x", target_language_codes=["ko-kr"]
            )


async def test_async_submit_extension_check_off(tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    async with make_client(lambda r: httpx2.Response(201, json=project_json("p"))) as client:
        project = await client.projects.submit(
            files=[exe], name="x", target_language_codes=["ko-kr"], extension_check="off"
        )
    assert project.id == "p"


async def test_async_wait_polls_until_terminal() -> None:
    statuses = iter(["extracting", "translating", "completed"])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


async def test_async_wait_raises_on_parked_gate() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="agent_selection"))

    async with make_client(handler) as client:
        with pytest.raises(ActionRequiredError) as raised:
            await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert raised.value.status == "agent_selection"
    assert raised.value.ui_url == "https://test/projects/p/agents"


async def test_async_wait_ignores_transient_agent_selection() -> None:
    statuses = iter(["agent_selection", "translating", "completed"])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


async def test_async_wait_through_gate_keeps_polling() -> None:
    statuses = iter(["agent_selection", "agent_selection", "translating", "completed"])

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait(
            "p", timeout=10, poll_interval=0.01, on_action_required="wait"
        )
    assert final.status == "completed"


async def test_async_wait_times_out() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="translating"))

    async with make_client(handler) as client:
        with pytest.raises(ProjectWaitTimeoutError) as raised:
            await client.projects.wait("p", timeout=0.05, poll_interval=0.01)
    assert raised.value.status == "translating"


async def test_async_wait_rejects_bad_mode() -> None:
    bogus: Any = "bogus"
    async with make_client(lambda r: httpx2.Response(200, json={})) as client:
        with pytest.raises(ClientInputError, match="on_action_required"):
            await client.projects.wait("p", on_action_required=bogus)


async def test_async_wait_treats_cancelled_as_terminal() -> None:
    calls = {"n": 0}

    def handler(request: httpx2.Request) -> httpx2.Response:
        calls["n"] += 1
        return httpx2.Response(200, json=project_json("p", status="cancelled"))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "cancelled"
    assert calls["n"] == 1


async def test_async_deliverables_and_one_deliverable() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/deliverables"):
            return httpx2.Response(
                200,
                json={
                    "deliverables": [
                        {"id": "d-1", "file_id": "f-1", "file_type": "xliff", "name": "ko.xliff"}
                    ],
                    "page": {"number": 1, "has_more": False, "limit": 50},
                },
            )
        return httpx2.Response(
            200,
            json={"id": "d-1", "file_id": "f-1", "file_type": "xliff", "locale_code": "ko-kr"},
        )

    async with make_client(handler) as client:
        listed = await client.projects.deliverables("p")
        one = await client.projects.deliverable("p", "d-1")

    assert [d.id for d in listed.deliverables] == ["d-1"]
    assert one.locale_code == "ko-kr"
    assert seen == ["/v1/projects/p/deliverables", "/v1/projects/p/deliverables/d-1"]


async def test_async_findings_page_and_filters() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/findings"
        assert request.url.params.get("limit") == "10"
        assert request.url.params.get("severity") == "critical"
        assert "page" not in request.url.params
        return httpx2.Response(
            200,
            json=finding_list_json([flag_finding_json()], has_more=False, limit=10),
        )

    async with make_client(handler) as client:
        body = await client.projects.findings("p", limit=10, severity=FindingSeverity.critical)
    assert [item.kind for item in body.findings] == ["flag"]
    assert body.page.number == 1


async def test_async_iterate_findings_walks_after() -> None:
    pages = {
        None: finding_list_json(
            [flag_finding_json("flag-1")], has_more=True, limit=1, after="0:0:flag-1"
        ),
        "0:0:flag-1": finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        token = request.url.params.get("after")
        assert token in pages
        return httpx2.Response(200, json=pages[token])

    async with make_client(handler) as client:
        kinds = [item.kind async for item in client.projects.iterate_findings("p", limit=1)]
    assert kinds == ["flag", "agent_finding"]


async def test_async_iterate_findings_continues_on_empty_page() -> None:
    pages = {
        None: finding_list_json([], has_more=True, limit=1, after="skip-1"),
        "skip-1": finding_list_json([flag_finding_json("flag-1")], has_more=False, limit=1),
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        token = request.url.params.get("after")
        assert token in pages
        return httpx2.Response(200, json=pages[token])

    async with make_client(handler) as client:
        ids = [item.id async for item in client.projects.iterate_findings("p", limit=1)]
    assert ids == ["flag-1"]


async def test_async_iterate_findings_resumes_from_after() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.params.get("after") == "0:0:flag-1"
        return httpx2.Response(
            200,
            json=finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
        )

    async with make_client(handler) as client:
        kinds = [
            item.kind
            async for item in client.projects.iterate_findings("p", limit=1, after="0:0:flag-1")
        ]
    assert kinds == ["agent_finding"]


async def test_async_iterate_findings_raises_when_after_does_not_advance() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json=finding_list_json(
                [flag_finding_json("flag-1")], has_more=True, limit=1, after="same"
            ),
        )

    async with make_client(handler) as client:
        got: list[str] = []
        with pytest.raises(FindingsKeysetError, match="did not advance"):
            async for item in client.projects.iterate_findings("p", limit=1):
                got.append(item.id)
    assert got == ["flag-1", "flag-1"]


async def test_async_iterate_findings_raises_when_has_more_without_after() -> None:
    async with make_client(
        lambda _r: httpx2.Response(
            200,
            json=finding_list_json([flag_finding_json("flag-1")], has_more=True, limit=1),
        )
    ) as client:
        got: list[str] = []
        with pytest.raises(FindingsKeysetError, match="did not advance") as raised:
            async for item in client.projects.iterate_findings("p"):
                got.append(item.id)
    assert got == ["flag-1"]
    assert raised.value.after is None


async def test_async_chain_of_custody() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/chain-of-custody"
        return httpx2.Response(200, json=chain_of_custody_json("p"))

    async with make_client(handler) as client:
        body = await client.projects.chain_of_custody("p")
    assert body.created_via == "api"
    assert body.deliverables[0].id == "deliv-1"


async def test_async_chain_of_custody_reads_naive_timestamps_as_utc() -> None:
    payload = chain_of_custody_json("p")
    payload["created_at"] = "2026-08-20T00:05:55.093379"
    payload["deliverables"][0]["created_at"] = "2026-08-20T00:06:53.096363"

    async with make_client(lambda _r: httpx2.Response(200, json=payload)) as client:
        body = await client.projects.chain_of_custody("p")
    assert body.created_at == datetime(2026, 8, 20, 0, 5, 55, 93379, tzinfo=UTC)
    assert body.deliverables[0].created_at.tzinfo is UTC


async def test_async_download_zip(tmp_path: Path) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("out_ko.xliff", "<xliff/>")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/deliverables"
        assert request.url.params.get("format") == "zip"
        return httpx2.Response(
            200, content=buf.getvalue(), headers={"content-type": "application/zip"}
        )

    async with make_client(handler) as client:
        dest = tmp_path / "deliv.zip"
        assert await client.projects.download_zip("p", dest) == dest
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["out_ko.xliff"]


async def test_async_download_single_deliverable(tmp_path: Path) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/deliverables/d-1"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx2.Response(200, content=b"<xliff/>")

    async with make_client(handler) as client:
        dest = tmp_path / "one.xliff"
        assert await client.projects.download_deliverable("p", "d-1", dest) == dest
    assert dest.read_bytes() == b"<xliff/>"


async def test_async_failed_download_leaves_existing_dest(tmp_path: Path) -> None:
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"keep-me")

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(404, json={"error": {"code": "not_found", "message": "nope"}})

    async with make_client(handler) as client:
        with pytest.raises(NotFoundError):
            await client.projects.download_deliverable("p", "d-1", dest)
    assert dest.read_bytes() == b"keep-me"


async def test_async_download_writes_many_chunks(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 400

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, content=payload)

    async with make_client(handler) as client:
        dest = tmp_path / "big.bin"
        await client.projects.download_zip("p", dest)
    assert dest.read_bytes() == payload


async def test_async_resume_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/review/resumptions"):
            return httpx2.Response(200, json=human_review_json())
        return httpx2.Response(200, json={"project_id": "p", "status": "completed"})

    async with make_client(handler) as client:
        resumed = await client.projects.resume("p")
        review = await client.projects.resume_human_review("p")

    assert seen == ["/v1/projects/p/resumptions", "/v1/projects/p/review/resumptions"]
    assert resumed.project_id == "p"
    assert review.status == "queued"


async def test_async_languages_list_and_filter() -> None:
    async with make_client(lambda r: httpx2.Response(200, json=language_list_json())) as client:
        every = await client.languages.list()
        filtered = await client.languages.list(search="french")
    assert len(every.languages) == 4
    assert {lang.bcp47 for lang in filtered.languages} == {"fr-fr", "fr-ca"}
    assert filtered.page.limit == 2


async def test_async_languages_resolve_normalizes_and_rejects() -> None:
    async with make_client(lambda r: httpx2.Response(200, json=language_list_json())) as client:
        assert await client.languages.resolve(["JA-JP", "Fr-Fr"]) == ["ja-jp", "fr-fr"]
        assert await client.languages.resolve(["ja"]) == ["ja-jp"]
        with pytest.raises(AmbiguousLocaleCodesError) as amb:
            await client.languages.resolve(["fr"])
        with pytest.raises(UnknownLocaleCodesError) as unknown:
            await client.languages.resolve(["xx-garbage"])
    assert amb.value.matches == ["fr-ca", "fr-fr"]
    assert unknown.value.codes == ["xx-garbage"]


async def test_async_error_envelope_maps_to_typed_errors() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/v1/projects/missing":
            return httpx2.Response(
                404, json={"error": {"code": "not_found", "message": "n", "request_id": "r-1"}}
            )
        return httpx2.Response(
            429,
            json={"error": {"code": "rate_limited", "message": "slow", "request_id": "r-3"}},
            headers={"Retry-After": "7"},
        )

    async with make_client(handler) as client:
        with pytest.raises(NotFoundError) as nf:
            await client.projects.get("missing")
        with pytest.raises(RateLimitError) as rl:
            await client.projects.get("limited")
    assert nf.value.request_id == "r-1"
    assert rl.value.retry_after == 7.0


async def test_async_unsupported_upload_422_carries_supported_formats() -> None:
    formats = [".csv", ".docx", ".txt"]

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            422,
            json={
                "error": {
                    "code": "validation_failed",
                    "message": "Unsupported file type",
                    "request_id": "r",
                    "supported_formats": formats,
                }
            },
        )

    async with make_client(handler) as client:
        with pytest.raises(ValidationError) as raised:
            await client.projects.submit(
                files=[("evil.exe", b"MZ")],
                name="x",
                target_language_codes=["ja-jp"],
                extension_check="off",
            )
    assert raised.value.supported_formats == formats


async def test_async_rejects_body_that_misses_required_fields() -> None:
    async with make_client(lambda r: httpx2.Response(200, json={"id": "p"})) as client:
        with pytest.raises(ResponseParseError, match="getProject"):
            await client.projects.get("p")


async def test_async_malformed_2xx_json_is_a_typed_error() -> None:
    async with make_client(
        lambda _request: httpx2.Response(200, content=b"<html>nope</html>")
    ) as client:
        with pytest.raises(ResponseDecodeError, match="/v1/me"):
            await client.me()


async def test_async_redirect_is_not_success() -> None:
    async with make_client(lambda r: httpx2.Response(302, headers={"location": "/x"})) as client:
        with pytest.raises(Exception) as raised:
            await client.get_json("/v1/me")
    assert getattr(raised.value, "status_code", None) == 302


async def test_async_redirects_are_never_followed() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(301, headers={"location": "https://evil.example/v1/me"})

    async with make_client(handler) as client:
        with pytest.raises(ApiMovedError) as raised:
            await client.get_json("/v1/me")
    assert raised.value.moved_to == "https://evil.example"
    assert seen == ["https://api.test/v1/me"]


async def test_async_streamed_download_from_a_moved_host_names_the_new_one(
    tmp_path: Path,
) -> None:
    dest = tmp_path / "out.zip"

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            301,
            headers={"location": "https://api.arbitr.ai/v1/projects/p/deliverables/d-1"},
            stream=httpx2.ByteStream(b"<html>moved</html>"),
        )

    async with make_client(handler) as client:
        with pytest.raises(ApiMovedError) as raised:
            await client.projects.download_deliverable("p", "d-1", dest)
    assert raised.value.moved_to == "https://api.arbitr.ai"
    assert not dest.exists()


async def test_async_path_ids_are_percent_encoded(tmp_path: Path) -> None:
    seen: list[bytes] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.raw_path)
        return httpx2.Response(
            404, json={"error": {"code": "not_found", "message": "nope", "request_id": "r"}}
        )

    async with make_client(handler) as client:
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
                await call()
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


async def test_async_httpx_transport_is_a_client_input_error() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200))
    with pytest.raises(ClientInputError, match="httpx2"):
        AsyncArbitrClient(api_key="k", transport=transport)  # ty: ignore[invalid-argument-type]


async def test_async_from_env_reads_dotenv(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("arbitr_api_key=py_test_async\narbitr_api_domain=https://api.example\n")
    async with AsyncArbitrClient.from_env(env) as client:
        assert client.api_key == "py_test_async"
        assert client.base_url == "https://api.example"


async def test_async_from_env_without_key_raises() -> None:
    with pytest.raises(MissingApiKeyError, match="ARBITR_API_KEY"):
        AsyncArbitrClient.from_env("absent.env")


async def test_async_empty_key_raises() -> None:
    with pytest.raises(MissingApiKeyError, match="api_key is required"):
        AsyncArbitrClient(api_key="")


async def test_async_key_mode_and_repr_hide_the_key() -> None:
    async with AsyncArbitrClient(api_key="abr_live_secretvalue") as client:
        assert client.key_mode == "live"
        assert "secretvalue" not in repr(client)


async def test_async_ui_url_derivation() -> None:
    async with AsyncArbitrClient(api_key="k", base_url="https://api-foo.example.com") as client:
        assert client.ui_base_url == "https://foo.example.com"
        assert client.project_url("p1") == "https://foo.example.com/projects/p1"
        assert (
            client.project_url("p1", view="agents") == "https://foo.example.com/projects/p1/agents"
        )


async def test_async_default_hosts_are_the_production_pair() -> None:
    """The API host and the UI host it deep-links to must move together."""
    async with AsyncArbitrClient(api_key="k") as client:
        assert client.base_url == "https://api.arbitr.ai"
        assert client.ui_base_url == "https://app.arbitr.ai"


async def test_async_context_manager_closes_the_transport() -> None:
    client = make_client(lambda r: httpx2.Response(200, json=balance_json(1)))
    async with client:
        await client.credits.balance()
    assert client.is_closed


async def test_async_shares_the_idempotency_key_helper() -> None:
    assert new_idempotency_key() != new_idempotency_key()
    assert len(new_idempotency_key()) == 36


async def test_async_user_agent_suffix() -> None:
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.headers["User-Agent"])
        return httpx2.Response(200, json=balance_json(1))

    client = AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx2.MockTransport(handler),
        user_agent="slack-service",
    )
    async with client:
        await client.credits.balance()
    assert seen == [f"arbitr-python/{arbitr.__version__} slack-service"]


REQUESTER = Requester(tenant_id="E1", external_id="U1", email="ann@example.com")
REQUESTER_JSON = {"tenant_id": "E1", "external_id": "U1", "email": "ann@example.com"}


async def test_async_submit_sends_hold_fields_and_requester(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p", status="extracting"))

    async with make_client(handler) as client:
        await client.projects.submit(
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


async def test_async_submit_omits_hold_fields_by_default(tmp_path: Any) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello")
    captured: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        captured["body"] = request.content
        return httpx2.Response(201, json=project_json("p"))

    async with make_client(handler) as client:
        await client.projects.submit(files=[doc], name="d", target_language_codes=["fr-fr"])
    for field in ("hold_for_quote", "archive_on_completion", "notes", "requester", "reference"):
        assert f'name="{field}"'.encode() not in captured["body"]


async def test_async_quote_parses_response() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append((request.method, request.url.path))
        return httpx2.Response(200, json=quote_json("p", version=2))

    async with make_client(handler) as client:
        quote = await client.projects.quote("p")
    assert seen == [("GET", "/v1/projects/p/quote")]
    assert quote.version == 2
    assert quote.status == QuoteStatus.ready
    assert quote.lines[0].target_language_code == "fr-fr"
    assert quote.lines[0].stage == QuoteStage.AI_TRANSLATION
    assert quote.fees[0].kind == "pdf_conversion"


async def test_async_adjust_quote_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        seen["idem"] = request.headers.get("Idempotency-Key")
        return httpx2.Response(201, json=quote_json("p", version=2))

    async with make_client(handler) as client:
        quote = await client.projects.adjust_quote(
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


async def test_async_confirm_body_omits_none() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/projects/p/confirmations"
        bodies.append(json.loads(request.content) if request.content else {})
        return httpx2.Response(201, json=quote_json("p", status="confirmed"))

    async with make_client(handler) as client:
        await client.projects.confirm("p")
        confirmed = await client.projects.confirm("p", quote_version=3, requester=REQUESTER)
    assert bodies[0] == {}
    assert bodies[1] == {"quote_version": 3, "requester": REQUESTER_JSON}
    assert confirmed.status == QuoteStatus.confirmed


async def test_async_confirm_requester_only_sends_requester() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(201, json=quote_json("p", status="confirmed"))

    async with make_client(handler) as client:
        await client.projects.confirm("p", requester=REQUESTER)
    assert bodies == [{"requester": REQUESTER_JSON}]


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("not_on_hold", NotOnHoldError),
        ("quote_not_ready", QuoteNotReadyError),
        ("quote_changed", QuoteChangedError),
        ("hold_expired", HoldExpiredError),
        ("already_confirmed", AlreadyConfirmedError),
    ],
)
async def test_async_conflict_codes_map_to_typed_errors(
    code: str, expected: type[ConflictError]
) -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        body = {"error": {"code": code, "message": "boom", "request_id": "r-1"}}
        return httpx2.Response(409, json=body)

    async with make_client(handler) as client:
        with pytest.raises(expected) as raised:
            await client.me()
    assert isinstance(raised.value, ConflictError)
    assert raised.value.code == code
    assert raised.value.status_code == 409


async def test_async_wait_on_held_project_mentions_confirm() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=project_json("p", status="agent_selection"))

    async with make_client(handler) as client:
        with pytest.raises(ActionRequiredError, match=r"projects\.confirm"):
            await client.projects.wait("p", timeout=10, poll_interval=0.01)


@pytest.mark.parametrize(
    ("call", "method", "path", "body", "query", "status", "response", "parsed"),
    WEBHOOK_CALLS,
    ids=WEBHOOK_CALL_IDS,
)
async def test_async_webhook_methods(
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

    async with make_client(handler) as client:
        result = await call(client)
    assert (seen["method"], seen["path"], seen["query"], seen["body"]) == (
        method,
        path,
        query,
        body,
    )
    assert isinstance(result, parsed)


async def test_async_webhook_update_sends_only_what_was_given() -> None:
    bodies: list[Any] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=webhook_json())

    async with make_client(handler) as client:
        await client.webhooks.update("w-1", event_types=["project.failed"])
        await client.webhooks.update("w-1", description="")
    assert bodies == [{"event_types": ["project.failed"]}, {"description": ""}]
