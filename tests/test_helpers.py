"""Pure helpers: dotenv parsing, locale normalization, downloads, pinned spec."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from arbitr import ArbitrClient, pinned_spec
from arbitr._constants import ACTION_REQUIRED_STATUSES, TERMINAL_STATUSES
from arbitr._coverage import OPERATION_METHODS
from arbitr._env import read_env_file
from arbitr._files import load_upload_parts
from arbitr._http import awrite_download_file, derive_ui_url, write_download_file
from arbitr._projects import normalize_locale_code, project_submit_form
from arbitr._wait import decide_project_wait
from arbitr.errors import BareLocaleCodeError, ClientInputError
from arbitr.generated.models import ProjectResponse
from payloads import project_json


class TestDotenvParsing:
    def test_plain_key_value(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("ARBITR_API_KEY=abr_test_1\n")
        assert read_env_file(env) == {"ARBITR_API_KEY": "abr_test_1"}

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert read_env_file(tmp_path / "absent") == {}

    def test_comments_and_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("# a comment\n\n  \nA=1\n")
        assert read_env_file(env) == {"A": "1"}

    def test_export_prefix_is_understood(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text('export ARBITR_API_KEY="abr_test_2"\n')
        assert read_env_file(env) == {"ARBITR_API_KEY": "abr_test_2"}

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('K="quoted"', "quoted"),
            ("K='quoted'", "quoted"),
            ("K=bare", "bare"),
            # A lone trailing/leading quote is part of the value, not a wrapper.
            ('K=trails"', 'trails"'),
            ("K='mismatched\"", "'mismatched\""),
            ("K=", ""),
            ("K=a=b", "a=b"),
            ("K=has#hash", "has#hash"),
        ],
    )
    def test_value_unquoting(self, tmp_path: Path, raw: str, expected: str) -> None:
        env = tmp_path / ".env"
        env.write_text(f"{raw}\n")
        assert read_env_file(env)["K"] == expected

    def test_later_lines_win(self, tmp_path: Path) -> None:
        env = tmp_path / ".env"
        env.write_text("K=first\nK=second\n")
        assert read_env_file(env)["K"] == "second"


class TestLocaleNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("fr-FR", "fr-fr"),
            ("FR-fr", "fr-fr"),
            ("  ja-JP  ", "ja-jp"),
            ("es-419", "es-419"),
            ("pa-Guru-IN", "pa-guru-in"),
            ("ko-kr", "ko-kr"),
        ],
    )
    def test_codes_are_lowercased_and_trimmed(self, raw: str, expected: str) -> None:
        assert normalize_locale_code(raw) == expected

    def test_bare_codes_are_rejected(self) -> None:
        """Expanding `fr` would pick a region for the caller; resolve() does that."""
        with pytest.raises(BareLocaleCodeError) as raised:
            normalize_locale_code("FR")
        assert raised.value.code == "FR"

    def test_empty_codes_are_rejected(self) -> None:
        with pytest.raises(ClientInputError, match="must not be empty"):
            normalize_locale_code("  ")

    def test_submit_form_normalizes_every_locale_field(self) -> None:
        form = project_submit_form(
            name="demo",
            target_language_codes=["KO-KR", " fr-FR "],
            source_language_code="EN-US",
            workflow=None,
            due_date=None,
        )
        assert form["target_language_codes"] == '["ko-kr", "fr-fr"]'
        assert form["source_language_code"] == "en-us"

    def test_submit_form_leaves_workflow_case_alone(self) -> None:
        form = project_submit_form(
            name="demo",
            target_language_codes=["ko-kr"],
            source_language_code="en-us",
            workflow=["AI_TRANSLATION", "TRANSLATION"],
            due_date="2026-08-01",
        )
        assert form["workflow"] == '["AI_TRANSLATION", "TRANSLATION"]'
        assert form["due_date"] == "2026-08-01"

    def test_submit_form_omits_due_date_when_absent(self) -> None:
        form = project_submit_form(
            name="d",
            target_language_codes=["ko-kr"],
            source_language_code="en-us",
            workflow=None,
            due_date=None,
        )
        assert "due_date" not in form


class TestLoadUploadParts:
    def test_path_is_read_into_bytes(self, tmp_path: Path) -> None:
        path = tmp_path / "hello.txt"
        path.write_bytes(b"hello world")
        parts = load_upload_parts([path], "allowlist")
        assert len(parts) == 1
        field, (name, content, content_type) = parts[0]
        assert field == "file"
        assert name == "hello.txt"
        assert content == b"hello world"
        assert content_type == "text/plain"

    def test_bytes_tuple_is_unchanged(self) -> None:
        parts = load_upload_parts([("a.txt", b"hi", "text/plain")], "allowlist")
        assert parts == [("file", ("a.txt", b"hi", "text/plain"))]

    def test_binary_handle_position_is_restored(self, tmp_path: Path) -> None:
        path = tmp_path / "a.txt"
        path.write_bytes(b"abcdef")
        with path.open("rb") as handle:
            handle.seek(2)
            parts = load_upload_parts([handle], "allowlist")
            assert parts[0][1][1] == b"abcdef"
            assert handle.tell() == 2


class TestWaitStateMachine:
    def parse(self, status: str) -> ProjectResponse:
        return ProjectResponse.model_validate(project_json("p", status=status))

    @pytest.mark.parametrize("status", sorted(TERMINAL_STATUSES))
    def test_terminal_statuses_stop_immediately(self, status: str) -> None:
        decision = decide_project_wait(
            self.parse(status), agent_selection_streak=0, on_action_required="raise"
        )
        assert decision.kind == "terminal"

    def test_cancelled_is_terminal(self) -> None:
        assert "cancelled" in TERMINAL_STATUSES

    def test_awaiting_payment_parks_on_first_sight(self) -> None:
        decision = decide_project_wait(
            self.parse("awaiting_payment"), agent_selection_streak=0, on_action_required="raise"
        )
        assert decision.kind == "parked"

    def test_agent_selection_needs_two_consecutive_polls(self) -> None:
        first = decide_project_wait(
            self.parse("agent_selection"), agent_selection_streak=0, on_action_required="raise"
        )
        assert first.kind == "continue"
        assert first.agent_selection_streak == 1
        second = decide_project_wait(
            self.parse("agent_selection"),
            agent_selection_streak=first.agent_selection_streak,
            on_action_required="raise",
        )
        assert second.kind == "parked"

    def test_streak_resets_when_the_status_moves_on(self) -> None:
        decision = decide_project_wait(
            self.parse("translating"), agent_selection_streak=5, on_action_required="raise"
        )
        assert decision.agent_selection_streak == 0

    @pytest.mark.parametrize("status", sorted(ACTION_REQUIRED_STATUSES))
    def test_wait_mode_never_parks(self, status: str) -> None:
        decision = decide_project_wait(
            self.parse(status), agent_selection_streak=9, on_action_required="wait"
        )
        assert decision.kind == "continue"


class TestDownloadWriters:
    def chunks(self, count: int, size: int = 1024) -> Iterator[bytes]:
        for index in range(count):
            yield bytes([index % 256]) * size

    def expected(self, count: int, size: int = 1024) -> bytes:
        return b"".join(bytes([index % 256]) * size for index in range(count))

    def test_sync_writer_concatenates_every_chunk_in_order(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"
        write_download_file(dest, self.chunks(500))
        assert dest.read_bytes() == self.expected(500)

    def test_sync_writer_handles_an_empty_body(self, tmp_path: Path) -> None:
        dest = tmp_path / "empty.bin"
        write_download_file(dest, iter([]))
        assert dest.read_bytes() == b""

    def test_sync_writer_creates_parent_directories(self, tmp_path: Path) -> None:
        dest = tmp_path / "nested" / "deep" / "out.bin"
        write_download_file(dest, self.chunks(2))
        assert dest.exists()

    def test_sync_writer_leaves_no_part_file_behind(self, tmp_path: Path) -> None:
        write_download_file(tmp_path / "out.bin", self.chunks(3))
        assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]

    def test_sync_writer_cleans_up_after_a_mid_stream_failure(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"
        dest.write_bytes(b"original")

        def failing() -> Iterator[bytes]:
            yield b"partial"
            raise OSError("stream died")

        with pytest.raises(ClientInputError, match="cannot write") as raised:
            write_download_file(dest, failing())
        assert isinstance(raised.value.__cause__, OSError)
        assert dest.read_bytes() == b"original"
        assert [p.name for p in tmp_path.iterdir()] == ["out.bin"]

    def test_async_writer_matches_the_sync_writer(self, tmp_path: Path) -> None:
        async def achunks() -> AsyncIterator[bytes]:
            for chunk in self.chunks(500):
                yield chunk

        dest = tmp_path / "out.bin"
        asyncio.run(awrite_download_file(dest, achunks()))
        assert dest.read_bytes() == self.expected(500)

    def test_async_writer_cleans_up_after_a_mid_stream_failure(self, tmp_path: Path) -> None:
        dest = tmp_path / "out.bin"

        async def failing() -> AsyncIterator[bytes]:
            yield b"partial"
            raise OSError("stream died")

        with pytest.raises(ClientInputError, match="cannot write") as raised:
            asyncio.run(awrite_download_file(dest, failing()))
        assert isinstance(raised.value.__cause__, OSError)
        assert not dest.exists()
        assert list(tmp_path.iterdir()) == []


class TestUiUrlDerivation:
    @pytest.mark.parametrize(
        ("api", "ui"),
        [
            ("https://api-arbitr.straker.ai", "https://arbitr.straker.ai"),
            ("https://preview-api-arbitr.example.com", "https://preview-arbitr.example.com"),
            ("https://api.arbitr.com", "https://arbitr.com"),
            ("https://arbitr.example", "https://arbitr.example"),
            ("http://localhost:8000", "http://localhost:8000"),
        ],
    )
    def test_derivation(self, api: str, ui: str) -> None:
        assert derive_ui_url(api) == ui


class TestPinnedSpec:
    def test_the_snapshot_ships_with_the_package(self) -> None:
        spec = pinned_spec()
        assert spec["openapi"].startswith("3.")
        assert spec["info"]["version"] == "1"

    def test_every_wrapped_operation_is_in_the_snapshot(self) -> None:
        ids = {
            op["operationId"]
            for path in pinned_spec()["paths"].values()
            for op in path.values()
            if isinstance(op, dict) and "operationId" in op
        }
        assert set(OPERATION_METHODS) <= ids

    def test_it_is_the_same_object_the_client_targets(self) -> None:
        with ArbitrClient(api_key="k") as client:
            assert client.base_url.rstrip("/") in {
                server["url"].rstrip("/") for server in pinned_spec()["servers"]
            }
