"""Everything in this package is published as-is to a public repo and to PyPI,
so no tracked file may name a machine path, and uv.lock resolves only from PyPI.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

_FORBIDDEN = re.compile(r"/home/[a-z]|/Users/[A-Za-z]")
_LOCK_SOURCE = re.compile(r'^source = \{ (?:registry|git|url) = "([^"]+)"')
_LOCK_REGISTRY = "https://pypi.org/"


def _published_files() -> list[Path]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "."],  # noqa: S607
            cwd=_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout to list the published files")
    return [_ROOT / name for name in listed if name != "uv.lock"]


def test_no_internal_references_in_published_files() -> None:
    hits = []
    for path in _published_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if _FORBIDDEN.search(line):
                hits.append(f"{path.relative_to(_ROOT)}:{number}: {line.strip()}")
    assert not hits, "internal references in the public SDK:\n" + "\n".join(hits)


def test_uv_lock_resolves_only_from_pypi() -> None:
    lock = (_ROOT / "uv.lock").read_text(encoding="utf-8")
    hits = [
        f"uv.lock:{number}: {source.group(1)}"
        for number, line in enumerate(lock.splitlines(), 1)
        if (source := _LOCK_SOURCE.search(line)) and not source.group(1).startswith(_LOCK_REGISTRY)
    ]
    assert not hits, "uv.lock resolves from outside PyPI:\n" + "\n".join(hits)
