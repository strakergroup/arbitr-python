"""Constants shared by the sync and async clients (no I/O)."""

from __future__ import annotations

from typing import Literal

DEFAULT_BASE_URL = "https://api-arbitr.straker.ai"

TERMINAL_STATUSES = frozenset({"cancelled", "completed", "published", "failed"})
ACTION_REQUIRED_STATUSES = frozenset({"agent_selection", "awaiting_payment"})
AGENT_SELECTION_CONFIRM_POLLS = 2

# Leading-byte-checked upload allowlist from the published OpenAPI snapshot.
ALLOWED_UPLOAD_EXTENSIONS = frozenset(
    {
        ".csv",
        ".dita",
        ".ditamap",
        ".docx",
        ".htm",
        ".html",
        ".idml",
        ".json",
        ".markdown",
        ".md",
        ".pdf",
        ".po",
        ".pptx",
        ".properties",
        ".srt",
        ".strings",
        ".ts",
        ".txt",
        ".vtt",
        ".xlf",
        ".xliff",
        ".xlsx",
        ".xml",
    }
)
SUPPORTED_FORMATS: list[str] = sorted(ALLOWED_UPLOAD_EXTENSIONS)

MAX_UPLOAD_FILES = 100
MAX_UPLOAD_TOTAL_BYTES = 200 * 1024 * 1024

DEFAULT_WORKFLOW = ("AI_TRANSLATION",)
DEFAULT_SOURCE_LANGUAGE = "en-us"

# Retries are opt-in via ``max_retries``. 429 carries Retry-After; the 5xx
# codes back off exponentially. Other statuses are never retried. Only GET
# is replayed — POST /v1/projects streams file handles that cannot be
# rewound, so callers retry it themselves with ``idempotency_key``.
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
RETRY_BACKOFF_BASE_SECONDS = 0.5
RETRY_BACKOFF_MAX_SECONDS = 60.0

OnActionRequired = Literal["raise", "wait"]
ExtensionCheck = Literal["allowlist", "off"]
