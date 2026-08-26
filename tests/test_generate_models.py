"""Post-processors in scripts/generate_models.py — no generator subprocess."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_models.py"
_SPEC = importlib.util.spec_from_file_location("generate_models", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
generate_models = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(generate_models)


def test_check_model_names_rejects_numeric_suffix() -> None:
    with pytest.raises(SystemExit, match="Status1"):
        generate_models.check_model_names("class Status1(StrEnum):\n    open = 'open'\n")


def test_use_utc_datetime_when_awaredatetime_is_first() -> None:
    text = (
        "from datetime import date\n"
        "from pydantic import AwareDatetime, BaseModel, ConfigDict\n"
        "\n"
        "created_at: AwareDatetime\n"
    )
    out = generate_models.use_utc_datetime(text)
    assert "from arbitr._datetime import UtcDatetime" in out
    assert "from pydantic import BaseModel, ConfigDict" in out
    pydantic_line = out.split("from pydantic import ", 1)[1].split("\n", 1)[0]
    assert "UtcDatetime" not in pydantic_line
    assert "created_at: UtcDatetime" in out
    assert "AwareDatetime" not in out


def test_use_utc_datetime_when_awaredatetime_is_last() -> None:
    text = "from pydantic import BaseModel, ConfigDict, AwareDatetime\ncreated_at: AwareDatetime\n"
    out = generate_models.use_utc_datetime(text)
    assert "from arbitr._datetime import UtcDatetime" in out
    assert "from pydantic import BaseModel, ConfigDict" in out
    assert "AwareDatetime" not in out
    pydantic_line = out.split("from pydantic import ", 1)[1].split("\n", 1)[0]
    assert "UtcDatetime" not in pydantic_line


def test_use_utc_datetime_parenthesized_import() -> None:
    text = (
        "from pydantic import (\n    AwareDatetime,\n    BaseModel,\n)\ncreated_at: AwareDatetime\n"
    )
    out = generate_models.use_utc_datetime(text)
    assert "from arbitr._datetime import UtcDatetime" in out
    assert "AwareDatetime" not in out
    match = generate_models._PYDANTIC_IMPORT.search(out)
    assert match is not None
    assert "UtcDatetime" not in match.group(0)
    assert "BaseModel" in match.group(0)


def test_use_utc_datetime_requires_awaredatetime() -> None:
    with pytest.raises(SystemExit, match="expected AwareDatetime"):
        generate_models.use_utc_datetime("from pydantic import BaseModel\n")
