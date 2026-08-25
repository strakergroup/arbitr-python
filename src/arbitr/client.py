"""Synchronous client for the Arbitr External API."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
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
    project_ui_url,
    raise_for_status,
    rate_limit_snapshot,
    retry_wait_seconds,
    transport_retry_delay,
    write_download_file,
)
from arbitr._locales import filter_language_list, language_bcp47_set, resolve_locale_codes
from arbitr._parse import decode_json_body, parse_response
from arbitr._projects import (
    ProjectResumptionResponse,
    idempotency_headers,
    project_list_params,
    project_submit_form,
)
from arbitr._version import __version__ as _version
from arbitr._wait import decide_project_wait, parse_on_action_required
from arbitr.generated.models import (
    CreditBalanceResponse,
    DeliverableListResponse,
    HumanReviewResponse,
    LanguageListResponse,
    MeResponse,
    ProjectDeliverableResponse,
    ProjectListResponse,
    ProjectResponse,
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
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        ui_base_url: str | None = None,
        max_retries: int = 0,
    ) -> None:
        if not api_key:
            raise err.MissingApiKeyError("api_key is required")
        self._api_key = SecretStr(api_key)
        self.base_url = base_url.rstrip("/")
        self.ui_base_url = (ui_base_url or derive_ui_url(self.base_url)).rstrip("/")
        self.max_retries = parse_max_retries(max_retries)
        self.rate_limit: dict[str, str] = {}
        self._http = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers=default_headers(api_key, api_version),
        )
        self.projects = ProjectsAPI(self)
        self.languages = LanguagesAPI(self)
        self.credits = CreditsAPI(self)

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

    def me(self) -> MeResponse:
        """Introspect the authenticated key (GET /v1/me)."""
        return parse_response(MeResponse, self.get_json("/v1/me"), operation="getCurrentKey")

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

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send an authenticated request; raise on non-2xx or transport failure.

        Retries retryable statuses up to ``max_retries`` times when the method
        is safe to replay, honouring ``Retry-After`` on 429.
        """
        retries = self.max_retries if is_retryable_method(method) else 0
        for attempt in range(retries + 1):
            try:
                resp = self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
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
        """Close the underlying httpx client."""
        self._http.close()

    def __enter__(self) -> ArbitrClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ArbitrClient(base_url={self.base_url!r}, version={_version!r})"


class ProjectsAPI:
    """Project lifecycle: submit, list/poll, deliverables, resumptions."""

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
        idempotency_key: str | None = None,
        extension_check: ExtensionCheck = "allowlist",
    ) -> ProjectResponse:
        """Create a translation project (POST /v1/projects)."""
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
                ),
                files=parts,
                headers=idempotency_headers(idempotency_key),
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
    ) -> ProjectListResponse:
        """One page of projects (GET /v1/projects)."""
        return parse_response(
            ProjectListResponse,
            self._c.get_json(
                "/v1/projects",
                params=project_list_params(
                    limit=limit,
                    page=page,
                    modified_after=modified_after,
                    status=status,
                ),
            ),
            operation="listProjects",
        )

    def iterate(
        self,
        *,
        limit: int = 50,
        modified_after: str | None = None,
        status: str | None = None,
    ) -> Iterator[ProjectResponse]:
        """Yield every project, following page-number pagination."""
        page_number = 1
        while True:
            body = self.list(
                limit=limit,
                page=page_number,
                modified_after=modified_after,
                status=status,
            )
            yield from body.projects
            if not body.page.has_more:
                return
            page_number += 1

    def get(self, project_id: str) -> ProjectResponse:
        """Poll status/progress (GET /v1/projects/{id})."""
        return parse_response(
            ProjectResponse,
            self._c.get_json(f"/v1/projects/{project_id}"),
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

    def deliverables(self, project_id: str) -> DeliverableListResponse:
        """List deliverable files (GET /v1/projects/{id}/deliverables)."""
        return parse_response(
            DeliverableListResponse,
            self._c.get_json(f"/v1/projects/{project_id}/deliverables"),
            operation="listDeliverables",
        )

    def deliverable(self, project_id: str, deliverable_id: str) -> ProjectDeliverableResponse:
        """Get one deliverable's metadata (GET …/deliverables/{id})."""
        return parse_response(
            ProjectDeliverableResponse,
            self._c.get_json(f"/v1/projects/{project_id}/deliverables/{deliverable_id}"),
            operation="getDeliverable",
        )

    def download_zip(self, project_id: str, dest: str | Path) -> Path:
        """Download all deliverables as one ZIP (``?format=zip``)."""
        return _stream_download(
            self._c,
            f"/v1/projects/{project_id}/deliverables",
            Path(dest),
            params={"format": "zip"},
        )

    def download_deliverable(self, project_id: str, deliverable_id: str, dest: str | Path) -> Path:
        """Download one deliverable file as bytes."""
        return _stream_download(
            self._c,
            f"/v1/projects/{project_id}/deliverables/{deliverable_id}",
            Path(dest),
            headers={"Accept": "application/octet-stream"},
        )

    def resume(self, project_id: str) -> ProjectResumptionResponse:
        """Resume a project parked at ``awaiting_payment`` after a credit top-up."""
        resp = self._c.request("POST", f"/v1/projects/{project_id}/resumptions")
        return parse_response(
            ProjectResumptionResponse,
            decode_json_body(resp, operation="createProjectResumption"),
            operation="createProjectResumption",
        )

    def resume_human_review(self, project_id: str) -> HumanReviewResponse:
        """Re-attempt a trust-credit-parked human-review send after a TC top-up."""
        resp = self._c.request("POST", f"/v1/projects/{project_id}/review/resumptions")
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
) -> Path:
    """Stream GET ``path`` into the file at ``dest``, honouring retries and rate limits."""
    retries = client.max_retries if is_retryable_method("GET") else 0
    for attempt in range(retries + 1):
        delay: float | None = None
        try:
            with client._http.stream("GET", path, params=params, headers=headers) as resp:
                client.rate_limit = rate_limit_snapshot(resp) or client.rate_limit
                delay = retry_wait_seconds(resp, attempt=attempt, retries=retries)
                if delay is not None:
                    resp.read()
                else:
                    raise_for_status(resp)
                    write_download_file(dest, resp.iter_bytes())
                    return dest
        except httpx.HTTPError as exc:
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

    def list(self, *, search: str | None = None) -> LanguageListResponse:
        """All supported languages (GET /v1/languages); optional client-side filter."""
        data = parse_response(
            LanguageListResponse,
            self._c.get_json("/v1/languages"),
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

    def balance(self) -> CreditBalanceResponse:
        """Current credit balance for the authenticated org."""
        return parse_response(
            CreditBalanceResponse,
            self._c.get_json("/v1/credits/balance"),
            operation="getCreditBalance",
        )
