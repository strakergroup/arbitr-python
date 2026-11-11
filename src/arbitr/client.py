"""Synchronous client for the Arbitr External API."""

from __future__ import annotations

import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx2
from pydantic import SecretStr

from arbitr import errors as err
from arbitr._constants import (
    DEFAULT_BASE_URL,
    DEFAULT_SOURCE_LANGUAGE,
    ExtensionCheck,
    OnActionRequired,
)
from arbitr._credentials import api_key_mode, load_client_settings
from arbitr._files import (
    FileInput,
    ensure_upload_within_limit,
    open_upload_parts,
    parse_extension_check,
    require_submit_files,
)
from arbitr._http import (
    default_headers,
    derive_ui_url,
    is_retryable_method,
    parse_max_retries,
    path_segment,
    project_ui_url,
    raise_for_status,
    rate_limit_snapshot,
    request_timeout,
    retry_wait_seconds,
    transport_retry_delay,
    write_download_file,
)
from arbitr._locales import filter_language_list, language_bcp47_set, resolve_locale_codes
from arbitr._parse import decode_json_body, parse_response
from arbitr._projects import (
    ProjectResumptionResponse,
    confirmation_body,
    findings_list_params,
    idempotency_headers,
    next_findings_after,
    project_list_params,
    project_submit_form,
    quote_adjustment_body,
)
from arbitr._text import text_translate_body, usage_list_params
from arbitr._version import __version__ as _version
from arbitr._wait import decide_project_wait, parse_on_action_required
from arbitr._webhook_requests import (
    WEBHOOKS_PATH,
    WebhookTestBody,
    webhook_create_body,
    webhook_deliveries_params,
    webhook_path,
    webhook_update_body,
)
from arbitr.generated.models import (
    AgentFinding,
    ChainOfCustodyResponse,
    ConnectionResponse,
    CreditBalanceResponse,
    DeliverableListResponse,
    FindingListResponse,
    FindingSeverity,
    FindingStatus,
    FlagFinding,
    HumanReviewResponse,
    LanguageListResponse,
    MeResponse,
    ProjectDeliverableResponse,
    ProjectListResponse,
    ProjectResponse,
    QuotePair,
    QuoteResponse,
    Requester,
    TextFormat,
    TextToTranslate,
    TextTranslateResponse,
    TextUsageType,
    UnknownFinding,
    UsageListResponse,
    WebhookCreateResponse,
    WebhookDelivery,
    WebhookDeliveryListResponse,
    WebhookDeliveryStatus,
    WebhookListResponse,
    WebhookResponse,
    WebhookStatus,
)

__all__ = ["ArbitrClient", "new_idempotency_key"]


def new_idempotency_key() -> str:
    """Return a fresh UUID4 suitable as an Idempotency-Key header value."""
    return str(uuid4())


class ArbitrClient:
    """Synchronous client for one API key and one host."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_version: str = "1",
        timeout: float | httpx2.Timeout = 60.0,
        transport: httpx2.BaseTransport | None = None,
        ui_base_url: str | None = None,
        max_retries: int = 0,
        user_agent: str | None = None,
    ) -> None:
        if not api_key:
            raise err.MissingApiKeyError("api_key is required")
        if transport is not None and not isinstance(transport, httpx2.BaseTransport):
            raise err.ClientInputError(
                f"transport must be an httpx2.BaseTransport, not {type(transport).__module__}."
                f"{type(transport).__qualname__}"
            )
        self._api_key = SecretStr(api_key)
        self.base_url = base_url.rstrip("/")
        self.ui_base_url = (ui_base_url or derive_ui_url(self.base_url)).rstrip("/")
        self.max_retries = parse_max_retries(max_retries)
        self.rate_limit: dict[str, str] = {}
        self._http = httpx2.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers=default_headers(api_key, api_version, user_agent),
            # httpx2 keeps X-API-Key on a cross-host redirect; a moved API is an
            # ApiMovedError for the caller to fix, never a forwarded key.
            follow_redirects=False,
        )
        self.projects = ProjectsAPI(self)
        self.languages = LanguagesAPI(self)
        self.credits = CreditsAPI(self)
        self.text = TextAPI(self)
        self.usage = UsageAPI(self)
        self.webhooks = WebhooksAPI(self)

    @property
    def api_key(self) -> str:
        """The API key passed at construction. Never log this value."""
        return self._api_key.get_secret_value()

    @property
    def key_mode(self) -> str:
        """Best-effort key mode from the prefix: ``live``, ``test``, or ``unknown``."""
        return api_key_mode(self.api_key)

    @property
    def is_closed(self) -> bool:
        """Whether the underlying connection pool has been released."""
        return self._http.is_closed

    def me(self, *, timeout: float | httpx2.Timeout | None = None) -> MeResponse:
        """Introspect the authenticated key (GET /v1/me)."""
        return parse_response(
            MeResponse,
            self.get_json("/v1/me", timeout=request_timeout(timeout)),
            operation="getCurrentKey",
        )

    def connection(self, *, timeout: float | httpx2.Timeout | None = None) -> ConnectionResponse:
        """The chat-app connection this key belongs to (GET /v1/connection)."""
        return parse_response(
            ConnectionResponse,
            self.get_json("/v1/connection", timeout=request_timeout(timeout)),
            operation="getConnection",
        )

    @classmethod
    def from_env(
        cls,
        env_file: str | Path = ".env",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> ArbitrClient:
        """Build a client from environment variables and/or a dotenv file."""
        settings = load_client_settings(env_file, api_key=api_key, base_url=base_url, **kwargs)
        return cls(
            api_key=settings.api_key,
            base_url=settings.base_url,
            ui_base_url=settings.ui_base_url,
            **settings.extra,
        )

    def project_url(
        self, project_id: str, *, view: Literal["project", "agents"] = "project"
    ) -> str:
        """Deep link to the project in the Arbitr UI."""
        return project_ui_url(self.ui_base_url, project_id, view=view)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx2.Response:
        """Send an authenticated request; raise on non-2xx or transport failure.

        Retries retryable statuses up to ``max_retries`` times when the method
        is safe to replay, honouring ``Retry-After`` on 429.
        """
        retries = self.max_retries if is_retryable_method(method) else 0
        for attempt in range(retries + 1):
            try:
                resp = self._http.request(method, path, **kwargs)
            except httpx2.HTTPError as exc:
                if attempt >= retries:
                    raise err.from_transport_error(exc) from exc
                time.sleep(transport_retry_delay(attempt))
                continue
            self.rate_limit = rate_limit_snapshot(resp) or self.rate_limit
            delay = retry_wait_seconds(resp, attempt=attempt, retries=retries)
            if delay is not None:
                resp.close()
                time.sleep(delay)
                continue
            raise_for_status(resp)
            return resp
        raise AssertionError("unreachable: retry loop always returns or raises")

    def get_json(self, path: str, **kwargs: Any) -> Any:
        """GET ``path`` and return the parsed JSON body (None when empty)."""
        resp = self.request("GET", path, **kwargs)
        return decode_json_body(resp, operation=path)

    def close(self) -> None:
        """Close the underlying httpx2 client."""
        self._http.close()

    def __enter__(self) -> ArbitrClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ArbitrClient(base_url={self.base_url!r}, version={_version!r})"


class ProjectsAPI:
    """Project lifecycle: submit, list/poll, findings, chain of custody, deliverables."""

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def submit(
        self,
        *,
        files: list[FileInput],
        name: str,
        target_language_codes: list[str],
        source_language_code: str = DEFAULT_SOURCE_LANGUAGE,
        workflow: list[str] | None = None,
        due_date: str | None = None,
        requester: Requester | None = None,
        hold_for_quote: bool = False,
        archive_on_completion: bool = False,
        notes: str | None = None,
        reference: str | None = None,
        idempotency_key: str | None = None,
        extension_check: ExtensionCheck = "allowlist",
        timeout: float | httpx2.Timeout | None = None,
    ) -> ProjectResponse:
        """Create a translation project (POST /v1/projects).

        ``requester``: your ids (tenant, external) for the person the work is for.
        ``hold_for_quote``: hold the project for a quote until you confirm it.
        ``archive_on_completion``: archive the project once it completes.
        ``notes``: free-text note stored with the project (255 characters at most).
        ``reference``: your own id for the project (1-128 characters). Creating
        again with a reference already in use returns that project and creates
        nothing; test keys don't deduplicate.
        """
        require_submit_files(files)
        extension_check = parse_extension_check(extension_check)
        ensure_upload_within_limit(files)
        with open_upload_parts(files, extension_check) as parts:
            resp = self._c.request(
                "POST",
                "/v1/projects",
                data=project_submit_form(
                    name=name,
                    target_language_codes=target_language_codes,
                    source_language_code=source_language_code,
                    workflow=workflow,
                    due_date=due_date,
                    requester=requester,
                    hold_for_quote=hold_for_quote,
                    archive_on_completion=archive_on_completion,
                    notes=notes,
                    reference=reference,
                ),
                files=parts,
                headers=idempotency_headers(idempotency_key),
                timeout=request_timeout(timeout),
            )
        return parse_response(
            ProjectResponse,
            decode_json_body(resp, operation="createProject"),
            operation="createProject",
        )

    def list(
        self,
        *,
        limit: int = 50,
        page: int = 1,
        modified_after: str | None = None,
        status: str | None = None,
        requester_tenant_id: str | None = None,
        requester_external_id: str | None = None,
        q: str | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> ProjectListResponse:
        """One page of projects (GET /v1/projects).

        ``requester_tenant_id`` and ``requester_external_id`` go together and
        keep projects created for that requester. ``q`` matches a name or id.
        """
        return parse_response(
            ProjectListResponse,
            self._c.get_json(
                "/v1/projects",
                params=project_list_params(
                    limit=limit,
                    page=page,
                    modified_after=modified_after,
                    status=status,
                    requester_tenant_id=requester_tenant_id,
                    requester_external_id=requester_external_id,
                    q=q,
                ),
                timeout=request_timeout(timeout),
            ),
            operation="listProjects",
        )

    def iterate(
        self,
        *,
        limit: int = 50,
        page: int = 1,
        modified_after: str | None = None,
        status: str | None = None,
        requester_tenant_id: str | None = None,
        requester_external_id: str | None = None,
        q: str | None = None,
    ) -> Iterator[ProjectResponse]:
        """Yield every project, following page-number pagination.

        Pass ``page`` to resume from a page other than the first.
        """
        page_number = page
        while True:
            body = self.list(
                limit=limit,
                page=page_number,
                modified_after=modified_after,
                status=status,
                requester_tenant_id=requester_tenant_id,
                requester_external_id=requester_external_id,
                q=q,
            )
            yield from body.projects
            if not body.page.has_more:
                return
            page_number += 1

    def get(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> ProjectResponse:
        """Poll status/progress (GET /v1/projects/{id})."""
        return parse_response(
            ProjectResponse,
            self._c.get_json(
                f"/v1/projects/{path_segment(project_id)}", timeout=request_timeout(timeout)
            ),
            operation="getProject",
        )

    def wait(
        self,
        project_id: str,
        *,
        timeout: float = 900.0,
        poll_interval: float = 5.0,
        on_action_required: OnActionRequired = "raise",
    ) -> ProjectResponse:
        """Poll until the project reaches a terminal status."""
        on_action_required = parse_on_action_required(on_action_required)
        deadline = time.monotonic() + timeout
        streak = 0
        while True:
            project = self.get(project_id)
            decision = decide_project_wait(
                project,
                agent_selection_streak=streak,
                on_action_required=on_action_required,
            )
            streak = decision.agent_selection_streak
            if decision.kind == "terminal":
                return project
            if decision.kind == "parked":
                raise err.ActionRequiredError(
                    project,
                    ui_url=self._c.project_url(
                        project_id,
                        view="agents" if decision.status == "agent_selection" else "project",
                    ),
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise err.ProjectWaitTimeoutError(project_id, decision.status, timeout)
            time.sleep(min(poll_interval, remaining))

    def findings(
        self,
        project_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        severity: FindingSeverity | str | None = None,
        category: str | None = None,
        status: FindingStatus | str | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> FindingListResponse:
        """One page of segment flags and agent findings (GET …/findings).

        Walk ``page.after`` as ``after=`` until ``page.has_more`` is false.
        ``severity``, ``category``, and ``status`` filter flags only.
        """
        return parse_response(
            FindingListResponse,
            self._c.get_json(
                f"/v1/projects/{path_segment(project_id)}/findings",
                params=findings_list_params(
                    limit=limit,
                    after=after,
                    severity=severity,
                    category=category,
                    status=status,
                ),
                timeout=request_timeout(timeout),
            ),
            operation="listProjectFindings",
        )

    def iterate_findings(
        self,
        project_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        severity: FindingSeverity | str | None = None,
        category: str | None = None,
        status: FindingStatus | str | None = None,
    ) -> Iterator[FlagFinding | AgentFinding | UnknownFinding]:
        """Yield every finding, following ``page.after`` keyset pagination.

        Pass ``after`` to resume from a previous page's seek token.
        """
        while True:
            body = self.findings(
                project_id,
                limit=limit,
                after=after,
                severity=severity,
                category=category,
                status=status,
            )
            yield from body.findings
            after = next_findings_after(
                has_more=body.page.has_more,
                after=body.page.after,
                previous=after,
            )
            if after is None:
                return

    def chain_of_custody(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> ChainOfCustodyResponse:
        """Provenance record for a project (GET …/chain-of-custody)."""
        return parse_response(
            ChainOfCustodyResponse,
            self._c.get_json(
                f"/v1/projects/{path_segment(project_id)}/chain-of-custody",
                timeout=request_timeout(timeout),
            ),
            operation="getProjectChainOfCustody",
        )

    def deliverables(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> DeliverableListResponse:
        """List deliverable files (GET /v1/projects/{id}/deliverables)."""
        return parse_response(
            DeliverableListResponse,
            self._c.get_json(
                f"/v1/projects/{path_segment(project_id)}/deliverables",
                timeout=request_timeout(timeout),
            ),
            operation="listDeliverables",
        )

    def deliverable(
        self, project_id: str, deliverable_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> ProjectDeliverableResponse:
        """Get one deliverable's metadata (GET …/deliverables/{id})."""
        return parse_response(
            ProjectDeliverableResponse,
            self._c.get_json(
                f"/v1/projects/{path_segment(project_id)}/deliverables/{path_segment(deliverable_id)}",
                timeout=request_timeout(timeout),
            ),
            operation="getDeliverable",
        )

    def download_zip(
        self, project_id: str, dest: str | Path, *, timeout: float | httpx2.Timeout | None = None
    ) -> Path:
        """Download all deliverables as one ZIP (``?format=zip``)."""
        return _stream_download(
            self._c,
            f"/v1/projects/{path_segment(project_id)}/deliverables",
            Path(dest),
            params={"format": "zip"},
            timeout=timeout,
        )

    def download_deliverable(
        self,
        project_id: str,
        deliverable_id: str,
        dest: str | Path,
        *,
        timeout: float | httpx2.Timeout | None = None,
    ) -> Path:
        """Download one deliverable file as bytes."""
        return _stream_download(
            self._c,
            f"/v1/projects/{path_segment(project_id)}/deliverables/{path_segment(deliverable_id)}",
            Path(dest),
            headers={"Accept": "application/octet-stream"},
            timeout=timeout,
        )

    def resume(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> ProjectResumptionResponse:
        """Resume a project parked at ``awaiting_payment`` after a credit top-up."""
        resp = self._c.request(
            "POST",
            f"/v1/projects/{path_segment(project_id)}/resumptions",
            timeout=request_timeout(timeout),
        )
        return parse_response(
            ProjectResumptionResponse,
            decode_json_body(resp, operation="createProjectResumption"),
            operation="createProjectResumption",
        )

    def quote(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> QuoteResponse:
        """Fetch the price quote for a held project (GET /v1/projects/{id}/quote)."""
        resp = self._c.request(
            "GET",
            f"/v1/projects/{path_segment(project_id)}/quote",
            timeout=request_timeout(timeout),
        )
        return parse_response(
            QuoteResponse,
            decode_json_body(resp, operation="getProjectQuote"),
            operation="getProjectQuote",
        )

    def adjust_quote(
        self,
        project_id: str,
        *,
        quote_version: int,
        remove: list[QuotePair],
        timeout: float | httpx2.Timeout | None = None,
    ) -> QuoteResponse:
        """Drop file/language pairs from a quote and re-price it.

        Pairs are matched by the server; ``target_language_code`` is sent as given.
        """
        resp = self._c.request(
            "POST",
            f"/v1/projects/{path_segment(project_id)}/quote/adjustments",
            json=quote_adjustment_body(quote_version=quote_version, remove=remove),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            QuoteResponse,
            decode_json_body(resp, operation="createQuoteAdjustment"),
            operation="createQuoteAdjustment",
        )

    def confirm(
        self,
        project_id: str,
        *,
        quote_version: int | None = None,
        requester: Requester | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> QuoteResponse:
        """Confirm a held project's quote so the work starts.

        Pass ``quote_version`` to refuse a quote that changed since you reviewed it.
        """
        resp = self._c.request(
            "POST",
            f"/v1/projects/{path_segment(project_id)}/confirmations",
            json=confirmation_body(quote_version=quote_version, requester=requester),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            QuoteResponse,
            decode_json_body(resp, operation="createProjectConfirmation"),
            operation="createProjectConfirmation",
        )

    def resume_human_review(
        self, project_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> HumanReviewResponse:
        """Re-attempt a trust-credit-parked human-review send after a TC top-up."""
        resp = self._c.request(
            "POST",
            f"/v1/projects/{path_segment(project_id)}/review/resumptions",
            timeout=request_timeout(timeout),
        )
        return parse_response(
            HumanReviewResponse,
            decode_json_body(resp, operation="createReviewResumption"),
            operation="createReviewResumption",
        )


def _stream_download(
    client: ArbitrClient,
    path: str,
    dest: Path,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | httpx2.Timeout | None = None,
) -> Path:
    """Stream GET ``path`` into the file at ``dest``, honouring retries and rate limits."""
    retries = client.max_retries if is_retryable_method("GET") else 0
    for attempt in range(retries + 1):
        delay: float | None = None
        try:
            with client._http.stream(
                "GET", path, params=params, headers=headers, timeout=request_timeout(timeout)
            ) as resp:
                client.rate_limit = rate_limit_snapshot(resp) or client.rate_limit
                delay = retry_wait_seconds(resp, attempt=attempt, retries=retries)
                if delay is not None:
                    resp.read()
                else:
                    if not resp.is_success:
                        resp.read()  # from_response parses the body
                    raise_for_status(resp)
                    write_download_file(dest, resp.iter_bytes())
                    return dest
        except httpx2.HTTPError as exc:
            if attempt >= retries:
                raise err.from_transport_error(exc) from exc
            time.sleep(transport_retry_delay(attempt))
            continue
        if delay is None:
            raise AssertionError("unreachable: retry loop always returns or raises")
        time.sleep(delay)
    raise AssertionError("unreachable: retry loop always returns or raises")


class LanguagesAPI:
    """Supported BCP-47 languages and locale-code resolution."""

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def list(
        self, *, search: str | None = None, timeout: float | httpx2.Timeout | None = None
    ) -> LanguageListResponse:
        """All supported languages (GET /v1/languages); optional client-side filter."""
        data = parse_response(
            LanguageListResponse,
            self._c.get_json("/v1/languages", timeout=request_timeout(timeout)),
            operation="listLanguages",
        )
        if search:
            return filter_language_list(data, search)
        return data

    def resolve(self, codes: list[str]) -> list[str]:
        """Map loose locale input to canonical codes from GET /v1/languages."""
        return resolve_locale_codes(codes, language_bcp47_set(self.list().languages))


class CreditsAPI:
    """Org credit balance."""

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def balance(self, *, timeout: float | httpx2.Timeout | None = None) -> CreditBalanceResponse:
        """Current credit balance for the authenticated org."""
        return parse_response(
            CreditBalanceResponse,
            self._c.get_json("/v1/credits/balance", timeout=request_timeout(timeout)),
            operation="getCreditBalance",
        )


class TextAPI:
    """Synchronous text translation."""

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def translate(
        self,
        texts: Sequence[TextToTranslate],
        *,
        format: TextFormat | str | None = None,
        usage_type: TextUsageType | str | None = None,
        requester: Requester | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> TextTranslateResponse:
        """Translate up to 100 texts in one call (POST /v1/text/translate).

        Each text is charged once per ``ref`` and target language, so resending
        the same refs after a failure costs nothing more; the client never
        resends it for you. ``format`` and ``usage_type`` default on the server
        to ``text`` and ``api``.
        """
        resp = self._c.request(
            "POST",
            "/v1/text/translate",
            json=text_translate_body(
                texts, format=format, usage_type=usage_type, requester=requester
            ),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            TextTranslateResponse,
            decode_json_body(resp, operation="translateText"),
            operation="translateText",
        )


class UsageAPI:
    """Charges recorded against the org."""

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def list(
        self,
        *,
        from_: str,
        to: str,
        page: int = 1,
        limit: int = 50,
        timeout: float | httpx2.Timeout | None = None,
    ) -> UsageListResponse:
        """One page of usage records (GET /v1/usage).

        ``from_`` (inclusive) and ``to`` (exclusive) are ISO-8601 timestamps at
        most 366 days apart.
        """
        return parse_response(
            UsageListResponse,
            self._c.get_json(
                "/v1/usage",
                params=usage_list_params(from_=from_, to=to, page=page, limit=limit),
                timeout=request_timeout(timeout),
            ),
            operation="listUsage",
        )


class WebhooksAPI:
    """Beta. Webhooks that send project events to your HTTPS endpoint.

    Every call needs a key with the ``webhooks:manage`` scope, which only an
    organisation admin or owner can grant.
    """

    def __init__(self, client: ArbitrClient) -> None:
        self._c = client

    def list(self, *, timeout: float | httpx2.Timeout | None = None) -> WebhookListResponse:
        """Every webhook in the organisation, live and test (GET /v1/webhooks)."""
        return parse_response(
            WebhookListResponse,
            self._c.get_json(WEBHOOKS_PATH, timeout=request_timeout(timeout)),
            operation="listWebhooks",
        )

    def create(
        self,
        url: str,
        event_types: Sequence[str],
        *,
        description: str | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> WebhookCreateResponse:
        """Register a public HTTPS ``url`` for ``event_types`` (POST /v1/webhooks).

        The response's ``plaintext_secret`` verifies delivery signatures and is
        returned only here; store it before you discard the response.
        """
        resp = self._c.request(
            "POST",
            WEBHOOKS_PATH,
            json=webhook_create_body(url=url, event_types=event_types, description=description),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            WebhookCreateResponse,
            decode_json_body(resp, operation="createWebhook"),
            operation="createWebhook",
        )

    def get(
        self, webhook_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> WebhookResponse:
        """One webhook (GET /v1/webhooks/{id})."""
        return parse_response(
            WebhookResponse,
            self._c.get_json(webhook_path(webhook_id), timeout=request_timeout(timeout)),
            operation="getWebhook",
        )

    def update(
        self,
        webhook_id: str,
        *,
        event_types: Sequence[str] | None = None,
        status: WebhookStatus | str | None = None,
        description: str | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> WebhookResponse:
        """Change a webhook's events, description or status (PATCH /v1/webhooks/{id}).

        Only the arguments you pass are sent. ``status="active"`` turns a
        disabled webhook back on and resets its failure count. The URL can't
        be changed; create a new webhook instead.
        """
        resp = self._c.request(
            "PATCH",
            webhook_path(webhook_id),
            json=webhook_update_body(
                event_types=event_types, status=status, description=description
            ),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            WebhookResponse,
            decode_json_body(resp, operation="updateWebhook"),
            operation="updateWebhook",
        )

    def delete(
        self, webhook_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> WebhookResponse:
        """Turn a webhook off (DELETE /v1/webhooks/{id}).

        It is not removed: it stays listed as ``disabled`` and ``update`` with
        ``status="active"`` turns it back on.
        """
        resp = self._c.request("DELETE", webhook_path(webhook_id), timeout=request_timeout(timeout))
        return parse_response(
            WebhookResponse,
            decode_json_body(resp, operation="deleteWebhook"),
            operation="deleteWebhook",
        )

    def test(
        self, webhook_id: str, *, timeout: float | httpx2.Timeout | None = None
    ) -> dict[str, Any]:
        """Send a ``webhook.test`` event to the webhook (POST /v1/webhooks/{id}/test)."""
        resp = self._c.request(
            "POST", webhook_path(webhook_id, "test"), timeout=request_timeout(timeout)
        )
        return parse_response(
            WebhookTestBody,
            decode_json_body(resp, operation="testWebhook"),
            operation="testWebhook",
        ).root

    def deliveries(
        self,
        webhook_id: str,
        *,
        status: WebhookDeliveryStatus | str | None = None,
        event: str | None = None,
        after: str | None = None,
        limit: int | None = None,
        timeout: float | httpx2.Timeout | None = None,
    ) -> WebhookDeliveryListResponse:
        """One page of a webhook's deliveries, newest first (GET /v1/webhooks/{id}/deliveries).

        Pass the previous page's ``page.after`` as ``after`` for the next page.
        """
        return parse_response(
            WebhookDeliveryListResponse,
            self._c.get_json(
                webhook_path(webhook_id, "deliveries"),
                params=webhook_deliveries_params(
                    status=status, event=event, after=after, limit=limit
                ),
                timeout=request_timeout(timeout),
            ),
            operation="listWebhookDeliveries",
        )

    def redeliver(
        self,
        webhook_id: str,
        delivery_id: str,
        *,
        timeout: float | httpx2.Timeout | None = None,
    ) -> WebhookDelivery:
        """Queue a delivery to be sent again (POST .../deliveries/{id}/redeliver)."""
        resp = self._c.request(
            "POST",
            webhook_path(webhook_id, "deliveries", path_segment(delivery_id), "redeliver"),
            timeout=request_timeout(timeout),
        )
        return parse_response(
            WebhookDelivery,
            decode_json_body(resp, operation="redeliverWebhookDelivery"),
            operation="redeliverWebhookDelivery",
        )
