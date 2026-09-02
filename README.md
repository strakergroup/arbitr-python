# Arbitr Python

Official Python client and `arbitr` CLI for the [Arbitr External API](https://arbitr.apidocumentation.com/introduction).

## Install

```bash
pip install arbitr-sdk
```

The PyPI package is `arbitr-sdk`. The import and CLI stay `arbitr`. Python 3.11 or newer.

Mint a key at [https://arbitr.straker.ai/settings/api-keys](https://arbitr.straker.ai/settings/api-keys)
and store it as `ARBITR_API_KEY` in the environment or a `.env` file. Submit and
download need both `verify:submit` and `verify:read`. A test key (`abr_test_...`)
checks auth and request shape without running the pipeline or spending credits —
start there, then switch to a live key (`abr_live_...`). See
[Test mode](https://arbitr.apidocumentation.com/concepts/test-mode).

## Library

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

Default host is production: `https://api-arbitr.straker.ai`.

Language codes are lowercase BCP-47 tags (`ko-kr`, `fr-fr`). Bare codes (`ko`)
are rejected by the API — `client.languages.resolve(["ko"])` expands them, or
`arbitr submit --resolve-locales` does it for you.

The client wraps the **published** OpenAPI surface only. Deprecated aliases
(agent-selection, `/deliverables/zip`, `/resume`) are not wrapped; use the
canonical replacements (`wait()` / the Arbitr UI, `?format=zip`, `/resumptions`).

## CLI

```bash
export ARBITR_API_KEY=abr_live_...
arbitr me
arbitr submit report.docx --locales ko-kr,fr-fr --wait --out out/
```

`arbitr --help` and `arbitr COMMAND --help` are the command reference.

Exit codes:

| Code | Meaning |
|---|---|
| `0` | ok |
| `1` | the API returned an error (JSON envelope on stderr) |
| `2` | usage, config, network, or timeout failure |
| `3` | the project is waiting on a person — `agent_selection` (start the campaign in the Arbitr UI) or `awaiting_payment` (top up, then `arbitr resume`) — and cannot proceed until they act |

## Coding agents

Give your agent this prompt:

```text
Set up arbitr for me. Fetch https://arbitr.apidocumentation.com/getting-started/agent-setup/index.md and follow it.
```

It installs the CLI, pauses while you create and store a key, verifies access
with `arbitr me`, and installs the persistent skill. It does not submit a project.

Or install the [agent skill](https://arbitr.apidocumentation.com/getting-started/skill)
directly (source: `skills/arbitr/SKILL.md`):

```bash
npx -y skills add strakergroup/arbitr-python --skill arbitr --yes --global
```

To call the API as hosted tools instead of through the CLI, see
[MCP](https://arbitr.apidocumentation.com/getting-started/mcp).

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

## Contributing

Development setup, checks, and how to refresh the pinned OpenAPI spec are in
[CONTRIBUTING.md](https://github.com/strakergroup/arbitr-python/blob/master/CONTRIBUTING.md).
