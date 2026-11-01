# Arbitr Python

Official Python client and `arbitr` CLI for the [Arbitr External API](https://arbitr.apidocumentation.com/introduction).

## Install

```bash
pip install arbitr-sdk          # library
pip install 'arbitr-sdk[cli]'   # library and the arbitr command
```

The PyPI package is `arbitr-sdk`. The import and CLI stay `arbitr`. Python 3.11 or newer.
The `arbitr` command needs the `cli` extra; without it, it prints the install
hint and exits 1.

Mint a key at [https://app.arbitr.ai/settings/api-keys](https://app.arbitr.ai/settings/api-keys)
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

Default host is production: `https://api.arbitr.ai`, deep-linking to the UI at
`https://app.arbitr.ai`. The former `*-arbitr.straker.ai` hosts redirect; the
client does not follow redirects, so drop any `base_url` override still naming them.

Language codes are lowercase BCP-47 tags (`ko-kr`, `fr-fr`). Codes are sent as
given and the API checks them against `GET /v1/languages`; one it does not
recognise comes back as a 422 `ValidationError`. To pick an exact tag yourself,
use `client.languages.resolve(["ko"])` or `arbitr submit --resolve-locales`.

### Text translation

```python
from arbitr import TextToTranslate

result = client.text.translate(
    [TextToTranslate(ref="greeting-1", text="Hello", target_language_codes=["fr-fr"])],
)
for item in result.results:
    for t in item.translations:
        print(item.ref, t.target_language_code, t.status, t.text)
```

Up to 100 texts per call. Each text is charged once per `ref` and target
language, so retrying with the same refs is free.

### Usage, connection, and pagination

```python
usage = client.usage.list(from_="2026-10-01T00:00:00Z", to="2026-11-01T00:00:00Z")
conn = client.connection()  # the chat-app connection this key belongs to

for project in client.projects.iterate(status="completed"):
    print(project.id)
for finding in client.projects.iterate_findings(project_id):
    print(finding)
```

`projects.list` returns one page; `iterate` and `iterate_findings` follow the
pages for you.

### Webhooks

```python
from arbitr.webhooks import WebhookVerificationError, parse_event, verify_signature

try:
    verify_signature(
        body=raw_body,
        signature=headers.get("X-Arbitr-Signature"),
        timestamp=headers.get("X-Arbitr-Timestamp"),
        secret=webhook_secret,
    )
except WebhookVerificationError:
    ...  # reject the delivery
event = parse_event(raw_body)  # {"event": "project.completed", ...}
```

Pass the raw request bytes, not re-serialised JSON. Deliveries older than
`tolerance_seconds` (default 300) are refused.

The client wraps the **published** OpenAPI surface only. Former aliases
(agent-selection, `/deliverables/zip`, `/resume`) have been removed from the
API and answer `410 Gone`; this package already uses the canonical replacements
(`wait()` / the Arbitr UI, `?format=zip`, `/resumptions`).

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

`httpx2` exceptions never escape the client — connection and timeout failures
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

## Timeouts

The client's `timeout=` (default 60s) applies to every request. Each method
that makes a single request also takes its own `timeout=` for that call, so a
caller with a short deadline doesn't wait on the client's:

```python
balance = client.credits.balance(timeout=10)
```

Either `timeout=` also takes an `httpx2.Timeout`, for a connect timeout that
differs from the read timeout. The page iterators (`projects.iterate`,
`iterate_findings`) and `languages.resolve()` use the client's timeout, and
`projects.wait(timeout=)` is the overall polling deadline. A custom
`transport=` must be an `httpx2` transport, such as `httpx2.MockTransport` in
tests.

## Contributing

How changes reach this repository, the checks, and the release process are in
[CONTRIBUTING.md](https://github.com/strakergroup/arbitr-python/blob/master/CONTRIBUTING.md).
Changes per release are in [CHANGELOG.md](https://github.com/strakergroup/arbitr-python/blob/master/CHANGELOG.md);
to report a vulnerability, see [SECURITY.md](https://github.com/strakergroup/arbitr-python/blob/master/SECURITY.md).
