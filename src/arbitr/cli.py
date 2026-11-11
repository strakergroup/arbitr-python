"""arbitr — CLI for the Arbitr External API. See ``CLI_HELP`` for the contract."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from arbitr import (
    ActionRequiredError,
    ApiMovedError,
    ArbitrClient,
    ArbitrClientError,
    ArbitrError,
    ClientInputError,
    ProjectWaitTimeoutError,
    TransportError,
)
from arbitr._constants import API_KEYS_URL
from arbitr._credentials import load_host_settings, resolve_cli_max_retries
from arbitr._http import project_ui_url
from arbitr._version import __version__
from arbitr.generated.models import FindingSeverity, FindingStatus, QuotePair, QuoteResponse

CLI_HELP = f"""arbitr — CLI for the Arbitr External API.

Credentials come from the environment (ARBITR_API_KEY / ARBITR_BASE_URL) or a
dotenv file (default: ./.env). Mint a key at
{API_KEYS_URL}

Exit codes: 0 ok, 1 API error, 2 usage/config/network/timeout, 3 project is
waiting on a person (agent_selection or awaiting_payment) and cannot proceed
until they act.
"""

app = typer.Typer(
    name="arbitr",
    help=CLI_HELP,
    no_args_is_help=False,
    add_completion=False,
)


@dataclass(frozen=True)
class ClientConfig:
    """Global CLI options needed to build the API client (lazily)."""

    base_url: str | None
    env_file: Path
    max_retries: int | None


def _print_version(value: bool) -> None:
    """Print the distribution name and version, then exit.

    Eager so the flag keeps short-circuiting if another global option later
    grows a validating callback. ``arbitr-sdk`` is the name to paste into
    ``pip install`` — the import and the command are both ``arbitr``.
    """
    if value:
        typer.echo(f"arbitr-sdk {__version__}")
        raise typer.Exit


@app.callback()
def global_options(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="show the installed version and exit",
        ),
    ] = False,
    base_url: Annotated[
        str | None, typer.Option("--base-url", help="override ARBITR_BASE_URL / .env")
    ] = None,
    env_file: Annotated[Path, typer.Option("--env-file", help="dotenv path")] = Path(".env"),
    max_retries: Annotated[
        int | None,
        typer.Option(
            "--max-retries",
            help="times to retry a GET after 429/5xx (default 3; 0 disables)",
        ),
    ] = None,
) -> None:
    """Run `arbitr COMMAND --help` for per-command details.

    Credentials come from ARBITR_API_KEY or ``--env-file`` (never a flag — that
    would leak the key into shell history and process listings).
    """
    ctx.obj = ClientConfig(base_url=base_url, env_file=env_file, max_retries=max_retries)


def get_client(ctx: typer.Context) -> ArbitrClient:
    """Build the API client from stored global options."""
    config = ctx.find_object(ClientConfig)
    if config is None:
        raise RuntimeError("ClientConfig missing — the app callback did not run")
    return ArbitrClient.from_env(
        config.env_file,
        base_url=config.base_url,
        max_retries=resolve_cli_max_retries(config.env_file, max_retries=config.max_retries),
    )


def print_json(obj: Any) -> None:
    """Pretty-print a JSON-able command result to stdout."""
    typer.echo(json.dumps(_json_ready(obj), indent=2, ensure_ascii=False))


def _json_ready(obj: Any) -> Any:
    """Turn response models into dicts; leave already-JSON values alone."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json", exclude_unset=True)
    if isinstance(obj, dict):
        return {key: _json_ready(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_json_ready(item) for item in obj]
    return obj


def split_csv(value: str | None) -> list[str]:
    """Split a comma-separated CLI option into stripped, non-empty items."""
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def execute(ctx: typer.Context, operation: Callable[[ArbitrClient], Any]) -> None:
    """Run one command against the API and print JSON.

    Exit codes: 1 API error, 2 usage/config/network/timeout, 3 project is
    waiting on a person (agent_selection / awaiting_payment).
    Every error this package can raise is handled here — the CLI must never
    surface a traceback.
    """
    try:
        with get_client(ctx) as client:
            result = operation(client)
    except ClientInputError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except ApiMovedError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(f"hint: set --base-url / ARBITR_BASE_URL to {exc.moved_to}", err=True)
        raise typer.Exit(2) from exc
    except ArbitrError as exc:
        payload: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.request_id:
            payload["request_id"] = exc.request_id
        if exc.field_errors:
            payload["field_errors"] = exc.field_errors
        if exc.extra:
            payload.update(exc.extra)
        typer.echo(json.dumps({"error": payload}, indent=2), err=True)
        raise typer.Exit(1) from exc
    except ActionRequiredError as exc:
        typer.echo(f"action required: {exc}", err=True)
        if exc.status == "agent_selection":
            hint = exc.ui_url or f"see: arbitr link {exc.project_id}"
            typer.echo(
                "hint: if the project was created with --hold-for-quote, confirm its quote "
                f"(arbitr quote {exc.project_id}, then arbitr confirm {exc.project_id}); "
                "otherwise release the gate in "
                f"the UI (Start Campaign): {hint}",
                err=True,
            )
        elif exc.status == "awaiting_payment":
            typer.echo(f"hint: after topping up: arbitr resume {exc.project_id}", err=True)
        raise typer.Exit(3) from exc
    except TransportError as exc:
        typer.echo(f"error: {exc}", err=True)
        typer.echo(
            "hint: check the host is reachable and --base-url / ARBITR_BASE_URL is correct",
            err=True,
        )
        raise typer.Exit(2) from exc
    except ProjectWaitTimeoutError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except ArbitrClientError as exc:
        # Backstop: any other client-side failure (e.g. response-schema drift).
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    except OSError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from exc
    if result is not None:
        print_json(result)


ProjectIdArg = Annotated[str, typer.Argument(help="project id (UUID)")]


def _timeout_seconds(value: float) -> float:
    """A wait timeout: 0 or more, ``inf`` to wait forever; nan never times out, so it's refused."""
    if math.isnan(value) or value < 0:
        raise typer.BadParameter("must be a number of seconds, 0 or more (inf waits forever)")
    return value


def _interval_seconds(value: float) -> float:
    """A poll interval ``time.sleep`` can take: finite, 0 or more."""
    if not math.isfinite(value) or value < 0:
        raise typer.BadParameter("must be a finite number of seconds, 0 or more")
    return value


TimeoutOpt = Annotated[
    float,
    typer.Option(
        "--timeout", help="seconds (default 900; inf waits forever)", callback=_timeout_seconds
    ),
]
IntervalOpt = Annotated[
    float, typer.Option("--interval", help="poll seconds (default 5)", callback=_interval_seconds)
]
WaitThroughGateOpt = Annotated[
    bool,
    typer.Option(
        "--wait-through-gate",
        help="keep polling if the project parks at agent_selection/awaiting_payment",
    ),
]


@app.command()
def credits(ctx: typer.Context) -> None:
    """Print the org's credit balance."""
    execute(ctx, lambda client: client.credits.balance())


@app.command()
def me(ctx: typer.Context) -> None:
    """Introspect the API key (org, mode, scopes)."""
    execute(ctx, lambda client: client.me())


@app.command()
def languages(
    ctx: typer.Context,
    search: Annotated[
        str | None, typer.Option("--search", help="filter by code or name substring")
    ] = None,
) -> None:
    """List supported BCP-47 languages."""
    execute(ctx, lambda client: client.languages.list(search=search))


@app.command()
def projects(
    ctx: typer.Context,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="page size")] = 50,
    page: Annotated[
        int,
        typer.Option("--page", min=1, help="1-based page number; with --all, start here"),
    ] = 1,
    all_pages: Annotated[bool, typer.Option("--all", help="follow pagination")] = False,
    modified_after: Annotated[
        str | None,
        typer.Option("--modified-after", help="ISO-8601; only projects updated since"),
    ] = None,
    status: Annotated[str | None, typer.Option("--status", help="exact status filter")] = None,
) -> None:
    """List projects (first page, or everything with --all)."""

    def op(client: ArbitrClient) -> Any:
        if all_pages:
            return {
                "projects": list(
                    client.projects.iterate(
                        limit=limit, page=page, modified_after=modified_after, status=status
                    )
                )
            }
        return client.projects.list(
            limit=limit, page=page, modified_after=modified_after, status=status
        )

    execute(ctx, op)


@app.command()
def status(ctx: typer.Context, project_id: ProjectIdArg) -> None:
    """Get one project, annotated with UI deep links."""

    def op(client: ArbitrClient) -> Any:
        project = client.projects.get(project_id)
        payload = _json_ready(project)
        payload["_ui_url"] = client.project_url(project_id)
        if project.status == "agent_selection":
            payload["_action_url"] = client.project_url(project_id, view="agents")
        return payload

    execute(ctx, op)


@app.command()
def link(ctx: typer.Context, project_id: ProjectIdArg) -> None:
    """Print UI deep links for a project. Does not call the API."""
    config = ctx.find_object(ClientConfig)
    if config is None:
        raise RuntimeError("ClientConfig missing — the app callback did not run")
    host = load_host_settings(config.env_file, base_url=config.base_url)
    print_json(
        {
            "project": project_ui_url(host.ui_base_url, project_id),
            "agents_start_campaign": project_ui_url(host.ui_base_url, project_id, view="agents"),
        }
    )


@app.command()
def wait(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    timeout: TimeoutOpt = 900.0,
    interval: IntervalOpt = 5.0,
    wait_through_gate: WaitThroughGateOpt = False,
) -> None:
    """Poll a project until it reaches a terminal status."""
    execute(
        ctx,
        lambda client: client.projects.wait(
            project_id,
            timeout=timeout,
            poll_interval=interval,
            on_action_required="wait" if wait_through_gate else "raise",
        ),
    )


@app.command()
def submit(
    ctx: typer.Context,
    files: Annotated[
        list[Path], typer.Argument(help="source file paths", exists=True, dir_okay=False)
    ],
    locales: Annotated[
        str,
        typer.Option(
            "--locales",
            help=(
                "CSV of lowercase BCP-47 codes, e.g. ko-kr,fr-fr. "
                "Codes are sent as given and checked by the API against GET /v1/languages; "
                "use --resolve-locales "
                "or `arbitr languages --search` to pick the exact tag yourself."
            ),
        ),
    ],
    name: Annotated[
        str | None, typer.Option("--name", help="project name (default: first file's stem)")
    ] = None,
    source: Annotated[
        str,
        typer.Option("--source", help="source_language_code, region-specific (default: en-us)"),
    ] = "en-us",
    workflow: Annotated[
        str,
        typer.Option("--workflow", help="CSV of stages (default: AI_TRANSLATION)"),
    ] = "AI_TRANSLATION",
    due_date: Annotated[
        str | None, typer.Option("--due-date", help="YYYY-MM-DD, informational only")
    ] = None,
    idempotency_key: Annotated[
        str | None, typer.Option("--idempotency-key", help="safe-retry key")
    ] = None,
    hold_for_quote: Annotated[
        bool,
        typer.Option(
            "--hold-for-quote",
            help="hold the project for a price quote; nothing runs until `arbitr confirm`",
        ),
    ] = False,
    reference: Annotated[
        str | None,
        typer.Option(
            "--reference",
            help="your own id for the project; reusing one returns that project instead",
        ),
    ] = None,
    resolve_locales: Annotated[
        bool,
        typer.Option(
            "--resolve-locales",
            help="expand --locales against GET /v1/languages before submitting",
        ),
    ] = False,
    wait_for: Annotated[bool, typer.Option("--wait", help="poll until terminal")] = False,
    out: Annotated[
        Path | None, typer.Option("--out", help="with --wait: directory for the deliverables ZIP")
    ] = None,
    timeout: TimeoutOpt = 900.0,
    interval: IntervalOpt = 5.0,
    wait_through_gate: WaitThroughGateOpt = False,
) -> None:
    """Create a translation project from local files."""

    def op(client: ArbitrClient) -> Any:
        if hold_for_quote and wait_for:
            raise ClientInputError(
                "--hold-for-quote and --wait can't be combined: a held project waits for "
                "`arbitr quote`, then `arbitr confirm`"
            )
        targets = split_csv(locales)
        if resolve_locales:
            targets = client.languages.resolve(targets)
        project = client.projects.submit(
            files=list(files),
            name=name or files[0].stem,
            target_language_codes=targets,
            source_language_code=source,
            workflow=split_csv(workflow),
            due_date=due_date,
            hold_for_quote=hold_for_quote,
            reference=reference,
            idempotency_key=idempotency_key,
        )
        payload = _json_ready(project)
        payload["_ui_url"] = client.project_url(project.id)
        if not wait_for:
            return payload
        final = client.projects.wait(
            project.id,
            timeout=timeout,
            poll_interval=interval,
            on_action_required="wait" if wait_through_gate else "raise",
        )
        out_payload = _json_ready(final)
        if out is not None:
            out.mkdir(parents=True, exist_ok=True)
            dest = client.projects.download_zip(final.id, out / f"{final.id}-deliverables.zip")
            out_payload["_downloaded_zip"] = str(dest)
        return out_payload

    execute(ctx, op)


@app.command()
def deliverables(ctx: typer.Context, project_id: ProjectIdArg) -> None:
    """List a project's deliverable files."""
    execute(ctx, lambda client: client.projects.deliverables(project_id))


@app.command()
def deliverable(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    deliverable_id: Annotated[str, typer.Argument(help="deliverable id (UUID)")],
) -> None:
    """Print one deliverable's JSON metadata."""
    execute(ctx, lambda client: client.projects.deliverable(project_id, deliverable_id))


@app.command()
def findings(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    limit: Annotated[int, typer.Option("--limit", min=1, max=200, help="page size")] = 50,
    after: Annotated[
        str | None,
        typer.Option(
            "--after",
            help="seek token from the previous page's page.after; with --all, start here",
        ),
    ] = None,
    severity: Annotated[
        FindingSeverity | None,
        typer.Option("--severity", help="restrict to flags of this severity"),
    ] = None,
    category: Annotated[str | None, typer.Option("--category", help="exact flag category")] = None,
    status: Annotated[
        FindingStatus | None, typer.Option("--status", help="restrict to flags with this status")
    ] = None,
    all_pages: Annotated[
        bool, typer.Option("--all", help="walk page.after until has_more is false")
    ] = False,
) -> None:
    """List verification findings (flags and agent findings) for a project."""

    def op(client: ArbitrClient) -> Any:
        if all_pages:
            return {
                "findings": list(
                    client.projects.iterate_findings(
                        project_id,
                        limit=limit,
                        after=after,
                        severity=severity,
                        category=category,
                        status=status,
                    )
                )
            }
        return client.projects.findings(
            project_id,
            limit=limit,
            after=after,
            severity=severity,
            category=category,
            status=status,
        )

    execute(ctx, op)


@app.command("chain-of-custody")
def chain_of_custody(ctx: typer.Context, project_id: ProjectIdArg) -> None:
    """Get the provenance record for a project."""
    execute(ctx, lambda client: client.projects.chain_of_custody(project_id))


@app.command()
def download(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    deliverable: Annotated[
        str | None,
        typer.Option("--deliverable", help="deliverable id (UUID) → download just that file"),
    ] = None,
    out: Annotated[Path | None, typer.Option("--out", help="destination path")] = None,
) -> None:
    """Download all deliverables as a ZIP, or one file with --deliverable."""

    def op(client: ArbitrClient) -> Any:
        if deliverable is not None:
            path = client.projects.download_deliverable(
                project_id, deliverable, out or Path(deliverable)
            )
        else:
            path = client.projects.download_zip(
                project_id, out or Path(f"{project_id}-deliverables.zip")
            )
        return {"downloaded": str(path), "bytes": path.stat().st_size}

    execute(ctx, op)


@app.command()
def resume(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    human_review: Annotated[
        bool,
        typer.Option(
            "--human-review", help="resume a trust-credit-parked human-review send instead"
        ),
    ] = False,
) -> None:
    """Resume a project parked at awaiting_payment (after credit top-up)."""

    def op(client: ArbitrClient) -> Any:
        if human_review:
            return client.projects.resume_human_review(project_id)
        return client.projects.resume(project_id)

    execute(ctx, op)


QuoteVersionOpt = Annotated[
    int,
    typer.Option("--quote-version", help="the quote `version` you reviewed"),
]


def parse_quote_pair(value: str) -> QuotePair:
    """``FILE_ID:LANGUAGE`` from ``--remove`` as a quote pair."""
    file_id, sep, language = value.partition(":")
    if not (sep and file_id and language):
        raise ClientInputError(f"--remove takes FILE_ID:LANGUAGE, not {value!r}")
    return QuotePair(file_id=file_id, target_language_code=language)


@app.command()
def quote(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    wait_for: Annotated[
        bool, typer.Option("--wait", help="poll while the quote is still `pricing`")
    ] = False,
    timeout: TimeoutOpt = 900.0,
    interval: IntervalOpt = 5.0,
) -> None:
    """Get the price quote for a project created with --hold-for-quote.

    With --wait, exits 1 if the quote expires instead of becoming ready.
    """

    def op(client: ArbitrClient) -> QuoteResponse:
        deadline = time.monotonic() + timeout
        current = client.projects.quote(project_id)
        while wait_for and current.status == "pricing":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProjectWaitTimeoutError(project_id, str(current.status), timeout)
            time.sleep(min(interval, remaining))
            current = client.projects.quote(project_id)
        if wait_for and current.status == "expired":
            print_json(current)
            typer.echo(f"error: the quote for {project_id} expired before it was ready", err=True)
            raise typer.Exit(1)
        return current

    execute(ctx, op)


@app.command()
def adjust(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    quote_version: QuoteVersionOpt,
    remove: Annotated[
        list[str],
        typer.Option("--remove", help="FILE_ID:LANGUAGE to drop from the quote; repeat for more"),
    ],
) -> None:
    """Drop files or languages from a held project's quote and get the new price."""
    execute(
        ctx,
        lambda client: client.projects.adjust_quote(
            project_id,
            quote_version=quote_version,
            remove=[parse_quote_pair(value) for value in remove],
        ),
    )


@app.command()
def confirm(
    ctx: typer.Context,
    project_id: ProjectIdArg,
    quote_version: Annotated[
        int | None,
        typer.Option(
            "--quote-version",
            help="refuse to confirm if the quote changed since you reviewed this version",
        ),
    ] = None,
) -> None:
    """Confirm a held project's quote so the work starts. This spends credits."""
    execute(ctx, lambda client: client.projects.confirm(project_id, quote_version=quote_version))


def entrypoint() -> None:
    """Console-script entry point (`arbitr ...`)."""
    app()


if __name__ == "__main__":
    entrypoint()
