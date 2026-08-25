"""Upload allowlist, size limits, and multipart file coercion (no network)."""

from __future__ import annotations

import mimetypes
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

from arbitr import _constants as constants
from arbitr._constants import (
    ALLOWED_UPLOAD_EXTENSIONS,
    MAX_UPLOAD_FILES,
    SUPPORTED_FORMATS,
    ExtensionCheck,
)
from arbitr.errors import ClientInputError, DisallowedFileExtensionError

FileInput = str | Path | tuple[str, bytes] | tuple[str, bytes, str] | BinaryIO


def parse_extension_check(value: str) -> ExtensionCheck:
    """Parse ``extension_check`` from untyped input."""
    if value == "allowlist" or value == "off":
        return value
    raise ClientInputError("extension_check must be 'allowlist' or 'off'")


def require_submit_files(files: list[FileInput]) -> None:
    """Raise if the submit file list is empty or longer than the API max."""
    if not files:
        raise ClientInputError("at least one file is required")
    if len(files) > MAX_UPLOAD_FILES:
        raise ClientInputError(f"too many files; max is {MAX_UPLOAD_FILES}")


@contextmanager
def open_upload_parts(
    files: list[FileInput], extension_check: ExtensionCheck
) -> Iterator[list[tuple[str, tuple[str, Any, str]]]]:
    """Yield httpx multipart ``file`` parts; close any paths this helper opened."""
    opened: list[BinaryIO] = []
    try:
        yield [("file", coerce_upload_file(item, opened, extension_check)) for item in files]
    finally:
        for handle in opened:
            handle.close()


def require_binary_upload_handle(file_input: object) -> None:
    """Raise if ``file_input`` is a text-mode handle httpx would reject."""
    mode = getattr(file_input, "mode", None)
    if isinstance(mode, str) and "b" not in mode:
        raise ClientInputError("file handles must be opened in binary mode")


def reject_disallowed_upload_extension(filename: str, extension_check: ExtensionCheck) -> None:
    """Raise if ``filename`` is not on the API upload allowlist."""
    if extension_check != "allowlist":
        return
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise DisallowedFileExtensionError(
            filename,
            extension,
            supported_formats=SUPPORTED_FORMATS,
        )


def upload_byte_size(file_input: FileInput) -> int:
    """Byte length of one upload input."""
    if isinstance(file_input, (str, Path)):
        path = Path(file_input)
        try:
            return path.stat().st_size
        except OSError as exc:
            raise ClientInputError(f"cannot read upload {path}: {exc}") from exc
    if isinstance(file_input, tuple):
        if len(file_input) < 2 or not isinstance(file_input[1], bytes):
            raise ClientInputError("file tuples must be (filename, bytes[, content_type])")
        return len(file_input[1])
    if hasattr(file_input, "read"):
        handle = file_input
        require_binary_upload_handle(handle)
        if not hasattr(handle, "seek") or not hasattr(handle, "tell"):
            raise ClientInputError("cannot determine upload size for this file input")
        position = handle.tell()
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        handle.seek(position)
        return size
    raise ClientInputError(f"unsupported file input: {type(file_input).__name__}")


def upload_file_name(file_input: object) -> str:
    """Best-effort filename for a file object; unnamed handles become ``upload.bin``."""
    raw = getattr(file_input, "name", "upload.bin")
    if isinstance(raw, (str, os.PathLike)):
        name = Path(raw).name
        if name:
            return name
    return "upload.bin"


def ensure_upload_within_limit(file_inputs: list[FileInput]) -> None:
    """Raise if the combined upload exceeds ``MAX_UPLOAD_TOTAL_BYTES``."""
    total = sum(upload_byte_size(item) for item in file_inputs)
    limit = constants.MAX_UPLOAD_TOTAL_BYTES
    if total > limit:
        raise ClientInputError(
            f"upload too large: {total} bytes; max is {limit} bytes (MAX_UPLOAD_TOTAL_BYTES)"
        )


def _read_part_content(content: Any) -> bytes:
    """Bytes of an httpx file part; restores the handle position when possible."""
    if isinstance(content, bytes):
        return content
    if hasattr(content, "tell") and hasattr(content, "seek"):
        position = content.tell()
        try:
            content.seek(0)
            data = content.read()
        finally:
            content.seek(position)
    else:
        data = content.read()
    if not isinstance(data, bytes):
        raise ClientInputError("file handles must be opened in binary mode")
    return data


def load_upload_parts(
    files: list[FileInput], extension_check: ExtensionCheck
) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Read every upload into memory so async submit does no filesystem I/O on the event loop."""
    ensure_upload_within_limit(files)
    with open_upload_parts(files, extension_check) as parts:
        return [
            (field, (name, _read_part_content(content), content_type))
            for field, (name, content, content_type) in parts
        ]


def coerce_upload_file(
    file_input: FileInput, opened: list[BinaryIO], extension_check: ExtensionCheck
) -> tuple[str, Any, str]:
    """Normalise a FileInput to httpx's (filename, content, content_type)."""
    extension_check = parse_extension_check(extension_check)
    if isinstance(file_input, (str, Path)):
        path = Path(file_input)
        reject_disallowed_upload_extension(path.name, extension_check)
        try:
            handle = path.open("rb")
        except OSError as exc:
            raise ClientInputError(f"cannot read upload {path}: {exc}") from exc
        opened.append(handle)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return (path.name, handle, content_type)
    if isinstance(file_input, tuple):
        match file_input:
            case (str() as name, bytes() as content):
                reject_disallowed_upload_extension(name, extension_check)
                return (name, content, "application/octet-stream")
            case (str() as name, bytes() as content, str() as content_type):
                reject_disallowed_upload_extension(name, extension_check)
                return (name, content, content_type)
            case _:
                raise ClientInputError("file tuples must be (filename, bytes[, content_type])")
    if hasattr(file_input, "read"):
        require_binary_upload_handle(file_input)
        name = upload_file_name(file_input)
        reject_disallowed_upload_extension(name, extension_check)
        return (name, file_input, "application/octet-stream")
    raise ClientInputError(f"unsupported file input: {type(file_input).__name__}")
