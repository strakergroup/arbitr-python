# Arbitr Python

Official Python client and `arbitr` CLI for the [Arbitr External API](https://api-arbitr.straker.ai/docs).

```bash
pip install arbitr
```

```python
from arbitr import ArbitrClient

client = ArbitrClient.from_env()  # ARBITR_API_KEY, optional ARBITR_BASE_URL
project = client.projects.submit(
    files=["report.docx"],
    name="Q3 report",
    target_language_codes=["ko-kr", "fr-fr"],
    idempotency_key="run-2026-08-report",
)
final = client.projects.wait(project.id)
client.projects.download_zip(final.id, "out/deliverables.zip")
```

Async:

```python
from arbitr import AsyncArbitrClient

async with AsyncArbitrClient.from_env() as client:
    me = await client.me()
```

Coding agents: give your agent this prompt:

```text
Set up arbitr for me. Fetch https://arbitr.apidocumentation.com/getting-started/agent-setup/index.md and follow it.
```

Or install the persistent agent skill:

```bash
npx -y skills add strakergroup/arbitr-python --skill arbitr --yes --global
```

CLI:

Mint a key at [https://arbitr.straker.ai/settings/api-keys](https://arbitr.straker.ai/settings/api-keys).

```bash
export ARBITR_API_KEY=abr_live_...
arbitr me
arbitr submit report.docx --locales ko-kr,fr-fr --wait --out out/
```

Exit codes: `0` ok, `1` API error, `2` usage/config/network/timeout, `3` parked
at a human gate.

Default host is production: `https://api-arbitr.straker.ai`.

Language codes are lowercase BCP-47 tags (`ko-kr`, `fr-fr`). Bare codes (`ko`)
are rejected by the API — `client.languages.resolve(["ko"])` expands them, or
`arbitr submit --resolve-locales` does it for you.

The client wraps the **published** OpenAPI surface only. Deprecated aliases
(agent-selection, `/deliverables/zip`, `/resume`) are not wrapped; use the
canonical replacements (`wait()` / the Arbitr UI, `?format=zip`, `/resumptions`).

## Errors

Everything this package raises derives from `ArbitrBaseError`, so one `except`
is enough to be safe. Below it there are two branches:

| Branch | Raised when | Notable members |
|---|---|---|
| `ArbitrError` | the API returned a non-2xx response | `AuthenticationError`, `PaymentRequiredError`, `NotFoundError`, `ConflictError`, `ValidationError`, `RateLimitError`, `GoneError`, `ServerError` |
| `ArbitrClientError` | the call failed before or instead of an error envelope | `TransportError` (`ConnectionFailedError`, `RequestTimeoutError`), `ClientInputError`, `ActionRequiredError`, `ProjectWaitTimeoutError`, `ResponseParseError` |

`httpx` exceptions never escape the client — connection and timeout failures
arrive as `ConnectionFailedError` / `RequestTimeoutError` with the original
exception on `__cause__`.

```python
from arbitr import ArbitrBaseError, PaymentRequiredError

try:
    client.projects.resume(project_id)
except PaymentRequiredError as exc:
    print(f"short by {exc.shortfall} credits")
except ArbitrBaseError as exc:
    print(f"call failed: {exc}")
```

## Retries and rate limits

Retries are opt-in and off by default on the library client:

```python
client = ArbitrClient.from_env(max_retries=3)
```

The CLI retries GET up to 3 times (`--max-retries` / `ARBITR_MAX_RETRIES`).

Only GET is replayed — `Retry-After` is honoured on 429 and 5xx back off
exponentially (capped at 60s). `POST /v1/projects` is never retried
automatically because its multipart body streams file handles; pass
`idempotency_key=` and retry it yourself. After any call,
`client.rate_limit` holds the latest `X-RateLimit-*` values.

## Develop

```bash
uv sync
uv run pytest
uv run ruff check src tests scripts
uv run ty check
uv run python scripts/generate_models.py   # after refreshing the pinned spec
uv run python scripts/check_operation_coverage.py
```

Pin a fresh production spec:

```bash
curl -sS https://api-arbitr.straker.ai/openapi.json -o src/arbitr/openapi.json
uv run python scripts/generate_models.py
```

The snapshot ships inside the package, so an installed copy can diff itself
against a live host:

```python
from arbitr import pinned_spec

print(sorted(pinned_spec()["paths"]))
```

Do not edit `src/arbitr/generated/models.py` by hand.
