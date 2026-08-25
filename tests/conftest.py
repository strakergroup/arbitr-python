"""Shared fixtures. Keeps the suite isolated from the developer's environment."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

# Every alias `_credentials.load_client_settings` consults.
ARBITR_ENV_VARS = (
    "ARBITR_API_KEY",
    "arbitr_api_key",
    "ARBITR_BASE_URL",
    "ARBITR_API_DOMAIN",
    "arbitr_api_domain",
    "ARBITR_UI_URL",
    "arbitr_ui_url",
    "ARBITR_MAX_RETRIES",
    "arbitr_max_retries",
)


@pytest.fixture(autouse=True)
def isolate_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[None]:
    """Run each test with no ARBITR_* variables and an empty working directory.

    The CLI defaults ``--env-file`` to ``./.env``, so without this a developer's
    real dotenv — which holds a live API key — would be read during the suite.
    The scratch cwd deliberately sits outside the test's own ``tmp_path`` so
    tests can assert on the exact contents of that directory.
    """
    for name in ARBITR_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))
    yield
