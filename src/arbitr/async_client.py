"""Asynchronous client for the Arbitr External API."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

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
    load_upload_parts,
    parse_extension_check,
    require_submit_files,
)
from arbitr._http import (
    awrite_download_file,
    default_headers,
    derive_ui_url,
    is_retryable_method,
    parse_max_retries,
    project_ui_url,
    raise_for_status,
    rate_limit_snapshot,
    retry_wait_seconds,
    transport_retry_delay,
)
from arbitr._locales import filter_language_list, language_bcp47_set, resolve_locale_codes
from arbitr._parse import decode_json_body, parse_response
from arbitr._projects import (
    ProjectResumptionResponse,
    findings_list_params,
    idempotency_headers,
    next_findings_after,
    project_list_params,
    project_submit_form,
)
from arbitr._version import __version__ as _version
from arbitr._wait import decide_project_wait, parse_on_action_required
from arbitr.client import new_idempotency_key
from arbitr.generated.models import (
    AgentFinding,
    ChainOfCustodyResponse,
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
)

__all__ = ["AsyncArbitrClient", "new_idempotency_key"]


class AsyncArbitrClient:
    """Asynchronous client for one API key and one host."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        *,
        api_version: str = "1",
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
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
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            transport=transport,
            headers=default_headers(api_key, api_version),
        )
        self.projects = AsyncProjectsAPI(self)
        self.languages = AsyncLanguagesAPI(self)
        self.credits = AsyncCreditsAPI(self)

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

    async def me(self) -> MeResponse:
        """Introspect the authenticated key (GET /v1/me)."""
        return parse_response(MeResponse, await self.get_json("/v1/me"), operation="getCurrentKey")

    @classmethod
    def from_env(
        cls,
        env_file: str | Path = ".env",
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any,
    ) -> AsyncArbitrClient:
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

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Send an authenticated request; raise on non-2xx or transport failure.

        Retries retryable statuses up to ``max_retries`` times when the method
        is safe to replay, honouring ``Retry-After`` on 429.
        """
        retries = self.max_retries if is_retryable_method(method) else 0
        for attempt in range(retries + 1):
            try:
                resp = await self._http.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                if attempt >= retries:
                    raise err.from_transport_error(exc) from exc
                await asyncio.sleep(transport_retry_delay(attempt))
                continue
            self.rate_limit = rate_limit_snapshot(resp) or self.rate_limit
            delay = retry_wait_seconds(resp, attempt=attempt, retries=retries)
            if delay is not None:
                await resp.aclose()
                await asyncio.sleep(delay)
                continue
            raise_for_status(resp)
            return resp
        raise AssertionError("unreachable: retry loop always returns or raises")

    async def get_json(self, path: str, **kwargs: Any) -> Any:
        """GET ``path`` and return the parsed JSON body (None when empty)."""
        resp = await self.request("GET", path, **kwargs)
        return decode_json_body(resp, operation=path)

    async def aclose(self) -> None:
        """Close the underlying httpx async client."""
        await self._http.aclose()

    async def __aenter__(self) -> AsyncArbitrClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"AsyncArbitrClient(base_url={self.base_url!r}, version={_version!r})"


class AsyncProjectsAPI:
    """Async project lifecycle: submit, list/poll, findings, chain of custody, deliverables."""

    def __init__(self, client: AsyncArbitrClient) -> None:
        self._c = client

    async def submit(
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
        parts = await asyncio.to_thread(load_upload_parts, files, extension_check)
        resp = await self._c.request(
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

    async def list(
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
            await self._c.get_json(
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

    async def iterate(
        self,
        *,
        limit: int = 50,
        page: int = 1,
        modified_after: str | None = None,
        status: str | None = None,
    ) -> AsyncIterator[ProjectResponse]:
        """Yield every project, following page-number pagination.

        Pass ``page`` to resume from a page other than the first.
        """
        page_number = page
        while True:
            body = await self.list(
                limit=limit,
                page=page_number,
                modified_after=modified_after,
                status=status,
            )
            for project in body.projects:
                yield project
            if not body.page.has_more:
                return
            page_number += 1

    async def get(self, project_id: str) -> ProjectResponse:
        """Poll status/progress (GET /v1/projects/{id})."""
        return parse_response(
            ProjectResponse,
            await self._c.get_json(f"/v1/projects/{project_id}"),
            operation="getProject",
        )

    async def wait(
        self,
        project_id: str,
        *,
        timeout: float = 900.0,  # noqa: ASYNC109 — poll deadline, not asyncio.timeout
        poll_interval: float = 5.0,
        on_action_required: OnActionRequired = "raise",
    ) -> ProjectResponse:
        """Poll until the project reaches a terminal status."""
        on_action_required = parse_on_action_required(on_action_required)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        streak = 0
        while True:
            project = await self.get(project_id)
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
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise err.ProjectWaitTimeoutError(project_id, decision.status, timeout)
            await asyncio.sleep(min(poll_interval, remaining))

    async def findings(
        self,
        project_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        severity: FindingSeverity | str | None = None,
        category: str | None = None,
        status: FindingStatus | str | None = None,
    ) -> FindingListResponse:
        """One page of segment flags and agent findings (GET …/findings).

        Walk ``page.after`` as ``after=`` until ``page.has_more`` is false.
        ``severity``, ``category``, and ``status`` filter flags only.
        """
        return parse_response(
            FindingListResponse,
            await self._c.get_json(
                f"/v1/projects/{project_id}/findings",
                params=findings_list_params(
                    limit=limit,
                    after=after,
                    severity=severity,
                    category=category,
                    status=status,
                ),
            ),
            operation="listProjectFindings",
        )

    async def iterate_findings(
        self,
        project_id: str,
        *,
        limit: int = 50,
        after: str | None = None,
        severity: FindingSeverity | str | None = None,
        category: str | None = None,
        status: FindingStatus | str | None = None,
    ) -> AsyncIterator[FlagFinding | AgentFinding]:
        """Yield every finding, following ``page.after`` keyset pagination.

        Pass ``after`` to resume from a previous page's seek token.
        """
        while True:
            body = await self.findings(
                project_id,
                limit=limit,
                after=after,
                severity=severity,
                category=category,
                status=status,
            )
            for finding in body.findings:
                yield finding
            after = next_findings_after(
                has_more=body.page.has_more,
                after=body.page.after,
                previous=after,
            )
            if after is None:
                return

    async def chain_of_custody(self, project_id: str) -> ChainOfCustodyResponse:
        """Provenance record for a project (GET …/chain-of-custody)."""
        return parse_response(
            ChainOfCustodyResponse,
            await self._c.get_json(f"/v1/projects/{project_id}/chain-of-custody"),
            operation="getProjectChainOfCustody",
        )

    async def deliverables(self, project_id: str) -> DeliverableListResponse:
        """List deliverable files (GET /v1/projects/{id}/deliverables)."""
        return parse_response(
            DeliverableListResponse,
            await self._c.get_json(f"/v1/projects/{project_id}/deliverables"),
            operation="listDeliverables",
        )

    async def deliverable(self, project_id: str, deliverable_id: str) -> ProjectDeliverableResponse:
        """Get one deliverable's metadata (GET …/deliverables/{id})."""
        return parse_response(
            ProjectDeliverableResponse,
            await self._c.get_json(f"/v1/projects/{project_id}/deliverables/{deliverable_id}"),
            operation="getDeliverable",
        )

    async def download_zip(self, project_id: str, dest: str | Path) -> Path:
        """Download all deliverables as one ZIP (``?format=zip``)."""
        return await _astream_download(
            self._c,
            f"/v1/projects/{project_id}/deliverables",
            Path(dest),
            params={"format": "zip"},
        )

    async def download_deliverable(
        self, project_id: str, deliverable_id: str, dest: str | Path
    ) -> Path:
        """Download one deliverable file as bytes."""
        return await _astream_download(
            self._c,
            f"/v1/projects/{project_id}/deliverables/{deliverable_id}",
            Path(dest),
            headers={"Accept": "application/octet-stream"},
        )

    async def resume(self, project_id: str) -> ProjectResumptionResponse:
        """Resume a project parked at ``awaiting_payment`` after a credit top-up."""
        resp = await self._c.request("POST", f"/v1/projects/{project_id}/resumptions")
        return parse_response(
            ProjectResumptionResponse,
            decode_json_body(resp, operation="createProjectResumption"),
            operation="createProjectResumption",
        )

    async def resume_human_review(self, project_id: str) -> HumanReviewResponse:
        """Re-attempt a trust-credit-parked human-review send after a TC top-up."""
        resp = await self._c.request("POST", f"/v1/projects/{project_id}/review/resumptions")
        return parse_response(
            HumanReviewResponse,
            decode_json_body(resp, operation="createReviewResumption"),
            operation="createReviewResumption",
        )


async def _astream_download(
    client: AsyncArbitrClient,
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
            async with client._http.stream("GET", path, params=params, headers=headers) as resp:
                client.rate_limit = rate_limit_snapshot(resp) or client.rate_limit
                delay = retry_wait_seconds(resp, attempt=attempt, retries=retries)
                if delay is not None:
                    await resp.aread()
                else:
                    raise_for_status(resp)
                    await awrite_download_file(dest, resp.aiter_bytes())
                    return dest
        except httpx.HTTPError as exc:
            if attempt >= retries:
                raise err.from_transport_error(exc) from exc
            await asyncio.sleep(transport_retry_delay(attempt))
            continue
        if delay is None:
            raise AssertionError("unreachable: retry loop always returns or raises")
        await asyncio.sleep(delay)
    raise AssertionError("unreachable: retry loop always returns or raises")


class AsyncLanguagesAPI:
    """Supported BCP-47 languages and locale-code resolution."""

    def __init__(self, client: AsyncArbitrClient) -> None:
        self._c = client

    async def list(self, *, search: str | None = None) -> LanguageListResponse:
        """All supported languages (GET /v1/languages); optional client-side filter."""
        data = parse_response(
            LanguageListResponse,
            await self._c.get_json("/v1/languages"),
            operation="listLanguages",
        )
        if search:
            return filter_language_list(data, search)
        return data

    async def resolve(self, codes: list[str]) -> list[str]:
        """Map loose locale input to canonical codes from GET /v1/languages."""
        payload = await self.list()
        return resolve_locale_codes(codes, language_bcp47_set(payload.languages))


class AsyncCreditsAPI:
    """Org credit balance."""

    def __init__(self, client: AsyncArbitrClient) -> None:
        self._c = client

    async def balance(self) -> CreditBalanceResponse:
        """Current credit balance for the authenticated org."""
        return parse_response(
            CreditBalanceResponse,
            await self._c.get_json("/v1/credits/balance"),
            operation="getCreditBalance",
        )
