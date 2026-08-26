"""CLI tests — Typer CliRunner; HTTP intercepted with respx."""

from __future__ import annotations

import json
import re
import zipfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import httpx
import pytest
import respx
import typer
from typer.testing import CliRunner, Result

import arbitr.cli as cli_module
from arbitr import ArbitrClient
from arbitr.cli import app
from payloads import (
    agent_finding_json,
    chain_of_custody_json,
    finding_list_json,
    flag_finding_json,
    language_list_json,
    project_json,
)

ENV = {
    "ARBITR_API_KEY": "py_test_cli",
    "ARBITR_BASE_URL": "https://api.test",
}

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url="https://api.test", assert_all_called=True) as router:
        yield router


def test_credits(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/credits/balance").respond(200, json={"balance": 42})
    result = runner.invoke(app, ["credits"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output) == {"balance": 42}


def test_submit_wait_download(runner: CliRunner, api: respx.MockRouter, tmp_path: Path) -> None:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ko.xliff", "<xliff/>")

    api.post("/v1/projects").respond(201, json=project_json("p-1", status="extracting"))
    api.get("/v1/projects/p-1").respond(200, json=project_json("p-1", status="completed"))
    api.get("/v1/projects/p-1/deliverables", params={"format": "zip"}).respond(
        200, content=buf.getvalue()
    )

    src = tmp_path / "doc.txt"
    src.write_text("hello")
    out_dir = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "submit",
            str(src),
            "--locales",
            "ko-kr,fr-fr",
            "--wait",
            "--interval",
            "0.01",
            "--out",
            str(out_dir),
        ],
        env=ENV,
    )
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["status"] == "completed"
    downloaded = out_dir / Path(out["_downloaded_zip"]).name
    assert downloaded.exists()


def test_error_envelope_goes_to_stderr(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/whatever").respond(
        422,
        json={"error": {"code": "validation_error", "message": "bad", "request_id": "r-9"}},
    )
    result = runner.invoke(app, ["status", "whatever"], env=ENV)
    err = json.loads(result.stderr)
    assert result.exit_code == 1
    assert err["error"]["code"] == "validation_error"
    assert err["error"]["request_id"] == "r-9"


def test_submit_disallowed_extension_exits_2(runner: CliRunner, tmp_path: Path) -> None:
    exe = tmp_path / "evil.exe"
    exe.write_bytes(b"MZ")
    result = runner.invoke(app, ["submit", str(exe), "--locales", "ja-jp"], env=ENV)
    assert result.exit_code == 2
    assert "allowlist" in result.stderr


def test_wait_exits_3_at_agent_selection_gate(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p").respond(200, json=project_json("p", status="agent_selection"))
    result = runner.invoke(app, ["wait", "p", "--interval", "0.01"], env=ENV)
    assert result.exit_code == 3
    assert "action required" in result.stderr
    assert "Start Campaign" in result.stderr


def test_link_command(runner: CliRunner) -> None:
    result = runner.invoke(app, ["link", "abc-123"], env=ENV)
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["project"] == "https://test/projects/abc-123"
    assert out["agents_start_campaign"] == "https://test/projects/abc-123/agents"


def test_link_works_without_an_api_key(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        ["--base-url", "https://api.test", "link", "abc-123"],
        env={"ARBITR_API_KEY": "", "arbitr_api_key": ""},
    )
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["project"] == "https://test/projects/abc-123"


def test_cli_retries_a_429_by_default(runner: CliRunner, api: respx.MockRouter) -> None:
    route = api.get("/v1/credits/balance")
    route.side_effect = [
        httpx.Response(
            429,
            json={"error": {"code": "rate_limited", "message": "slow"}},
            headers={"Retry-After": "0"},
        ),
        httpx.Response(200, json={"balance": 9}),
    ]
    result = runner.invoke(app, ["credits"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output) == {"balance": 9}
    assert route.call_count == 2


def test_cli_max_retries_zero_does_not_retry(runner: CliRunner, api: respx.MockRouter) -> None:
    route = api.get("/v1/credits/balance").respond(
        429,
        json={"error": {"code": "rate_limited", "message": "slow"}},
        headers={"Retry-After": "0"},
    )
    result = runner.invoke(app, ["--max-retries", "0", "credits"], env=ENV)
    assert_no_traceback(result, exit_code=1)
    assert route.call_count == 1


def test_missing_key_exits_2(runner: CliRunner) -> None:
    result = runner.invoke(
        app,
        ["--env-file", "/nonexistent/.env", "credits"],
        env={"ARBITR_API_KEY": "", "arbitr_api_key": "", "arbitr_api_domain": ""},
    )
    assert result.exit_code == 2
    assert "ARBITR_API_KEY" in result.stderr


def test_help_works_without_credentials(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--help"], env={"ARBITR_API_KEY": "", "arbitr_api_key": ""})
    assert result.exit_code == 0
    assert "credits" in result.output
    assert "projects" in result.output
    assert "--api-key" not in result.output


def test_api_key_flag_is_not_accepted(runner: CliRunner) -> None:
    result = runner.invoke(app, ["--api-key", "py_test_secret", "me"], env=ENV, color=True)
    assert result.exit_code != 0
    combined = _ANSI_ESCAPE.sub("", f"{result.output}\n{result.stderr}")
    assert "No such option" in combined
    assert "--api-key" in combined


def test_no_command_prints_usage(runner: CliRunner) -> None:
    result = runner.invoke(app, [], env=ENV)
    assert result.exit_code == 2
    assert "Usage" in result.output or "Usage" in result.stderr


def assert_no_traceback(result: Result, *, exit_code: int) -> None:
    """A CLI failure must be a clean message, never a propagated exception."""
    escaped = result.exception
    assert escaped is None or isinstance(escaped, SystemExit), (
        f"exception escaped the CLI: {escaped!r}"
    )
    assert result.exit_code == exit_code
    assert "Traceback" not in result.stderr


def test_unreachable_host_reports_cleanly(runner: CliRunner) -> None:
    """Regression: a transport failure used to print a Rich traceback."""
    with respx.mock(base_url="https://api.test") as router:
        router.get("/v1/credits/balance").mock(side_effect=httpx.ConnectError("Connection refused"))
        result = runner.invoke(app, ["--max-retries", "0", "credits"], env=ENV)
    assert_no_traceback(result, exit_code=2)
    assert "Connection refused" in result.stderr
    assert "GET https://api.test/v1/credits/balance" in result.stderr
    assert "ARBITR_BASE_URL" in result.stderr


def test_request_timeout_reports_cleanly(runner: CliRunner) -> None:
    with respx.mock(base_url="https://api.test") as router:
        router.get("/v1/me").mock(side_effect=httpx.ReadTimeout("timed out"))
        result = runner.invoke(app, ["--max-retries", "0", "me"], env=ENV)
    assert_no_traceback(result, exit_code=2)
    assert "timed out" in result.stderr


def test_schema_drift_reports_cleanly(runner: CliRunner, api: respx.MockRouter) -> None:
    """Regression: ResponseParseError used to escape and print a traceback."""
    api.get("/v1/projects/p").respond(200, json={"id": "p"})
    result = runner.invoke(app, ["status", "p"], env=ENV)
    assert_no_traceback(result, exit_code=2)
    assert "did not match the published schema" in result.stderr
    assert "getProject" in result.stderr


def test_malformed_json_reports_cleanly(runner: CliRunner, api: respx.MockRouter) -> None:
    """Regression: json.JSONDecodeError used to escape and print a traceback."""
    api.get("/v1/me").respond(200, content=b"<html>nope</html>")
    result = runner.invoke(app, ["me"], env=ENV)
    assert_no_traceback(result, exit_code=2)
    assert "not valid JSON" in result.stderr


def test_payment_required_surfaces_the_shortfall(runner: CliRunner, api: respx.MockRouter) -> None:
    api.post("/v1/projects/p/resumptions").respond(
        402,
        json={
            "error": {
                "code": "payment_required",
                "message": "balance still short",
                "request_id": "r-4",
                "required": 100,
                "available": 10,
                "shortfall": 90,
            }
        },
    )
    result = runner.invoke(app, ["resume", "p"], env=ENV)
    assert_no_traceback(result, exit_code=1)
    err = json.loads(result.stderr)
    assert err["error"]["code"] == "payment_required"
    assert err["error"]["shortfall"] == 90


def test_awaiting_payment_gate_exits_3_with_a_resume_hint(
    runner: CliRunner, api: respx.MockRouter
) -> None:
    api.get("/v1/projects/p").respond(200, json=project_json("p", status="awaiting_payment"))
    result = runner.invoke(app, ["wait", "p", "--interval", "0.01"], env=ENV)
    assert_no_traceback(result, exit_code=3)
    assert "arbitr resume p" in result.stderr


def test_cancelled_project_is_terminal(runner: CliRunner, api: respx.MockRouter) -> None:
    """Regression: `cancelled` used to poll to the timeout."""
    route = api.get("/v1/projects/p").respond(200, json=project_json("p", status="cancelled"))
    result = runner.invoke(app, ["wait", "p", "--interval", "0.01"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "cancelled"
    assert route.call_count == 1


def test_submit_lowercases_locales(runner: CliRunner, api: respx.MockRouter) -> None:
    route = api.post("/v1/projects").respond(201, json=project_json("p-1"))
    src = Path("doc.txt")
    src.write_text("hello")
    result = runner.invoke(app, ["submit", str(src), "--locales", "KO-KR,fr-FR"], env=ENV)
    assert result.exit_code == 0
    body = route.calls.last.request.content
    assert json.dumps(["ko-kr", "fr-fr"]).encode() in body


def test_submit_resolve_locales_expands_bare_codes(
    runner: CliRunner, api: respx.MockRouter
) -> None:
    api.get("/v1/languages").respond(200, json=language_list_json())
    route = api.post("/v1/projects").respond(201, json=project_json("p-1"))
    src = Path("doc.txt")
    src.write_text("hello")
    result = runner.invoke(
        app, ["submit", str(src), "--locales", "ja", "--resolve-locales"], env=ENV
    )
    assert result.exit_code == 0
    assert json.dumps(["ja-jp"]).encode() in route.calls.last.request.content


def test_submit_rejects_bare_locale_without_resolve(runner: CliRunner, tmp_path: Path) -> None:
    src = tmp_path / "doc.txt"
    src.write_text("hello")
    result = runner.invoke(app, ["submit", str(src), "--locales", "ko"], env=ENV)
    assert_no_traceback(result, exit_code=2)
    assert "bare language code" in result.stderr


def test_submit_resolve_locales_reports_ambiguity(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/languages").respond(200, json=language_list_json())
    src = Path("doc.txt")
    src.write_text("hello")
    result = runner.invoke(
        app, ["submit", str(src), "--locales", "fr", "--resolve-locales"], env=ENV
    )
    assert_no_traceback(result, exit_code=2)
    assert "ambiguous" in result.stderr
    assert "fr-ca" in result.stderr and "fr-fr" in result.stderr


def test_locales_help_recommends_full_tags(runner: CliRunner) -> None:
    """Regression: the help text used to advertise `ko,fr-FR`, both rejected."""
    result = runner.invoke(app, ["submit", "--help"], env=ENV)
    assert result.exit_code == 0
    help_text = " ".join(result.output.split())
    assert "ko-kr,fr-fr" in help_text
    assert "ko,fr-FR" not in help_text


def track_clients(monkeypatch: pytest.MonkeyPatch) -> list[ArbitrClient]:
    """Record every client the CLI builds so a test can assert it was closed."""
    built: list[ArbitrClient] = []
    original = cli_module.get_client

    def spy(ctx: typer.Context) -> ArbitrClient:
        client = original(ctx)
        built.append(client)
        return client

    monkeypatch.setattr(cli_module, "get_client", spy)
    return built


def test_client_is_closed_after_each_command(
    runner: CliRunner, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the CLI used to leak an open httpx client per invocation."""
    built = track_clients(monkeypatch)
    api.get("/v1/credits/balance").respond(200, json={"balance": 1})
    result = runner.invoke(app, ["credits"], env=ENV)
    assert result.exit_code == 0
    assert len(built) == 1
    assert built[0].is_closed
    assert built[0].max_retries == 3


def test_client_is_closed_even_when_the_command_fails(
    runner: CliRunner, api: respx.MockRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = track_clients(monkeypatch)
    api.get("/v1/credits/balance").respond(
        500, json={"error": {"code": "server_error", "message": "boom"}}
    )
    result = runner.invoke(app, ["--max-retries", "0", "credits"], env=ENV)
    assert result.exit_code == 1
    assert built[0].is_closed


def test_download_command(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p/deliverables", params={"format": "zip"}).respond(
        200, content=b"PK\x03\x04zipbytes"
    )
    out = Path("bundle.zip")
    result = runner.invoke(app, ["download", "p", "--out", str(out)], env=ENV)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["bytes"] == len(b"PK\x03\x04zipbytes")
    assert out.read_bytes() == b"PK\x03\x04zipbytes"


def test_download_single_deliverable(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p/deliverables/d-1").respond(200, content=b"<xliff/>")
    out = Path("one.xliff")
    result = runner.invoke(
        app, ["download", "p", "--deliverable", "d-1", "--out", str(out)], env=ENV
    )
    assert result.exit_code == 0
    assert out.read_bytes() == b"<xliff/>"


def test_deliverables_command(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p/deliverables").respond(
        200,
        json={
            "deliverables": [{"id": "d-1", "file_id": "f", "file_type": "xliff"}],
            "page": {"number": 1, "has_more": False, "limit": 50},
        },
    )
    result = runner.invoke(app, ["deliverables", "p"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["deliverables"][0]["id"] == "d-1"


def test_findings_command(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p/findings").respond(
        200,
        json=finding_list_json([flag_finding_json()], has_more=False),
    )
    result = runner.invoke(app, ["findings", "p"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["findings"][0]["id"] == "flag-1"


def test_findings_all_walks_after(runner: CliRunner, api: respx.MockRouter) -> None:
    # respx treats ``params=`` as a subset match, so ``{"limit": "1"}`` would also
    # catch the follow-up ``after=`` request and ``--all`` would never stop.
    pages = {
        None: finding_list_json(
            [flag_finding_json("flag-1")], has_more=True, limit=1, after="0:0:flag-1"
        ),
        "0:0:flag-1": finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        token = request.url.params.get("after")
        assert token in pages
        return httpx.Response(200, json=pages[token])

    api.get("/v1/projects/p/findings").mock(side_effect=handler)
    result = runner.invoke(app, ["findings", "p", "--all", "--limit", "1"], env=ENV)
    assert result.exit_code == 0
    assert [item["id"] for item in json.loads(result.output)["findings"]] == ["flag-1", "find-2"]


def test_findings_all_after_resumes_from_token(runner: CliRunner, api: respx.MockRouter) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("after") == "0:0:flag-1"
        return httpx.Response(
            200,
            json=finding_list_json([agent_finding_json("find-2")], has_more=False, limit=1),
        )

    api.get("/v1/projects/p/findings").mock(side_effect=handler)
    result = runner.invoke(
        app, ["findings", "p", "--all", "--after", "0:0:flag-1", "--limit", "1"], env=ENV
    )
    assert result.exit_code == 0
    assert [item["id"] for item in json.loads(result.output)["findings"]] == ["find-2"]


def test_findings_rejects_out_of_range_limit(runner: CliRunner) -> None:
    """The spec caps limit at 200; reject locally instead of spending a 422."""
    result = runner.invoke(app, ["findings", "p", "--limit", "500"], env=ENV)
    assert result.exit_code == 2
    assert "200" in _ANSI_ESCAPE.sub("", f"{result.output}\n{result.stderr}")


def test_findings_rejects_unknown_severity(runner: CliRunner) -> None:
    result = runner.invoke(app, ["findings", "p", "--severity", "urgent"], env=ENV)
    assert result.exit_code == 2
    combined = _ANSI_ESCAPE.sub("", f"{result.output}\n{result.stderr}")
    assert "critical" in combined


def test_findings_sends_enum_filters_as_plain_strings(
    runner: CliRunner, api: respx.MockRouter
) -> None:
    route = api.get("/v1/projects/p/findings").respond(
        200, json=finding_list_json([flag_finding_json()])
    )
    result = runner.invoke(
        app, ["findings", "p", "--severity", "critical", "--status", "open"], env=ENV
    )
    assert result.exit_code == 0
    params = route.calls.last.request.url.params
    assert params.get("severity") == "critical"
    assert params.get("status") == "open"


def test_chain_of_custody_command(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p/chain-of-custody").respond(200, json=chain_of_custody_json("p"))
    result = runner.invoke(app, ["chain-of-custody", "p"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["created_via"] == "api"


def test_projects_all_follows_pagination(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects", params={"page": "1"}).respond(
        200,
        json={
            "projects": [project_json("p1")],
            "page": {"number": 1, "has_more": True, "limit": 50},
        },
    )
    api.get("/v1/projects", params={"page": "2"}).respond(
        200,
        json={
            "projects": [project_json("p2")],
            "page": {"number": 2, "has_more": False, "limit": 50},
        },
    )
    result = runner.invoke(app, ["projects", "--all"], env=ENV)
    assert result.exit_code == 0
    assert [p["id"] for p in json.loads(result.output)["projects"]] == ["p1", "p2"]


def test_projects_all_page_resumes_from_page(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects", params={"page": "2"}).respond(
        200,
        json={
            "projects": [project_json("p2")],
            "page": {"number": 2, "has_more": False, "limit": 50},
        },
    )
    result = runner.invoke(app, ["projects", "--all", "--page", "2"], env=ENV)
    assert result.exit_code == 0
    assert [p["id"] for p in json.loads(result.output)["projects"]] == ["p2"]


def test_projects_all_honours_limit(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects", params={"limit": "7", "page": "1"}).respond(
        200,
        json={
            "projects": [project_json("p1")],
            "page": {"number": 1, "has_more": False, "limit": 7},
        },
    )
    result = runner.invoke(app, ["projects", "--all", "--limit", "7"], env=ENV)
    assert result.exit_code == 0
    assert [p["id"] for p in json.loads(result.output)["projects"]] == ["p1"]


def test_status_command_annotates_ui_links(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/projects/p").respond(200, json=project_json("p", status="agent_selection"))
    result = runner.invoke(app, ["status", "p"], env=ENV)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_ui_url"] == "https://test/projects/p"
    assert payload["_action_url"] == "https://test/projects/p/agents"


def test_languages_command_filters(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/languages").respond(200, json=language_list_json())
    result = runner.invoke(app, ["languages", "--search", "japanese"], env=ENV)
    assert result.exit_code == 0
    assert [lang["bcp47"] for lang in json.loads(result.output)["languages"]] == ["ja-jp"]


def test_me_command(runner: CliRunner, api: respx.MockRouter) -> None:
    api.get("/v1/me").respond(
        200, json={"org_id": "org-1", "mode": "test", "scopes": ["verify:read"]}
    )
    result = runner.invoke(app, ["me"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["scopes"] == ["verify:read"]


def test_resume_human_review(runner: CliRunner, api: respx.MockRouter) -> None:
    api.post("/v1/projects/p/review/resumptions").respond(
        200,
        json={
            "status": "queued",
            "service_plan": ["TRANSLATION"],
            "charged_tc": 1,
            "requested_at": "2026-08-01T00:00:00Z",
        },
    )
    result = runner.invoke(app, ["resume", "p", "--human-review"], env=ENV)
    assert result.exit_code == 0
    assert json.loads(result.output)["status"] == "queued"
