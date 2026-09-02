# Contributing

## Develop

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run python scripts/generate_models.py   # after refreshing the pinned spec
uv run python scripts/check_operation_coverage.py
```

Unit tests mock at the HTTP edge (`httpx.MockTransport` / `respx`). CI makes no
live API calls.

## Pinned OpenAPI spec

The client wraps the published OpenAPI surface only, pinned from production:

```bash
curl -sS https://api-arbitr.straker.ai/openapi.json -o src/arbitr/openapi.json
uv run python scripts/generate_models.py
```

After a refresh, add methods on both `ArbitrClient` and `AsyncArbitrClient` and
mirror the tests in `tests/test_client.py` and `tests/test_async_client.py`.
`scripts/check_operation_coverage.py` fails if a published operation is left
unwrapped.

The snapshot ships inside the package, so an installed copy can diff itself
against a live host:

```python
from arbitr import pinned_spec

print(sorted(pinned_spec()["paths"]))
```

Do not edit `src/arbitr/generated/models.py` by hand.

## Releasing

1. Bump `__version__` in `src/arbitr/_version.py` (the only place the version
   lives; Hatch reads it from there).
2. Merge to `master`.
3. Publish a GitHub release tagged `vX.Y.Z`. The publish workflow verifies the
   tag matches `arbitr.__version__`, builds, and uploads to PyPI via trusted
   publishing.
