# Changelog

Notable changes to `arbitr-sdk`, in the style of
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow
[Semantic Versioning](https://semver.org/); before 1.0, a minor release may
break.

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
