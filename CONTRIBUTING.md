# Contributing

## How changes reach this repository

This repository receives release snapshots from Straker's internal development
repository, where the SDK is developed and tested. Each release lands here as
one "Release X.Y.Z" commit. A change made directly here is overwritten by the
next release.

To report a bug or ask for a change, open an issue. A pull request is welcome
for discussion; maintainers port the change into the next release rather than
merging it here. Report security issues privately — see [SECURITY.md](SECURITY.md).

## Checks

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run python scripts/check_operation_coverage.py
```

Unit tests mock at the HTTP edge (`httpx2.MockTransport` / `respx` with
`pytest-httpx2`). They make no live API calls.

## Pinned OpenAPI spec

The client wraps the published OpenAPI surface only, pinned from production:

```bash
curl -sS https://api.arbitr.ai/openapi.json -o src/arbitr/openapi.json
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

## Releases

1. The version is set in `src/arbitr/_version.py` and `CHANGELOG.md` gets a
   `## X.Y.Z` section.
2. The snapshot arrives as a "Release X.Y.Z" pull request, which a maintainer
   approves and merges.
3. Publishing a GitHub release tagged `vX.Y.Z` runs the publish workflow. It
   checks the tag matches `arbitr.__version__`, builds, and uploads to PyPI via
   trusted publishing.

If a release is bad, yank `X.Y.Z` on PyPI and ship `X.Y.Z+1` with the fix.
Never reuse a version number.
