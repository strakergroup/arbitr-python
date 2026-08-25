"""Pinned OpenAPI snapshot vs another document (live prod spec in CI)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import httpx
import pytest
import respx

from arbitr import OpenAPIDocumentError, pinned_spec
from arbitr._constants import DEFAULT_BASE_URL
from arbitr._spec import PROD_OPENAPI_URL, openapi_document_diff

_REPO = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO / "scripts" / "check_pinned_spec.py"
_SPEC_URL = "https://spec.test/openapi.json"

_MIN_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "arbitr", "version": "1"},
    "paths": {"/v1/me": {"get": {"operationId": "getCurrentKey"}}},
}


def test_shuffled_keys_and_integer_floats_are_not_drift() -> None:
    left = {"openapi": "3.1.0", "info": {"version": 1.0, "title": "a"}, "paths": {}}
    right = {"paths": {}, "info": {"title": "a", "version": 1}, "openapi": "3.1.0"}
    assert openapi_document_diff(left, right) is None


def test_new_path_is_drift() -> None:
    other = {
        "openapi": "3.1.0",
        "info": {"title": "arbitr", "version": "1"},
        "paths": {
            "/v1/me": {"get": {"operationId": "getCurrentKey"}},
            "/v1/projects/{project_id}/findings": {"get": {"operationId": "listProjectFindings"}},
        },
    }
    diff = openapi_document_diff(_MIN_SPEC, other)
    assert diff is not None
    assert "listProjectFindings" in diff
    assert "/v1/projects/{project_id}/findings" in diff


def test_cli_other_file_matching_pin_exits_0(tmp_path: Path) -> None:
    other = tmp_path / "live.json"
    other.write_text(json.dumps(pinned_spec(), indent=4) + "\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), "--other-file", str(other)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "matches" in result.stdout.lower()


def test_cli_other_file_with_extra_path_exits_1(tmp_path: Path) -> None:
    live = pinned_spec()
    live.setdefault("paths", {})["/v1/projects/{project_id}/findings"] = {
        "get": {"operationId": "listProjectFindings"}
    }
    other = tmp_path / "live.json"
    other.write_text(json.dumps(live), encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), "--other-file", str(other)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "listProjectFindings" in result.stdout


@pytest.fixture
def script() -> ModuleType:
    """The CI entrypoint loaded in-process so respx can intercept its fetch."""
    spec = importlib.util.spec_from_file_location("check_pinned_spec", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def spec_api() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url="https://spec.test") as router:
        yield router


def test_cli_invalid_packaged_pin_exits_4_not_unreadable_live(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A corrupt pin must not be retried as 'could not read production OpenAPI'."""

    def broken_pin() -> dict[str, object]:
        raise OpenAPIDocumentError("openapi.json is not valid JSON")

    monkeypatch.setattr(script, "pinned_spec", broken_pin)
    assert script.main(["--url", _SPEC_URL]) == script.EXIT_PIN_UNREADABLE
    assert "openapi.json is not valid JSON" in capsys.readouterr().err


def test_unexpected_error_exits_3_not_drift(
    script: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A script bug must not be annotated as pin-vs-prod drift."""

    def boom() -> dict[str, object]:
        raise RuntimeError("packaging bug")

    monkeypatch.setattr(script, "pinned_spec", boom)
    assert script.main(["--other-file", "unused.json"]) == script.EXIT_UNEXPECTED
    err = capsys.readouterr().err
    assert "unexpected failure" in err
    assert "packaging bug" in err


def test_prod_openapi_url_uses_the_public_default_host() -> None:
    assert f"{DEFAULT_BASE_URL}/openapi.json" == PROD_OPENAPI_URL


def test_fetched_url_matching_pin_exits_0(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_api.get("/openapi.json").mock(return_value=httpx.Response(200, json=pinned_spec()))
    assert script.main(["--url", _SPEC_URL]) == 0
    assert "matches" in capsys.readouterr().out.lower()


def test_fetched_url_with_extra_path_exits_1(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    live = pinned_spec()
    live.setdefault("paths", {})["/v1/projects/{project_id}/findings"] = {
        "get": {"operationId": "listProjectFindings"}
    }
    spec_api.get("/openapi.json").mock(return_value=httpx.Response(200, json=live))
    assert script.main(["--url", _SPEC_URL]) == 1
    assert "listProjectFindings" in capsys.readouterr().out


def test_unreachable_url_exits_2(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    """A network flake must not be reported as drift."""
    spec_api.get("/openapi.json").mock(side_effect=httpx.ConnectError("Connection refused"))
    assert script.main(["--url", _SPEC_URL]) == 2
    err = capsys.readouterr().err
    assert "failed to fetch" in err
    assert "Connection refused" in err


def test_server_error_from_url_exits_2(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_api.get("/openapi.json").mock(return_value=httpx.Response(503))
    assert script.main(["--url", _SPEC_URL]) == 2
    err = capsys.readouterr().err
    assert "failed to fetch" in err
    assert "503" in err


def test_non_json_body_from_url_exits_2(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    """A proxy or error page served as 200 is a parse failure, not drift."""
    spec_api.get("/openapi.json").mock(
        return_value=httpx.Response(200, text="<html>gateway timeout</html>")
    )
    assert script.main(["--url", _SPEC_URL]) == 2
    assert "not valid JSON" in capsys.readouterr().err


def test_json_object_without_openapi_fields_exits_2(
    script: ModuleType, spec_api: respx.MockRouter, capsys: pytest.CaptureFixture[str]
) -> None:
    spec_api.get("/openapi.json").mock(
        return_value=httpx.Response(200, json={"detail": "temporarily unavailable"})
    )
    assert script.main(["--url", _SPEC_URL]) == 2
    assert "not an OpenAPI document" in capsys.readouterr().err


def test_fetch_targets_production_by_default(script: ModuleType) -> None:
    """No --url must mean the public prod host, since CI passes no arguments."""
    with respx.mock(assert_all_called=True) as router:
        route = router.get(script.PROD_OPENAPI_URL).mock(
            return_value=httpx.Response(200, json=pinned_spec())
        )
        assert script.main([]) == 0
    assert route.called


def test_cli_other_file_invalid_json_exits_2(tmp_path: Path) -> None:
    other = tmp_path / "live.json"
    other.write_text("{not json", encoding="utf-8")
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), "--other-file", str(other)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "not valid JSON" in result.stderr


def test_cli_missing_other_file_exits_2(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(_SCRIPT), "--other-file", str(missing)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "cannot read" in result.stderr
