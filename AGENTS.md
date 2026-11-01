# AGENTS.md

Official Python SDK + CLI for the Arbitr External API.

Domain terms live in `CONTEXT.md`. Cursor always-on copy of the git
policy: `.cursor/rules/public-sdk-git.mdc`.

## Where changes are made

The SDK is developed in Straker's internal development repository. The public
`strakergroup/arbitr-python` repository only receives release snapshots, one
"Release X.Y.Z" commit each, so a change made there directly is overwritten by
the next release. Make changes in the development repository.

## Public git

This repository is public. Branch names, commits, tags, and pull requests
are customer-visible.

- No ticket ids in branches, commits, PR titles, bodies, or tags.
- No issue-tracker URLs, internal hostnames, deploy notes, or employee
  machine paths.
- Write for an external caller: what changed in the published API/CLI/SDK
  and why it matters to them.
- Reuse a short descriptive branch (`findings-and-chain-of-custody`), not a
  ticket-prefixed name.
- Do not commit agent working notes, implementation plans, or design specs.
  Do not add `/docs` indexes. `CHANGELOG.md` is the only changelog.

Wrong: `fix(TICKET-1234): timestamps after staging smoke`

Right: `Serialize chain-of-custody timestamps with a UTC offset`

## Surface rules

- Wrap **published** OpenAPI operations only. The mapped operation table and
  optional ignore set live in `src/arbitr/_coverage.py` and are shared by
  `scripts/check_operation_coverage.py` and `tests/test_operation_coverage.py`
  — edit them in that one place. Prefer an empty ignore set; only add an id
  when it is still published but must not grow a wrapper.
- After `https://api.arbitr.ai/openapi.json` changes, refresh
  `src/arbitr/openapi.json` (it ships inside the package; read it with
  `arbitr.pinned_spec()`), regenerate models, add methods on **both**
  `ArbitrClient` and `AsyncArbitrClient`, and mirror the tests in
  `tests/test_client.py` and `tests/test_async_client.py`.
- Do not hand-edit `src/arbitr/generated/`.
- Do not implement sync by calling `asyncio.run` on the async client.
- Default base URL is `https://api.arbitr.ai`. Pin OpenAPI from that
  host. README, CLI help, comments, and examples mention only that public
  API host.
- Every error derives from `ArbitrBaseError`. Never let an `httpx2` exception
  reach a caller, and never let the CLI print a traceback — `cli.execute()`
  handles the whole tree.
- Language codes on the wire are lowercase BCP-47 tags. Normalize with
  `_projects.normalize_locale_code`. A bare code (`ko`) is sent as given for
  the API to check against `GET /v1/languages`; do not refuse it locally. Only
  `languages.resolve()` may expand a bare code.
- Bump the version in `src/arbitr/_version.py` only; Hatch reads it from there.
- Every release needs a `## X.Y.Z` section in `CHANGELOG.md`, written for an
  external caller. The release refuses to run without it.
- The library must import without Typer: the CLI is the optional `cli` extra, and
  only `arbitr/cli.py` imports `typer`. The console script goes through
  `_cli_entry.py`, which names the extra when it is missing.

## Checks

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run pytest
uv run python scripts/check_operation_coverage.py
```

Unit tests use `httpx2.MockTransport` / `respx` (via `pytest-httpx2`) at the HTTP edge. No live API
calls in CI.
