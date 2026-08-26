"""Regenerate pydantic models from the pinned OpenAPI snapshot.

Do not edit src/arbitr/generated/ by hand. Re-run:

    uv run python scripts/generate_models.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "src" / "arbitr" / "openapi.json"
OUT = ROOT / "src" / "arbitr" / "generated" / "models.py"

HEADER = '''\
"""Generated from the pinned OpenAPI snapshot. Do not edit by hand.

Regenerate with: uv run python scripts/generate_models.py
"""
'''

# Inline enums are named after their property, so two schemas with a `status`
# field collide and the loser becomes `Status1` — a name that silently moves to
# a different enum as soon as another schema is added. Pin the colliding ones.
# The key is the generator's internal enum ref; `check_model_names` fails the
# run if that format ever changes, rather than letting `Status1` come back.
ENUM_REF = (
    "openapi.json#/components/schemas/{schema}/{field}#-datamodel-code-generator-#-enum-#-special-#"
)
MODEL_NAMES = {
    ENUM_REF.format(schema="FlagFinding", field="severity"): "FindingSeverity",
    ENUM_REF.format(schema="FlagFinding", field="status"): "FindingStatus",
    ENUM_REF.format(schema="HumanReviewResponse", field="status"): "HumanReviewStatus",
    # Not a collision — `Mode` is just too generic for a name callers import.
    ENUM_REF.format(schema="MeResponse", field="mode"): "ApiKeyMode",
}


_PYDANTIC_IMPORT = re.compile(r"from pydantic import (\([^)]*\)|[^\n]+)")


def check_model_names(text: str) -> None:
    """Reject a numeric-suffix class name, which means two schemas collided.

    ``Address``/``Address1`` names depend on schema ordering, so which model
    owns the bare name changes without warning. Add a ``MODEL_NAMES`` entry.
    """
    collided = re.findall(r"^class ([A-Za-z_]+\d+)\(", text, flags=re.MULTILINE)
    if collided:
        raise SystemExit(f"name collision fell back to a numeric suffix: {', '.join(collided)}")
    for name in MODEL_NAMES.values():
        if f"class {name}(" not in text:
            raise SystemExit(f"expected {name} in the generated output; check MODEL_NAMES")


def _imported_names(imported: str) -> tuple[list[str], bool]:
    inner = imported.strip()
    parenthesized = inner.startswith("(") and inner.endswith(")")
    if parenthesized:
        inner = inner[1:-1]
    names = [part.strip() for part in inner.split(",") if part.strip()]
    return names, parenthesized


def _drop_imported_name(imported: str, name: str) -> str:
    names, parenthesized = _imported_names(imported)
    kept = [item for item in names if item != name]
    if not kept:
        raise SystemExit(f"pydantic import would be empty after removing {name}")
    joined = ", ".join(kept)
    return f"({joined})" if parenthesized else joined


def use_utc_datetime(text: str) -> str:
    """Swap pydantic's ``AwareDatetime`` for ``arbitr._datetime.UtcDatetime``.

    Live /v1 has served UTC timestamps with no offset. ``AwareDatetime`` rejects
    those outright and a bare ``datetime`` leaks a naive value to the caller;
    ``UtcDatetime`` accepts both and always yields an aware UTC value.
    """
    if "AwareDatetime" not in text:
        raise SystemExit("expected AwareDatetime in the generated output")
    text = text.replace("AwareDatetime", "UtcDatetime")
    match = _PYDANTIC_IMPORT.search(text)
    if match is None:
        raise SystemExit("expected a pydantic import in the generated output")
    cleaned = _drop_imported_name(match.group(1), "UtcDatetime")
    text = text[: match.start(1)] + cleaned + text[match.end(1) :]
    if "from arbitr._datetime import UtcDatetime" not in text:
        text, inserted = re.subn(
            r"from pydantic import ",
            "from arbitr._datetime import UtcDatetime\nfrom pydantic import ",
            text,
            count=1,
        )
        if inserted != 1:
            raise SystemExit("expected a pydantic import to hang the UtcDatetime import on")
    pydantic_import = _PYDANTIC_IMPORT.search(text)
    if pydantic_import is None or "UtcDatetime" in pydantic_import.group(0):
        raise SystemExit("UtcDatetime still imported from pydantic")
    if "from arbitr._datetime import UtcDatetime" not in text:
        raise SystemExit("failed to import UtcDatetime from arbitr._datetime")
    return text


def main() -> None:
    """Run datamodel-code-generator against the pinned spec."""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(SPEC),
        "--input-file-type",
        "openapi",
        "--output",
        str(OUT),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--target-python-version",
        "3.11",
        "--use-standard-collections",
        "--use-union-operator",
        "--collapse-root-models",
        "--disable-timestamp",
        "--extra-fields",
        "allow",
        "--output-datetime-class",
        "AwareDatetime",
        "--model-name-map",
        json.dumps(MODEL_NAMES),
        "--custom-file-header",
        HEADER,
    ]
    subprocess.run(cmd, check=True)
    text = OUT.read_text()
    check_model_names(text)
    OUT.write_text(use_utc_datetime(text))
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(OUT)],
        check=True,
    )
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
