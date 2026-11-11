# Changelog

Notable changes to `arbitr-sdk`, in the style of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/); before 1.0, a minor release may
break.

## 0.6.0

### Breaking

- `ProjectResponse.target_language_codes` and `UsageRecord.target_language_codes`
  are `list[str | None]`: an entry is `None` when its language is no longer one
  `GET /v1/languages` lists. Code that joins or upper-cases the list must skip
  `None`.
- `ProjectResponse.source_language_code` can be `None`, for the same reason.
- `CreditBalanceResponse.intelligence_credits` and `trust_credits` are required.
  The API always returns them; a balance without them now raises
  `ResponseParseError` instead of reading as 0.

### Added

- Quote hold. `projects.submit(hold_for_quote=True)` creates a project that waits
  for a price. `projects.quote`, `projects.adjust_quote` and `projects.confirm`
  read the quote, drop files or languages from it, and start the work. Conflicts
  raise `NotOnHoldError`, `QuoteNotReadyError`, `QuoteChangedError`,
  `HoldExpiredError` and `AlreadyConfirmedError`.
- `projects.submit` takes `requester`, `archive_on_completion`, `notes` and
  `reference`, and `projects.confirm` takes `requester`. `reference` is your own
  id for the project: creating again with a reference your organisation already
  uses returns that project instead of creating another (test keys don't
  deduplicate), and one used by a project this key can't open is a 409
  `reference_in_use` `ConflictError`.
- CLI: `arbitr submit --hold-for-quote --reference`, `arbitr quote` (`--wait`
  polls while it is pricing and exits 1 if the quote expires), `arbitr adjust
  --remove FILE_ID:LANGUAGE` and `arbitr confirm`.
- Beta: webhook management on `client.webhooks`: `list`, `create`, `get`,
  `update`, `delete` (turns a webhook off), `test`, `deliveries` and `redeliver`,
  with models such as `WebhookResponse`, `WebhookCreateResponse` and
  `WebhookDelivery`. A key needs the `webhooks:manage` scope, which only an
  organisation admin or owner can grant.
- `parse_webhook_event` parses a delivered body into a typed `WebhookEvent`, and
  `KNOWN_EVENTS` lists the new project events, such as `project.hold_ready`,
  `project.confirmed`, `project.hold_expired` and the review events. Per-event
  payload models are in `arbitr.generated.models`.
- `reference` on `ProjectResponse`. `ref` and `target_language_code` on
  `ErrorDetail` name the reused `ref`, and the language it was charged for, on a
  `text.translate` conflict.

### Changed

- `TextToTranslate` no longer checks locale codes locally beyond length; the API
  checks them, as `text.translate` already documented.

### Fixed

- `arbitr wait`, `arbitr submit --wait` and `arbitr quote --wait` reject a
  negative `--timeout` or `--interval`, a `nan` timeout and an infinite interval
  (exit 2) instead of printing a traceback or never timing out. `--timeout inf`
  still waits forever.

## 0.5.0

### Breaking

- The `arbitr` CLI is now an optional extra: `pip install 'arbitr-sdk[cli]'`.
  Without it, the `arbitr` command prints the install hint and exits 1.
- The HTTP library is now `httpx2` instead of `httpx`. `transport=` must be an
  `httpx2` transport; passing an `httpx` one raises `ClientInputError`.
  `timeout=` accepts `httpx2.Timeout`. TLS verification uses the operating
  system trust store through `httpx2` instead of `certifi`. Tests that used
  `respx` should use `pytest-httpx2`.
- Bare locale codes are no longer refused locally. `projects.submit` and
  `text.translate` send codes as given and the API checks them, so
  `BareLocaleCodeError` is no longer raised; an unrecognised code comes back as
  a 422 `ValidationError`.
- Requires `pydantic` 2.5 or later.

### Added

- `text.translate` (`POST /v1/text/translate`).
- `usage.list` (`GET /v1/usage`).
- `connection()` (`GET /v1/connection`).
- `requester_tenant_id`, `requester_external_id` and `q` filters on
  `projects.list` and `projects.iterate`.
- A per-call `timeout=` on every method that makes a single request.
- Models for the new endpoints and the requester fields.
- Python 3.14 support.

### Fixed

- A finding whose kind this version does not know parses as `UnknownFinding`
  instead of failing the whole page.
- Path parameters are URL-encoded.
- `from_env()` no longer combines an API key from the environment with a base
  URL read only from a `.env` file.

## 0.4.2 and earlier

See the [GitHub releases](https://github.com/strakergroup/arbitr-python/releases).
