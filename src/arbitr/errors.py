"""Error types mapped from the Arbitr API error envelope.

The API returns ``{"error": {"code", "message", "request_id"}}`` on failure,
with extra keys on some codes. ``from_response`` picks the most specific
subclass.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, ClassVar

import httpx
from pydantic import ValidationError as PydanticValidationError

if TYPE_CHECKING:
    from arbitr.generated.models import ProjectResponse


class ArbitrBaseError(Exception):
    """Root of every error this package raises.

    Catch this to handle anything the client can fail with, including
    transport failures, without also catching unrelated bugs.
    """


class ArbitrError(ArbitrBaseError):
    """A non-2xx response from the Arbitr API."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        request_id: str | None = None,
        field_errors: list[dict[str, Any]] | None = None,
        retry_after: float | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"[{status_code}] {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.request_id = request_id
        self.field_errors = field_errors or []
        self.retry_after = retry_after
        self.extra = extra or {}

    @property
    def supported_formats(self) -> list[str] | None:
        """Accepted extensions on unsupported-upload 422s; otherwise None."""
        raw = self.extra.get("supported_formats")
        if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
            return raw
        return None

    def _numeric_extra(self, key: str) -> float | None:
        raw = self.extra.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        return float(raw)


class AuthenticationError(ArbitrError):
    """401/403 — missing, bad, or under-scoped API key."""

    @property
    def required_scope(self) -> str | None:
        """Scope the key is missing, on ``insufficient_scope``; otherwise None."""
        raw = self.extra.get("required_scope")
        return raw if isinstance(raw, str) else None


class PaymentRequiredError(ArbitrError):
    """402 — not enough credits to proceed.

    Raised when a resumption is attempted while the balance is still short.
    Top up, then retry ``projects.resume()`` / ``projects.resume_human_review()``.
    """

    @property
    def required(self) -> float | None:
        """Credits needed to proceed, when the API reported it."""
        return self._numeric_extra("required")

    @property
    def available(self) -> float | None:
        """Credits currently available, when the API reported it."""
        return self._numeric_extra("available")

    @property
    def shortfall(self) -> float | None:
        """Credits still needed, when the API reported it."""
        return self._numeric_extra("shortfall")


class NotFoundError(ArbitrError):
    """404 — resource does not exist (or is not visible to this key)."""


class GoneError(ArbitrError):
    """410 — the route passed its sunset date; move to its replacement."""


class ConflictError(ArbitrError):
    """409 — e.g. Idempotency-Key reused with a different body."""


class ValidationError(ArbitrError):
    """422 — request failed validation; inspect ``field_errors``."""


class RateLimitError(ArbitrError):
    """429 — rate limit exceeded; honour ``retry_after`` seconds."""


class ServerError(ArbitrError):
    """5xx — server-side failure; safe to retry with backoff."""


class ArbitrClientError(ArbitrBaseError):
    """Failure raised by this client before or instead of an HTTP error envelope."""


class TransportError(ArbitrClientError):
    """The request never produced an HTTP response.

    Wraps the underlying ``httpx`` failure so callers never need to import
    ``httpx`` to write correct error handling. The original exception stays
    available as ``__cause__``.
    """

    def __init__(self, message: str, *, method: str, url: str) -> None:
        super().__init__(f"{method} {url}: {message}")
        self.method = method
        self.url = url


class ConnectionFailedError(TransportError):
    """The host could not be reached (DNS, refused connection, TLS)."""


class RequestTimeoutError(TransportError, TimeoutError):
    """The request timed out before a response arrived."""


class ClientInputError(ArbitrClientError):
    """Client-side input problem raised before any HTTP request."""


class MissingApiKeyError(ClientInputError):
    """No API key was supplied or found in the environment / dotenv file."""


class DisallowedFileExtensionError(ClientInputError):
    """An upload file's extension is not on the API allowlist."""

    def __init__(
        self,
        filename: str,
        extension: str,
        *,
        supported_formats: list[str] | None = None,
    ) -> None:
        self.filename = filename
        self.extension = extension
        self.supported_formats = list(supported_formats or [])
        extra = ""
        if self.supported_formats:
            extra = f"; supported_formats: {', '.join(self.supported_formats)}"
        super().__init__(f"{filename}: extension {extension!r} is not on the API allowlist{extra}")


class UnknownLocaleCodesError(ClientInputError):
    """Locale codes that GET /v1/languages does not know."""

    def __init__(self, codes: list[str]) -> None:
        super().__init__(
            f"unknown locale_codes: {', '.join(codes)} — see GET /v1/languages for supported codes"
        )
        self.codes = codes


class AmbiguousLocaleCodesError(ClientInputError):
    """A language prefix matches more than one BCP-47 tag."""

    def __init__(self, code: str, matches: list[str]) -> None:
        self.code = code
        self.matches = list(matches)
        super().__init__(
            f"ambiguous locale_code {code!r} matches {', '.join(self.matches)}; "
            "use a full BCP-47 tag"
        )


class ProjectWaitTimeoutError(ArbitrClientError, TimeoutError):
    """``projects.wait()`` exceeded its timeout before a terminal status."""

    def __init__(self, project_id: str, status: str | None, timeout: float) -> None:
        super().__init__(f"project {project_id} still {status!r} after {timeout:.0f}s")
        self.project_id = project_id
        self.status = status
        self.timeout = timeout


class FindingsKeysetError(ArbitrClientError):
    """GET .../findings reported another page but ``page.after`` did not advance."""

    def __init__(self, *, after: str | None, previous: str | None) -> None:
        super().__init__(
            "listProjectFindings: page.has_more is true but page.after "
            f"did not advance (after={after!r}, previous={previous!r})"
        )
        self.after = after
        self.previous = previous


class ResponseParseError(ArbitrClientError):
    """A 2xx JSON body did not match the published response schema."""

    def __init__(self, operation: str, cause: PydanticValidationError) -> None:
        self.operation = operation
        self.errors = cause.errors()
        super().__init__(
            f"{operation}: response did not match the published schema "
            f"({cause.error_count()} error(s))"
        )


class ResponseDecodeError(ArbitrClientError):
    """A 2xx body could not be parsed as JSON."""

    def __init__(self, operation: str, cause: json.JSONDecodeError | UnicodeDecodeError) -> None:
        self.operation = operation
        super().__init__(f"{operation}: response was not valid JSON ({cause})")


class BareLocaleCodeError(ClientInputError):
    """A locale was a bare language code rather than a full BCP-47 tag."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"{code!r} is a bare language code, not a full BCP-47 tag "
            "(e.g. ja-jp, es-419). Expand it with languages.resolve() "
            "or pass a region-specific tag."
        )


class ActionRequiredError(ArbitrClientError):
    """The project parked at a gate that requires a human action.

    Not an HTTP error — raised by ``wait()`` when the project's status enters
    an action-required state the external API cannot release.
    """

    _GUIDANCE: ClassVar[dict[str, str]] = {
        "agent_selection": (
            "the project is waiting for a human to confirm the agent selection "
            "(the 'Start Campaign' button) in the Arbitr UI — the external API "
            "cannot release this gate. Open the project's /agents page, click "
            "Start Campaign, then wait again. (New projects skip the gate "
            'entirely when submitted with workflow=["AI_TRANSLATION"].)'
        ),
        "awaiting_payment": (
            "insufficient credits — top up in the Arbitr UI, then call "
            "projects.resume() or `arbitr resume <id>`. Check the balance "
            "with `arbitr credits`."
        ),
    }

    def __init__(self, project: ProjectResponse, *, ui_url: str | None = None) -> None:
        self.project = project
        self.status = project.status
        self.project_id = project.id
        self.ui_url = ui_url
        guidance = self._GUIDANCE.get(
            self.status,
            "complete the required action in the Arbitr UI, then wait again.",
        )
        msg = f"project {self.project_id} is parked at {self.status!r}: {guidance}"
        if ui_url:
            msg += f" Open: {ui_url}"
        super().__init__(msg)


_STATUS_MAP: dict[int, type[ArbitrError]] = {
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: AuthenticationError,
    404: NotFoundError,
    409: ConflictError,
    410: GoneError,
    422: ValidationError,
    429: RateLimitError,
}

_ENVELOPE_META_KEYS = frozenset({"code", "message", "request_id", "field_errors"})


def _parse_error_envelope(resp: httpx.Response) -> dict[str, Any]:
    """Extract the API's ``{"error": {...}}`` envelope; ``{}`` when absent."""
    try:
        body = resp.json()
    except ValueError:
        return {}
    envelope = body.get("error") if isinstance(body, dict) else None
    return envelope if isinstance(envelope, dict) else {}


def from_response(resp: httpx.Response) -> ArbitrError:
    """Build the most specific ArbitrError from an error response."""
    envelope = _parse_error_envelope(resp)
    code = envelope.get("code") or "http_error"
    message = envelope.get("message") or (resp.text[:500] if resp.text else resp.reason_phrase)
    field_errors = envelope.get("field_errors")

    retry_after: float | None = None
    if resp.status_code == 429:
        try:
            retry_after = float(resp.headers.get("retry-after", "1"))
        except ValueError:
            retry_after = 1.0

    cls = _STATUS_MAP.get(resp.status_code)
    if cls is None:
        cls = ServerError if resp.status_code >= 500 else ArbitrError
    return cls(
        resp.status_code,
        str(code),
        str(message),
        request_id=envelope.get("request_id"),
        field_errors=field_errors if isinstance(field_errors, list) else None,
        retry_after=retry_after,
        extra={k: v for k, v in envelope.items() if k not in _ENVELOPE_META_KEYS},
    )


def from_transport_error(exc: httpx.HTTPError) -> TransportError:
    """Translate an httpx transport failure into this package's error tree."""
    request = getattr(exc, "request", None)
    method = request.method if request is not None else "?"
    url = str(request.url) if request is not None else "?"
    message = str(exc) or type(exc).__name__
    cls: type[TransportError]
    if isinstance(exc, httpx.TimeoutException):
        cls = RequestTimeoutError
    elif isinstance(exc, httpx.TransportError):
        cls = ConnectionFailedError
    else:
        cls = TransportError
    return cls(message, method=method, url=url)
