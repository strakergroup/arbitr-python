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


def test_use_tolerant_enums_rewrites_every_enum_base() -> None:
    text = (
        "from datetime import date\n"
        "from enum import StrEnum\n"
        "from typing import Annotated\n"
        "\n"
        "from arbitr._datetime import UtcDatetime\n"
        "from pydantic import BaseModel\n"
        "\n"
        "class FindingType(StrEnum):\n"
        "    repaired = 'repaired'\n"
        "\n"
        "class ApiKeyMode(StrEnum):\n"
        "    live = 'live'\n"
    )
    out = generate_models.use_tolerant_enums(text)
    assert "from arbitr._enums import TolerantStrEnum\nfrom pydantic import BaseModel\n" in out
    assert "class FindingType(TolerantStrEnum):" in out
    assert "class ApiKeyMode(TolerantStrEnum):" in out
    assert "from enum import StrEnum" not in out


def test_use_tolerant_enums_requires_an_enum_to_rewrite() -> None:
    with pytest.raises(SystemExit, match="StrEnum"):
        generate_models.use_tolerant_enums("from pydantic import BaseModel\n")


def test_use_tolerant_enums_rejects_a_surviving_bare_strenum() -> None:
    text = (
        "from enum import StrEnum\n"
        "from pydantic import BaseModel\n"
        "\n"
        "class Odd(StrEnum):\n"
        "    a = 'a'\n"
        "\n"
        "Alias = StrEnum\n"
    )
    with pytest.raises(SystemExit, match="survived"):
        generate_models.use_tolerant_enums(text)


# datamodel-code-generator's raw output, before ruff normalises the quotes.
_FINDING_UNION_TEXT = (
    "from typing import Annotated, Literal\n"
    "\n"
    "from pydantic import BaseModel, ConfigDict, Field\n"
    "\n"
    "\n"
    "class AgentFinding(BaseModel):\n"
    "    model_config = ConfigDict(\n"
    "        extra='allow',\n"
    "    )\n"
    "    kind: Literal['agent_finding'] = Field('agent_finding', title='Kind')\n"
    "    id: str = Field(..., title='Id')\n"
    "\n"
    "\n"
    "class FlagFinding(BaseModel):\n"
    "    kind: Literal['flag'] = Field('flag', title='Kind')\n"
    "\n"
    "\n"
    "class FindingListResponse(BaseModel):\n"
    "    findings: list[\n"
    "        Annotated[FlagFinding | AgentFinding, Field(discriminator='kind')]\n"
    "    ] = Field(..., title='Findings')\n"
)


def test_use_tolerant_findings_tags_known_kinds_and_falls_back_to_unknown_finding() -> None:
    out = generate_models.use_tolerant_findings(_FINDING_UNION_TEXT)
    assert "discriminator=" not in out
    assert (
        'Annotated[Annotated[FlagFinding, Tag("flag")]'
        ' | Annotated[AgentFinding, Tag("agent_finding")]'
        ' | Annotated[UnknownFinding, Tag("unknown")], Discriminator(_finding_tag)]'
    ) in out
    assert "return kind if kind in ('flag', 'agent_finding') else \"unknown\"" in out
    assert "from pydantic import Discriminator, Tag\nfrom pydantic import BaseModel" in out
    assert out.index("class UnknownFinding(BaseModel):") < out.index("class FindingListResponse(")


def test_use_tolerant_findings_requires_the_findings_union() -> None:
    with pytest.raises(SystemExit, match="discriminator"):
        generate_models.use_tolerant_findings("from pydantic import BaseModel\n")
