# Design: Refresh arbitr-python OpenAPI pin and release 0.2.2

**Date:** 2026-09-10  
**Ticket:** [RAY-81825](https://app.clickup.com/t/86d4ac4hz) (epic [RAY-81435](https://app.clickup.com/t/36600298/RAY-81435))  
**Repo:** `arbitr-python` (PyPI: `arbitr-sdk`)  
**Branch base:** `origin/master` @ `25014a6`

## Problem

The packaged OpenAPI pin (`src/arbitr/openapi.json`) has drifted from production (`https://api-arbitr.straker.ai/openapi.json`). CI `scripts/check_pinned_spec.py` fails (exit 1). Callers who install from PyPI still get the older pin and generated models.

## Observed drift (as of 2026-09-10)

| Area | Change |
| --- | --- |
| Routes | Live OpenAPI dropped 6 formerly deprecated operations still listed in the pin: `getAgentSelection`, `submitAgentSelection`, `downloadDeliverablesZip`, `downloadDeliverable`, `resumeProject`, `resumeHumanReview` |
| Schema | `AgentFinding.finding_type` enum gains `repaired` |
| Schema | `ErrorDetail` gains optional `current_status` (used on `not_awaiting_payment` 409s) |
| Docs text | Locale examples and retirement wording updated in the OpenAPI `info.description` |
| New ops | None — live has 12 operations; pin still has 18 |

The SDK never wrapped the six removed routes (`IGNORED_OPERATION_IDS`). Canonical replacements are already used (`wait()` / UI, `?format=zip`, `/resumptions`).

## Goals

1. Re-sync the pin with production and regenerate models.
2. Keep operation-coverage rules honest after the removals.
3. Expose `ConflictError.current_status` for the new error field.
4. Ship a patch release **`0.2.2`** to PyPI (version bump + GitHub release `v0.2.2`).

## Non-goals

- Adding new client methods (no new published operations).
- Changing wait/CLI behavior for project status `agent_selection` (still a live project status; unrelated to the deleted agent-selection **routes**).
- Calling or wrapping any route that now returns 410 Gone.
- Changes outside this repository (API backend, docs portal).

## Approach

Minimal refresh + patch release (Approach 1 from brainstorming).

### Steps

1. **Refresh pin**  
   `curl -sS https://api-arbitr.straker.ai/openapi.json -o src/arbitr/openapi.json`

2. **Regenerate models**  
   `uv run python scripts/generate_models.py`  
   Do not hand-edit `src/arbitr/generated/`.

3. **Coverage tables**  
   Clear `IGNORED_OPERATION_IDS` (empty frozenset or equivalent). Leaving the old ids fails `stale_ignores` in `audit_spec_mapping()`.  
   Leave `OPERATION_METHODS` unchanged.

4. **Error ergonomics**  
   Add `ConflictError.current_status -> str | None` reading from `extra`, matching existing accessors (`PaymentRequiredError.shortfall`, `AuthenticationError.required_scope`).

5. **Docs wording**  
   Update README / AGENTS lines that say deprecated aliases “are not wrapped” so they state those routes are **retired (410 Gone)** and the SDK already uses the canonical replacements.

6. **Version**  
   Set `src/arbitr/_version.py` `__version__ = "0.2.2"` only (Hatch reads this path).

7. **Release**  
   Merge to `master`, publish GitHub release tagged `v0.2.2`. Existing `.github/workflows/publish.yml` verifies tag == package version and publishes via trusted publishing.

## Semver rationale

Patch `0.2.1` → `0.2.2`: additive schema only (new enum value, optional error field); no breaking client surface. Removed OpenAPI operations were never wrapped.

## Testing

- `uv run python scripts/check_pinned_spec.py` exits 0 after refresh.
- `uv run python scripts/check_operation_coverage.py` and `tests/test_operation_coverage.py` pass with empty ignores.
- Unit test: 409 envelope with `current_status` populates `ConflictError.current_status`; absent field yields `None`.
- Optional smoke: findings payload with `finding_type: "repaired"` parses via generated models.
- Full suite: `uv run pytest`, ruff, ty — no live API calls in unit CI.
- Publish gate: release tag `v0.2.2` must match `__version__`.

## Risks

| Risk | Mitigation |
| --- | --- |
| Stale ignore ids fail coverage after pin refresh | Clear `IGNORED_OPERATION_IDS` in the same change |
| Confusing deleted routes with status `agent_selection` | Docs explicitly distinguish route retirement vs project status |
| Pin changes again before merge | Re-run drift check immediately before merge/release |

## Success criteria

- [ ] Packaged pin matches production (canonicalize/diff clean)
- [ ] Generated models regenerated from the new pin
- [ ] Coverage audit green with no stale ignores
- [ ] `ConflictError.current_status` implemented and tested
- [ ] README/AGENTS wording updated for retired routes
- [ ] `__version__` is `0.2.2` and GitHub release `v0.2.2` publishes `arbitr-sdk` to PyPI
