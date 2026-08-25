"""API-key mode and dotenv construction shared by both clients (no network)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arbitr._constants import DEFAULT_BASE_URL
from arbitr._env import pick_env_value, read_env_file
from arbitr._http import derive_ui_url, parse_max_retries
from arbitr.errors import ClientInputError, MissingApiKeyError

CLI_DEFAULT_MAX_RETRIES = 3


def api_key_mode(api_key: str) -> str:
    """Best-effort key mode from the prefix: ``live``, ``test``, or ``unknown``."""
    if "_live_" in api_key:
        return "live"
    if "_test_" in api_key:
        return "test"
    return "unknown"


@dataclass(frozen=True)
class HostSettings:
    """API and UI hosts resolved from env / dotenv / explicit overrides."""

    base_url: str
    ui_base_url: str


@dataclass(frozen=True)
class ClientSettings:
    """Resolved constructor inputs from env / dotenv / explicit overrides."""

    api_key: str
    base_url: str
    ui_base_url: str | None
    extra: dict[str, Any]


def _parse_env_max_retries(raw: str) -> int:
    """Parse ``ARBITR_MAX_RETRIES`` from a dotenv / env string."""
    try:
        value = int(raw.strip())
    except ValueError:
        raise ClientInputError("max_retries must be a non-negative integer") from None
    return parse_max_retries(value)


def load_host_settings(
    env_file: str | Path = ".env",
    *,
    base_url: str | None = None,
    ui_base_url: str | None = None,
) -> HostSettings:
    """Resolve API and UI hosts without requiring an API key."""
    file_vals = read_env_file(env_file)
    url = (
        base_url
        or pick_env_value(
            "ARBITR_BASE_URL",
            "ARBITR_API_DOMAIN",
            "arbitr_api_domain",
            file_vals=file_vals,
        )
        or DEFAULT_BASE_URL
    )
    ui = (
        ui_base_url
        or pick_env_value("ARBITR_UI_URL", "arbitr_ui_url", file_vals=file_vals)
        or derive_ui_url(url)
    )
    return HostSettings(base_url=url.rstrip("/"), ui_base_url=ui.rstrip("/"))


def resolve_cli_max_retries(
    env_file: str | Path,
    *,
    max_retries: int | None,
) -> int:
    """CLI retry count: flag, then env, then ``CLI_DEFAULT_MAX_RETRIES``."""
    if max_retries is not None:
        return parse_max_retries(max_retries)
    file_vals = read_env_file(env_file)
    raw = pick_env_value("ARBITR_MAX_RETRIES", "arbitr_max_retries", file_vals=file_vals)
    if raw is not None:
        return _parse_env_max_retries(raw)
    return CLI_DEFAULT_MAX_RETRIES


def load_client_settings(
    env_file: str | Path = ".env",
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    **kwargs: Any,
) -> ClientSettings:
    """Resolve API key, base URL, and UI URL for client construction.

    Raises:
        MissingApiKeyError: If no key is in the arguments, environment, or dotenv file.
    """
    file_vals = read_env_file(env_file)
    host = load_host_settings(
        env_file,
        base_url=base_url,
        ui_base_url=kwargs.pop("ui_base_url", None),
    )
    key = api_key or pick_env_value("ARBITR_API_KEY", "arbitr_api_key", file_vals=file_vals)
    if "max_retries" not in kwargs:
        raw = pick_env_value("ARBITR_MAX_RETRIES", "arbitr_max_retries", file_vals=file_vals)
        if raw is not None:
            kwargs["max_retries"] = _parse_env_max_retries(raw)
    if not key:
        raise MissingApiKeyError(
            "No API key found. Set ARBITR_API_KEY in the environment or "
            "arbitr_api_key in the env file. Mint a key at "
            "https://arbitr.straker.ai/settings/api-keys"
        )
    return ClientSettings(
        api_key=key,
        base_url=host.base_url,
        ui_base_url=host.ui_base_url,
        extra=kwargs,
    )
