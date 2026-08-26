"""``arbitr`` — CLI for the Arbitr External API.

Credentials come from the environment (ARBITR_API_KEY / ARBITR_BASE_URL) or a
dotenv file (default: ./.env).

Exit codes: 0 ok, 1 API error, 2 usage/config/timeout, 3 project parked at a
human gate (agent_selection / awaiting_payment).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import BaseModel

from arbitr import (
    ActionRequiredError,
    ArbitrClient,
    ArbitrClientError,
    ArbitrError,
    ClientInputError,
    ProjectWaitTimeoutError,
    TransportError,
)
from arbitr._credentials import load_host_settings, resolve_cli_max_retries
from arbitr._http import project_ui_url
from arbitr.generated.models import FindingSeverity, FindingStatus

app = typer.Typer(
    name="arbitr",
    help=__doc__,
    no_args_is_help=False,
    add_completion=False,
)


@dataclass(frozen=True)
class ClientConfig:
    """Global CLI options needed to build the API client (lazily)."""

    base_url: str | None
    env_file: Path
    max_retries: int | None


@app.callback()
def global_options(
    ctx: typer.Context,
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

    Exit codes: 1 API error, 2 config/network/timeout, 3 parked at a human gate.
    Every error this package can raise is handled here — the CLI must never
    surface a traceback.
    """
    try:
        with get_client(ctx) as client:
            result = operation(client)
    except ClientInputError as exc:
        typer.echo(f"error: {exc}", err=True)
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
            typer.echo(f"hint: release the gate in the UI (Start Campaign): {hint}", err=True)
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
TimeoutOpt = Annotated[float, typer.Option("--timeout", help="seconds (default 900)")]
IntervalOpt = Annotated[float, typer.Option("--interval", help="poll seconds (default 5)")]
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
    limit: Annotated[int, typer.Option("--limit", help="page size")] = 50,
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
                "Bare codes (ko) are rejected — use --resolve-locales "
                "or `arbitr languages --search` to find the full tag."
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


def entrypoint() -> None:
    """Console-script entry point (`arbitr ...`)."""
    app()


if __name__ == "__main__":
    entrypoint()
