# OpenAPI pin refresh + 0.2.2 release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-sync `arbitr-python`'s packaged OpenAPI pin with production, regenerate models, clear stale ignored operation ids, add `ConflictError.current_status`, and ship `arbitr-sdk` `0.2.2` to PyPI.

**Architecture:** Follow the existing pin → generate → coverage workflow already in this repo. No new HTTP methods. Schema drift is absorbed by regenerating `src/arbitr/generated/models.py`. One typed error accessor mirrors `PaymentRequiredError.shortfall` / `AuthenticationError.required_scope`. Release uses the existing GitHub `release` → trusted-publishing workflow.

**Tech Stack:** Python 3.11+, httpx, Pydantic v2, Hatch, uv, pytest, GitHub Actions publish workflow.

## Global Constraints

- Base branch: `origin/master` (this repo has no `main`).
- Pin source host only: `https://api-arbitr.straker.ai/openapi.json`.
- Do not hand-edit `src/arbitr/generated/`.
- Do not wrap retired/410 routes; clear `IGNORED_OPERATION_IDS` when those ops leave the pin.
- Version lives only in `src/arbitr/_version.py`; release tag must be `v0.2.2` matching `__version__`.
- Unit tests must not call the live API (except the intentional drift-check script / scheduled CI).
- Ticket: RAY-81825; design: `docs/superpowers/specs/2026-09-10-openapi-pin-refresh-design.md`.
- Distinguish deleted **routes** from live project **status** `agent_selection` — do not remove wait/CLI handling for that status.

---

## File map

| File | Role in this work |
| --- | --- |
| `src/arbitr/openapi.json` | Packaged pin; replace with live prod snapshot |
| `src/arbitr/generated/models.py` | Regenerated only via `scripts/generate_models.py` |
| `src/arbitr/_coverage.py` | Clear `IGNORED_OPERATION_IDS`; keep `OPERATION_METHODS` |
| `src/arbitr/errors.py` | Add `ConflictError.current_status` |
| `tests/test_errors.py` | TDD for `current_status` |
| `tests/test_operation_coverage.py` | Still valid with empty ignore set; update docstrings if they claim aliases are “still published” as a requirement beyond the empty-set math |
| `README.md`, `AGENTS.md` | Wording: retired routes are 410; SDK uses replacements |
| `src/arbitr/_version.py` | `0.2.1` → `0.2.2` |
| `docs/changelog/changelog.md`, `docs/overview.md` | Track the change |

---

### Task 1: `ConflictError.current_status`

**Files:**
- Modify: `src/arbitr/errors.py` (`ConflictError` class, ~lines 107–108)
- Test: `tests/test_errors.py` (add tests next to the payment-required / required-scope tests)

**Interfaces:**
- Consumes: `ArbitrError.extra` populated by `from_response()` (any envelope key not in `_ENVELOPE_META_KEYS`)
- Produces: `ConflictError.current_status -> str | None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_errors.py`:

```python
def test_conflict_exposes_current_status() -> None:
    handler = error_response(
        409,
        "not_awaiting_payment",
        current_status="translating",
    )
    with make_client(handler) as client, pytest.raises(ConflictError) as raised:
        client.projects.resume("p")
    assert raised.value.current_status == "translating"


def test_conflict_current_status_is_none_when_absent() -> None:
    handler = error_response(409, "conflict")
    with make_client(handler) as client, pytest.raises(ConflictError) as raised:
        client.me()
    assert raised.value.current_status is None


def test_conflict_current_status_ignores_non_string() -> None:
    handler = error_response(409, "not_awaiting_payment", current_status=123)
    with make_client(handler) as client, pytest.raises(ConflictError) as raised:
        client.projects.resume("p")
    assert raised.value.current_status is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/alex/Straker/arbitr/arbitr-python
uv run pytest tests/test_errors.py::test_conflict_exposes_current_status tests/test_errors.py::test_conflict_current_status_is_none_when_absent tests/test_errors.py::test_conflict_current_status_ignores_non_string -v
```

Expected: FAIL with `AttributeError: 'ConflictError' object has no attribute 'current_status'` (or similar).

- [ ] **Step 3: Implement the property**

Replace the bare `ConflictError` class in `src/arbitr/errors.py` with:

```python
class ConflictError(ArbitrError):
    """409 — e.g. Idempotency-Key reused with a different body.

    On ``not_awaiting_payment``, the API may include ``current_status`` naming
    the project's status when the conflict was detected.
    """

    @property
    def current_status(self) -> str | None:
        """Project status on ``not_awaiting_payment`` when the API sent it."""
        raw = self.extra.get("current_status")
        return raw if isinstance(raw, str) else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run the same pytest command as Step 2.

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/arbitr/errors.py tests/test_errors.py
git commit -m "$(cat <<'EOF'
Expose ConflictError.current_status from not_awaiting_payment 409s.

EOF
)"
```

---

### Task 2: Refresh pin, regenerate models, clear stale ignores

**Files:**
- Modify: `src/arbitr/openapi.json` (overwrite from prod)
- Modify: `src/arbitr/generated/models.py` (via generator only)
- Modify: `src/arbitr/_coverage.py` (empty `IGNORED_OPERATION_IDS`; update the comment that says deprecated aliases are still in the published spec)
- Modify: `tests/test_operation_coverage.py` (docstrings only if they claim ignores must be non-empty / still published as product intent — keep assertions; empty frozenset still satisfies `>=` and `isdisjoint`)

**Interfaces:**
- Consumes: live `https://api-arbitr.straker.ai/openapi.json`
- Produces: pin with 12 operations; `FindingType.repaired`; `ErrorDetail.current_status` in generated models; `IGNORED_OPERATION_IDS == frozenset()`

- [ ] **Step 1: Refresh the pin from production**

```bash
cd /home/alex/Straker/arbitr/arbitr-python
curl -sS https://api-arbitr.straker.ai/openapi.json -o src/arbitr/openapi.json
```

- [ ] **Step 2: Regenerate models**

```bash
uv run python scripts/generate_models.py
```

Expected: exits 0; `src/arbitr/generated/models.py` updates. Confirm `FindingType` includes `repaired`:

```bash
uv run python -c 'from arbitr.generated.models import FindingType; print(list(FindingType))'
```

Expected output includes `FindingType.repaired`.

- [ ] **Step 3: Clear `IGNORED_OPERATION_IDS`**

In `src/arbitr/_coverage.py`, replace the ignore block with:

```python
# Formerly ignored deprecated aliases (agent-selection, deliverables/zip,
# resume) have been removed from the published OpenAPI and answer 410 Gone.
# Keep this empty unless a new published-but-unwrapped id must be excused.
IGNORED_OPERATION_IDS: frozenset[str] = frozenset()
```

Leave `OPERATION_METHODS` unchanged.

Also update the module docstring / AGENTS cross-comment in this file if it still says those aliases “still in the published spec”.

- [ ] **Step 4: Update coverage test docstrings (assertions stay)**

In `tests/test_operation_coverage.py`, change:

```python
def test_ignored_aliases_are_still_published() -> None:
    """The ignore list only exists to excuse ids that are actually in the spec."""
    assert published_operation_ids() >= IGNORED_OPERATION_IDS


def test_deprecated_operations_are_never_wrapped() -> None:
    assert IGNORED_OPERATION_IDS.isdisjoint(OPERATION_METHODS)
```

to:

```python
def test_ignored_aliases_are_still_published() -> None:
    """Ignores must be a subset of published ids (empty ignore set is fine)."""
    assert published_operation_ids() >= IGNORED_OPERATION_IDS


def test_ignored_operations_are_never_wrapped() -> None:
    assert IGNORED_OPERATION_IDS.isdisjoint(OPERATION_METHODS)
```

- [ ] **Step 5: Verify pin + coverage**

```bash
uv run python scripts/check_pinned_spec.py
uv run python scripts/check_operation_coverage.py
uv run pytest tests/test_operation_coverage.py tests/test_pinned_spec_drift.py -q
```

Expected:
- `check_pinned_spec.py` exit 0 (pin matches live)
- `check_operation_coverage.py` exit 0 / no problems
- pytest PASS

If `check_pinned_spec.py` fails because prod moved again, re-run Step 1–2 before continuing.

- [ ] **Step 6: Smoke-parse `repaired` findings**

Append to `tests/test_response_parse.py` (already imports from `payloads`):

```python
from arbitr.generated.models import AgentFinding, FindingType
from payloads import agent_finding_json


def test_agent_finding_accepts_repaired_type() -> None:
    model = AgentFinding.model_validate(agent_finding_json(finding_type="repaired"))
    assert model.finding_type is FindingType.repaired
```

Run:

```bash
uv run pytest tests/test_response_parse.py::test_agent_finding_accepts_repaired_type -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/arbitr/openapi.json src/arbitr/generated/models.py src/arbitr/_coverage.py tests/test_operation_coverage.py tests/
git commit -m "$(cat <<'EOF'
Refresh OpenAPI pin from production and clear retired ignore ids.

EOF
)"
```

---

### Task 3: Docs wording, version bump, full verification

**Files:**
- Modify: `README.md` (lines ~51–53)
- Modify: `AGENTS.md` (surface-rules bullet about deprecated-ignored tables)
- Modify: `src/arbitr/_version.py`
- Modify: `docs/changelog/changelog.md`
- Modify: `docs/overview.md` (link the plan if missing)

**Interfaces:**
- Produces: `__version__ == "0.2.2"`; docs describe retired routes as 410 Gone

- [ ] **Step 1: Update README wording**

Replace:

```markdown
The client wraps the **published** OpenAPI surface only. Deprecated aliases
(agent-selection, `/deliverables/zip`, `/resume`) are not wrapped; use the
canonical replacements (`wait()` / the Arbitr UI, `?format=zip`, `/resumptions`).
```

with:

```markdown
The client wraps the **published** OpenAPI surface only. Former aliases
(agent-selection, `/deliverables/zip`, `/resume`) have been removed from the
API and answer `410 Gone`; this package already uses the canonical replacements
(`wait()` / the Arbitr UI, `?format=zip`, `/resumptions`).
```

Do **not** remove README/CLI mentions of project status `agent_selection` elsewhere — that status is still live.

- [ ] **Step 2: Update AGENTS.md coverage bullet**

Replace the bullet that says “mapped and deprecated-ignored operation tables” with wording that the mapping + optional ignore tables live in `_coverage.py`, and ignores must stay empty unless a published id is deliberately left unwrapped.

Example:

```markdown
- Wrap **published** OpenAPI operations only. The mapped operation table and
  optional ignore set live in `src/arbitr/_coverage.py` and are shared by
  `scripts/check_operation_coverage.py` and `tests/test_operation_coverage.py`
  — edit them in that one place. Prefer an empty ignore set; only add an id
  when it is still published but must not grow a wrapper.
```

- [ ] **Step 3: Bump version**

In `src/arbitr/_version.py`:

```python
__version__ = "0.2.2"
```

- [ ] **Step 4: Changelog + overview**

Add to `docs/changelog/changelog.md`:

```markdown
- [Changed]: Refresh OpenAPI pin for production drift, clear retired ignore ids, add ConflictError.current_status, release 0.2.2 (Alex Zhao, 2026-09-10)
```

Ensure `docs/overview.md` indexes this plan under Specs/Plans.

- [ ] **Step 5: Full local verification**

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run ty check
uv run pytest
uv run python scripts/check_operation_coverage.py
uv run python scripts/check_pinned_spec.py
uv run python -c 'import arbitr; assert arbitr.__version__ == "0.2.2"'
```

Expected: all exit 0 / green.

- [ ] **Step 6: Commit**

```bash
git add README.md AGENTS.md src/arbitr/_version.py docs/changelog/changelog.md docs/overview.md
git commit -m "$(cat <<'EOF'
Bump arbitr-sdk to 0.2.2 and document retired OpenAPI aliases.

EOF
)"
```

---

### Task 4: Merge and publish `v0.2.2`

**Files:**
- None in-repo beyond what Tasks 1–3 already committed
- Remote: GitHub release tag `v0.2.2` triggers `.github/workflows/publish.yml`

**Interfaces:**
- Consumes: `__version__ == "0.2.2"` on `master`
- Produces: PyPI package `arbitr-sdk==0.2.2`

- [ ] **Step 1: Open / merge PR to `master`**

Push the feature branch, open a PR against `master`, wait for CI (including any scheduled/pinned-spec job that applies). Merge only when green.

Re-run immediately before merge if needed:

```bash
uv run python scripts/check_pinned_spec.py
```

Expected: exit 0.

- [ ] **Step 2: Create the GitHub release**

After merge, on `master`:

```bash
git checkout master
git pull origin master
gh release create v0.2.2 --title "v0.2.2" --notes "$(cat <<'EOF'
## arbitr-sdk 0.2.2

- Refresh packaged OpenAPI pin to match production
- Regenerate models (`FindingType.repaired`, `ErrorDetail.current_status`)
- Clear stale ignored operation ids for routes that now return 410 Gone
- Add `ConflictError.current_status` for `not_awaiting_payment` conflicts

EOF
)"
```

Expected: publish workflow runs; tag check passes (`v0.2.2` == `0.2.2`); package uploads to PyPI.

- [ ] **Step 3: Verify publish**

```bash
gh run list --workflow=publish.yml --limit 3
pip index versions arbitr-sdk | head
# or:
curl -sS https://pypi.org/pypi/arbitr-sdk/json | python -c 'import sys,json; print(json.load(sys.stdin)["info"]["version"])'
```

Expected: latest version `0.2.2`.

- [ ] **Step 4: Close out the ticket**

Comment on RAY-81825 with the PR URL and PyPI version; mark done when publish is confirmed.

---

## Self-review (plan vs spec)

| Spec requirement | Task |
| --- | --- |
| Refresh pin from prod | Task 2 |
| Regenerate models | Task 2 |
| Clear stale `IGNORED_OPERATION_IDS` | Task 2 |
| `ConflictError.current_status` | Task 1 |
| README/AGENTS wording for retired routes | Task 3 |
| Version `0.2.2` + GitHub release / PyPI | Task 3 + Task 4 |
| Coverage / pin-drift tests green | Task 2 + Task 3 |
| No new client methods / no agent_selection status removal | Global Constraints |

Placeholder scan: none. `agent_finding_json` is the exact factory in `tests/payloads.py`.
