"""Async client tests — same MockTransport seam as the sync suite.

Mirrors `test_client.py` so a method added to one client but not the other,
or wired differently, fails here.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest

from arbitr import (
    SUPPORTED_FORMATS,
    ActionRequiredError,
    AmbiguousLocaleCodesError,
    AsyncArbitrClient,
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
    new_idempotency_key,
)
from payloads import human_review_json, language_list_json, project_json, project_list_json


def make_client(handler: Any) -> AsyncArbitrClient:
    return AsyncArbitrClient(
        api_key="py_test_abc123",
        base_url="https://api.test",
        transport=httpx.MockTransport(handler),
    )


async def test_async_credits_and_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-API-Key"] == "py_test_abc123"
        assert request.headers["X-API-Version"] == "1"
        assert request.headers["User-Agent"].startswith("arbitr-python/")
        return httpx.Response(200, json={"balance": 7})

    async with make_client(handler) as client:
        assert (await client.credits.balance()).balance == 7


async def test_async_me_uses_v1_prefix() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/me"
        return httpx.Response(200, json={"org_id": "o", "mode": "test", "scopes": ["verify:read"]})

    async with make_client(handler) as client:
        assert (await client.me()).scopes == ["verify:read"]


async def test_async_iterate_follows_page_numbers() -> None:
    pages = {
        "1": project_list_json([project_json("p1")], number=1, has_more=True, limit=1),
        "2": project_list_json([project_json("p2")], number=2, has_more=False, limit=1),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        assert request.url.params.get("limit") == "1"
        return httpx.Response(200, json=pages[page])

    async with make_client(handler) as client:
        ids = [p.id async for p in client.projects.iterate(limit=1)]
    assert ids == ["p1", "p2"]


async def test_async_list_params() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("modified_after") == "2026-07-26T00:00:00Z"
        assert request.url.params.get("status") == "completed"
        assert request.url.params.get("page") == "3"
        return httpx.Response(200, json=project_list_json([], number=3, has_more=False, limit=50))

    async with make_client(handler) as client:
        await client.projects.list(
            page=3, modified_after="2026-07-26T00:00:00Z", status="completed"
        )


async def test_async_submit_builds_multipart(tmp_path: Path) -> None:
    doc = tmp_path / "hello.txt"
    doc.write_text("hello world")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects"
        captured["content_type"] = request.headers["content-type"]
        captured["idem"] = request.headers.get("Idempotency-Key")
        captured["body"] = request.content
        return httpx.Response(201, json=project_json("proj-1", status="extracting"))

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
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content
        assert json.dumps(["AI_TRANSLATION", "TRANSLATION"]).encode() in body
        assert b'name="due_date"' in body and b"2026-08-01" in body
        return httpx.Response(201, json=project_json("p-3"))

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

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(201, json=project_json("p"))

    async with make_client(handler) as client:
        await client.projects.submit(
            files=[("a.txt", b"hi")],
            name="x",
            target_language_codes=["KO-KR", "Fr-Fr"],
            source_language_code="EN-US",
        )
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in captured["body"]
    assert b"EN-US" not in captured["body"]


async def test_async_submit_rejects_bare_locale_codes() -> None:
    async with make_client(lambda _request: httpx.Response(500)) as client:
        with pytest.raises(BareLocaleCodeError) as raised:
            await client.projects.submit(
                files=[("a.txt", b"hi")],
                name="x",
                target_language_codes=["ko"],
            )
    assert raised.value.code == "ko"


async def test_async_submit_rejects_disallowed_extension(tmp_path: Path) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    async with make_client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(DisallowedFileExtensionError) as raised:
            await client.projects.submit(files=[exe], name="x", target_language_codes=["ko-kr"])
    assert raised.value.extension == ".exe"
    assert raised.value.supported_formats == SUPPORTED_FORMATS


async def test_async_submit_rejects_empty_file_list() -> None:
    async with make_client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(ClientInputError, match="at least one file"):
            await client.projects.submit(files=[], name="x", target_language_codes=["ko-kr"])


async def test_async_submit_rejects_over_total_byte_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("arbitr._constants.MAX_UPLOAD_TOTAL_BYTES", 4)
    async with make_client(lambda r: httpx.Response(500)) as client:
        with pytest.raises(ClientInputError, match="upload too large"):
            await client.projects.submit(
                files=[("a.txt", b"hello")], name="x", target_language_codes=["ko-kr"]
            )


async def test_async_submit_extension_check_off(tmp_path: Path) -> None:
    exe = tmp_path / "tool.exe"
    exe.write_bytes(b"MZ")
    async with make_client(lambda r: httpx.Response(201, json=project_json("p"))) as client:
        project = await client.projects.submit(
            files=[exe], name="x", target_language_codes=["ko-kr"], extension_check="off"
        )
    assert project.id == "p"


async def test_async_wait_polls_until_terminal() -> None:
    statuses = iter(["extracting", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


async def test_async_wait_raises_on_parked_gate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status="agent_selection"))

    async with make_client(handler) as client:
        with pytest.raises(ActionRequiredError) as raised:
            await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert raised.value.status == "agent_selection"
    assert raised.value.ui_url == "https://test/projects/p/agents"


async def test_async_wait_ignores_transient_agent_selection() -> None:
    statuses = iter(["agent_selection", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "completed"


async def test_async_wait_through_gate_keeps_polling() -> None:
    statuses = iter(["agent_selection", "agent_selection", "translating", "completed"])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status=next(statuses)))

    async with make_client(handler) as client:
        final = await client.projects.wait(
            "p", timeout=10, poll_interval=0.01, on_action_required="wait"
        )
    assert final.status == "completed"


async def test_async_wait_times_out() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=project_json("p", status="translating"))

    async with make_client(handler) as client:
        with pytest.raises(ProjectWaitTimeoutError) as raised:
            await client.projects.wait("p", timeout=0.05, poll_interval=0.01)
    assert raised.value.status == "translating"


async def test_async_wait_rejects_bad_mode() -> None:
    bogus: Any = "bogus"
    async with make_client(lambda r: httpx.Response(200, json={})) as client:
        with pytest.raises(ClientInputError, match="on_action_required"):
            await client.projects.wait("p", on_action_required=bogus)


async def test_async_wait_treats_cancelled_as_terminal() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=project_json("p", status="cancelled"))

    async with make_client(handler) as client:
        final = await client.projects.wait("p", timeout=10, poll_interval=0.01)
    assert final.status == "cancelled"
    assert calls["n"] == 1


async def test_async_deliverables_and_one_deliverable() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/deliverables"):
            return httpx.Response(
                200,
                json={
                    "deliverables": [
                        {"id": "d-1", "file_id": "f-1", "file_type": "xliff", "name": "ko.xliff"}
                    ],
                    "page": {"number": 1, "has_more": False, "limit": 50},
                },
            )
        return httpx.Response(
            200,
            json={"id": "d-1", "file_id": "f-1", "file_type": "xliff", "locale_code": "ko-kr"},
        )

    async with make_client(handler) as client:
        listed = await client.projects.deliverables("p")
        one = await client.projects.deliverable("p", "d-1")

    assert [d.id for d in listed.deliverables] == ["d-1"]
    assert one.locale_code == "ko-kr"
    assert seen == ["/v1/projects/p/deliverables", "/v1/projects/p/deliverables/d-1"]


async def test_async_download_zip(tmp_path: Path) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("out_ko.xliff", "<xliff/>")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects/p/deliverables"
        assert request.url.params.get("format") == "zip"
        return httpx.Response(
            200, content=buf.getvalue(), headers={"content-type": "application/zip"}
        )

    async with make_client(handler) as client:
        dest = tmp_path / "deliv.zip"
        assert await client.projects.download_zip("p", dest) == dest
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist() == ["out_ko.xliff"]


async def test_async_download_single_deliverable(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/projects/p/deliverables/d-1"
        assert request.headers["accept"] == "application/octet-stream"
        return httpx.Response(200, content=b"<xliff/>")

    async with make_client(handler) as client:
        dest = tmp_path / "one.xliff"
        assert await client.projects.download_deliverable("p", "d-1", dest) == dest
    assert dest.read_bytes() == b"<xliff/>"


async def test_async_failed_download_leaves_existing_dest(tmp_path: Path) -> None:
    dest = tmp_path / "out.bin"
    dest.write_bytes(b"keep-me")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"code": "not_found", "message": "nope"}})

    async with make_client(handler) as client:
        with pytest.raises(NotFoundError):
            await client.projects.download_deliverable("p", "d-1", dest)
    assert dest.read_bytes() == b"keep-me"


async def test_async_download_writes_many_chunks(tmp_path: Path) -> None:
    payload = bytes(range(256)) * 400

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=payload)

    async with make_client(handler) as client:
        dest = tmp_path / "big.bin"
        await client.projects.download_zip("p", dest)
    assert dest.read_bytes() == payload


async def test_async_resume_paths() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/review/resumptions"):
            return httpx.Response(200, json=human_review_json())
        return httpx.Response(200, json={"project_id": "p", "status": "completed"})

    async with make_client(handler) as client:
        resumed = await client.projects.resume("p")
        review = await client.projects.resume_human_review("p")

    assert seen == ["/v1/projects/p/resumptions", "/v1/projects/p/review/resumptions"]
    assert resumed.project_id == "p"
    assert review.status == "queued"


async def test_async_languages_list_and_filter() -> None:
    async with make_client(lambda r: httpx.Response(200, json=language_list_json())) as client:
        every = await client.languages.list()
        filtered = await client.languages.list(search="french")
    assert len(every.languages) == 4
    assert {lang.bcp47 for lang in filtered.languages} == {"fr-fr", "fr-ca"}
    assert filtered.page.limit == 2


async def test_async_languages_resolve_normalizes_and_rejects() -> None:
    async with make_client(lambda r: httpx.Response(200, json=language_list_json())) as client:
        assert await client.languages.resolve(["JA-JP", "Fr-Fr"]) == ["ja-jp", "fr-fr"]
        assert await client.languages.resolve(["ja"]) == ["ja-jp"]
        with pytest.raises(AmbiguousLocaleCodesError) as amb:
            await client.languages.resolve(["fr"])
        with pytest.raises(UnknownLocaleCodesError) as unknown:
            await client.languages.resolve(["xx-garbage"])
    assert amb.value.matches == ["fr-ca", "fr-fr"]
    assert unknown.value.codes == ["xx-garbage"]


async def test_async_error_envelope_maps_to_typed_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/projects/missing":
            return httpx.Response(
                404, json={"error": {"code": "not_found", "message": "n", "request_id": "r-1"}}
            )
        return httpx.Response(
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

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
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
    async with make_client(lambda r: httpx.Response(200, json={"id": "p"})) as client:
        with pytest.raises(ResponseParseError, match="getProject"):
            await client.projects.get("p")


async def test_async_malformed_2xx_json_is_a_typed_error() -> None:
    async with make_client(
        lambda _request: httpx.Response(200, content=b"<html>nope</html>")
    ) as client:
        with pytest.raises(ResponseDecodeError, match="/v1/me"):
            await client.me()


async def test_async_redirect_is_not_success() -> None:
    async with make_client(lambda r: httpx.Response(302, headers={"location": "/x"})) as client:
        with pytest.raises(Exception) as raised:
            await client.get_json("/v1/me")
    assert getattr(raised.value, "status_code", None) == 302


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
    async with AsyncArbitrClient(api_key="k", base_url="https://api-arbitr.straker.ai") as client:
        assert client.ui_base_url == "https://arbitr.straker.ai"
        assert client.project_url("p1") == "https://arbitr.straker.ai/projects/p1"
        assert (
            client.project_url("p1", view="agents")
            == "https://arbitr.straker.ai/projects/p1/agents"
        )


async def test_async_default_base_url_is_prod() -> None:
    async with AsyncArbitrClient(api_key="k") as client:
        assert client.base_url == "https://api-arbitr.straker.ai"


async def test_async_context_manager_closes_the_transport() -> None:
    client = make_client(lambda r: httpx.Response(200, json={"balance": 1}))
    async with client:
        await client.credits.balance()
    assert client.is_closed


async def test_async_shares_the_idempotency_key_helper() -> None:
    assert new_idempotency_key() != new_idempotency_key()
    assert len(new_idempotency_key()) == 36
