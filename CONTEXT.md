# Arbitr External API client

Python client and CLI for the public Arbitr External API. Terms here are the
customer-facing language of that API, not the internal product.

## Language

**Project**:
A translation job created by submitting source files and target languages.
Identified by a UUID. The client returns a `ProjectResponse` parsed from the
API JSON.
_Avoid_: Job, task, order, request

**Deliverable**:
One translated output file that belongs to a Project.
_Avoid_: Artifact, result, download (as a noun)

**Credit**:
Prepaid capacity consumed when a live API key submits a Project.
_Avoid_: Token, quota (use scope for key permissions)

**API key**:
Credential minted at https://arbitr.straker.ai/settings/api-keys. Live keys
spend credits; sandbox keys do not.
_Avoid_: Token, secret (except the webhook signing secret)

**Locale**:
A lowercased BCP-47 language tag such as `ja-jp` or `es-419`.
_Avoid_: Language name, bare ISO-639 (`ja`), mixed-case tags (`ja-JP`)

**Workflow**:
The processing path requested at submit. `AI_TRANSLATION` runs unattended.
_Avoid_: Pipeline, campaign (the UI name for starting agent selection)

**Action-required**:
A Project status that cannot advance without a human: `agent_selection` or
`awaiting_payment`. `wait()` raises rather than polling forever.
_Avoid_: Parked, blocked, stalled (except as informal description of the same)

**Resumption**:
A POST that continues a Project after the human action is done (credit top-up
or, for human review, a trust-credit top-up).
_Avoid_: Retry, restart, resume-as-new-submit

**Idempotency key**:
Caller-supplied key so a retried submit does not create a second Project.
_Avoid_: Request id (that is the API's error-envelope field)

**Webhook**:
An inbound signed delivery the API sends to a subscriber URL. This package
verifies signatures; it does not manage subscriptions.
_Avoid_: Callback, hook
