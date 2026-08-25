# AGENTS.md

Official Python SDK + CLI for the Arbitr External API.

Domain terms live in `CONTEXT.md`.

## Surface rules

- Wrap **published** OpenAPI operations only. The mapped and
  deprecated-ignored operation tables live in `src/arbitr/_coverage.py` and are
  shared by `scripts/check_operation_coverage.py` and
  `tests/test_operation_coverage.py` — edit them in that one place.
- After `https://api-arbitr.straker.ai/openapi.json` changes, refresh
  `src/arbitr/openapi.json` (it ships inside the package; read it with
  `arbitr.pinned_spec()`), regenerate models, add methods on **both**
  `ArbitrClient` and `AsyncArbitrClient`, and mirror the tests in
  `tests/test_client.py` and `tests/test_async_client.py`.
- Do not hand-edit `src/arbitr/generated/`.
- Do not implement sync by calling `asyncio.run` on the async client.
- Default base URL is `https://api-arbitr.straker.ai`. Pin OpenAPI from that
  host. README, CLI help, comments, and examples mention only that public
  API host.
- Every error derives from `ArbitrBaseError`. Never let an `httpx` exception
  reach a caller, and never let the CLI print a traceback — `cli.execute()`
  handles the whole tree.
- Language codes on the wire are lowercase BCP-47 tags. Normalize with
  `_projects.normalize_locale_code`; only `languages.resolve()` may expand a
  bare code.
- Bump the version in `src/arbitr/_version.py` only; Hatch reads it from there.

## Checks

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run pytest
uv run python scripts/check_operation_coverage.py
```

Unit tests use `httpx.MockTransport` / `respx` at the HTTP edge. No live API
calls in CI.
