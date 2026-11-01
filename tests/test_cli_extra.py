"""The CLI is an optional extra: the library works without Typer, and the
``arbitr`` command says how to install the extra instead of a traceback.
"""

from __future__ import annotations

import subprocess
import sys

_BLOCK_TYPER = (
    "import sys\n"
    "class _NoTyper:\n"
    "    def find_spec(self, name, path=None, target=None):\n"
    "        if name == 'typer' or name.startswith('typer.'):\n"
    "            raise ModuleNotFoundError(\"No module named 'typer'\", name='typer')\n"
    "sys.meta_path.insert(0, _NoTyper())\n"
)


def _run_without_typer(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", _BLOCK_TYPER + code],
        capture_output=True,
        text=True,
        check=False,
    )


def test_library_imports_without_typer() -> None:
    result = _run_without_typer("import arbitr; arbitr.AsyncArbitrClient; arbitr.ArbitrClient")
    assert result.returncode == 0, result.stderr


def test_cli_entrypoint_without_typer_names_the_extra() -> None:
    result = _run_without_typer("from arbitr._cli_entry import entrypoint; entrypoint()")
    assert result.returncode == 1
    assert "pip install 'arbitr-sdk[cli]'" in result.stderr
    assert "Traceback" not in result.stderr
