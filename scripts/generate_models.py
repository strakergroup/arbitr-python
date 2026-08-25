"""Regenerate pydantic models from the pinned OpenAPI snapshot.

Do not edit src/arbitr/generated/ by hand. Re-run:

    uv run python scripts/generate_models.py
"""

from __future__ import annotations

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
        "--custom-file-header",
        HEADER,
    ]
    subprocess.run(cmd, check=True)
    subprocess.run(
        [sys.executable, "-m", "ruff", "format", str(OUT)],
        check=True,
    )
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
