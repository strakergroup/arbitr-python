"""Per-call ``timeout=`` on the typed methods, mirrored across both clients.

A caller with a deadline (a chat message waiting on a balance) passes a short
timeout for that one call; every other call keeps the client's timeout.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest

from arbitr import ArbitrClient, AsyncArbitrClient
from payloads import (
    chain_of_custody_json,
    finding_list_json,
    human_review_json,
    language_list_json,
    project_json,
    project_list_json,
)

CLIENT_TIMEOUT = 60.0
CALL_TIMEOUT = 7.0

DELIVERABLE = {"id": "d-1", "file_id": "f-1", "file_type": "verified_doc"}
RESUMPTION = {"project_id": "p", "status": "processing"}


def _respond(request: httpx2.Request) -> httpx2.Response:
    path = request.url.path
    if path == "/v1/me":
        return httpx2.Response(200, json={"org_id": "o", "mode": "test", "scopes": []})
    if path == "/v1/credits/balance":
        return httpx2.Response(200, json={"balance": 1})
    if path == "/v1/languages":
        return httpx2.Response(200, json=language_list_json())
    if path == "/v1/projects" and request.method == "GET":
        return httpx2.Response(200, json=project_list_json([project_json()]))
    if path.endswith("/findings"):
        return httpx2.Response(200, json=finding_list_json([]))
    if path.endswith("/chain-of-custody"):
        return httpx2.Response(200, json=chain_of_custody_json())
    if path.endswith("/review/resumptions"):
        return httpx2.Response(200, json=human_review_json())
    if path.endswith("/resumptions"):
        return httpx2.Response(200, json=RESUMPTION)
    if path.endswith("/deliverables") and "format" in request.url.params:
        return httpx2.Response(200, content=b"zip")
    if path.endswith("/deliverables"):
        return httpx2.Response(
            200,
            json={
                "deliverables": [DELIVERABLE],
                "page": {"number": 1, "has_more": False, "limit": 50},
            },
        )
    if "/deliverables/" in path and request.headers.get("accept") == "application/octet-stream":
        return httpx2.Response(200, content=b"file")
    if "/deliverables/" in path:
        return httpx2.Response(200, json=DELIVERABLE)
    return httpx2.Response(200, json=project_json())


Call = Callable[[Any, Path, dict[str, float]], Any]

# Each typed method that sends exactly one request, called with the kwargs under test.
CALLS: dict[str, Call] = {
    "me": lambda c, _, kw: c.me(**kw),
    "credits.balance": lambda c, _, kw: c.credits.balance(**kw),
    "languages.list": lambda c, _, kw: c.languages.list(**kw),
    "projects.submit": lambda c, d, kw: c.projects.submit(
        files=[d / "a.txt"], name="n", target_language_codes=["ja-jp"], **kw
    ),
    "projects.list": lambda c, _, kw: c.projects.list(**kw),
    "projects.get": lambda c, _, kw: c.projects.get("p", **kw),
    "projects.findings": lambda c, _, kw: c.projects.findings("p", **kw),
    "projects.chain_of_custody": lambda c, _, kw: c.projects.chain_of_custody("p", **kw),
    "projects.deliverables": lambda c, _, kw: c.projects.deliverables("p", **kw),
    "projects.deliverable": lambda c, _, kw: c.projects.deliverable("p", "d-1", **kw),
    "projects.download_zip": lambda c, d, kw: c.projects.download_zip("p", d / "out.zip", **kw),
    "projects.download_deliverable": lambda c, d, kw: c.projects.download_deliverable(
        "p", "d-1", d / "out.txt", **kw
    ),
    "projects.resume": lambda c, _, kw: c.projects.resume("p", **kw),
    "projects.resume_human_review": lambda c, _, kw: c.projects.resume_human_review("p", **kw),
}


def _recording() -> tuple[list[httpx2.Request], httpx2.MockTransport]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return _respond(request)

    return seen, httpx2.MockTransport(handler)


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    (tmp_path / "a.txt").write_text("hello")
    return tmp_path


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [({"timeout": CALL_TIMEOUT}, CALL_TIMEOUT), ({}, CLIENT_TIMEOUT)],
    ids=["per-call", "client-default"],
)
@pytest.mark.parametrize("name", list(CALLS))
def test_sync_call_timeout(
    name: str, kwargs: dict[str, float], expected: float, workdir: Path
) -> None:
    seen, transport = _recording()
    with ArbitrClient(
        api_key="k", base_url="https://api.test", timeout=CLIENT_TIMEOUT, transport=transport
    ) as client:
        CALLS[name](client, workdir, kwargs)

    [request] = seen
    assert request.extensions["timeout"]["read"] == expected


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [({"timeout": CALL_TIMEOUT}, CALL_TIMEOUT), ({}, CLIENT_TIMEOUT)],
    ids=["per-call", "client-default"],
)
@pytest.mark.parametrize("name", list(CALLS))
async def test_async_call_timeout(
    name: str, kwargs: dict[str, float], expected: float, workdir: Path
) -> None:
    seen, transport = _recording()
    async with AsyncArbitrClient(
        api_key="k", base_url="https://api.test", timeout=CLIENT_TIMEOUT, transport=transport
    ) as client:
        await CALLS[name](client, workdir, kwargs)

    [request] = seen
    assert request.extensions["timeout"]["read"] == expected


def test_sync_timeout_accepts_an_httpx2_timeout() -> None:
    """A short connect timeout with a long read one, on the client and on one call."""
    seen, transport = _recording()
    with ArbitrClient(
        api_key="k",
        base_url="https://api.test",
        timeout=httpx2.Timeout(30.0, connect=5.0),
        transport=transport,
    ) as client:
        client.credits.balance()
        client.credits.balance(timeout=httpx2.Timeout(130.0, connect=5.0))

    assert [r.extensions["timeout"]["connect"] for r in seen] == [5.0, 5.0]
    assert [r.extensions["timeout"]["read"] for r in seen] == [30.0, 130.0]


async def test_async_timeout_accepts_an_httpx2_timeout() -> None:
    seen, transport = _recording()
    async with AsyncArbitrClient(
        api_key="k",
        base_url="https://api.test",
        timeout=httpx2.Timeout(30.0, connect=5.0),
        transport=transport,
    ) as client:
        await client.credits.balance()
        await client.credits.balance(timeout=httpx2.Timeout(130.0, connect=5.0))

    assert [r.extensions["timeout"]["connect"] for r in seen] == [5.0, 5.0]
    assert [r.extensions["timeout"]["read"] for r in seen] == [30.0, 130.0]
