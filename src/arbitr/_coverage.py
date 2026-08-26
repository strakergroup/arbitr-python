"""Published-surface coverage rules, shared by the CI script and the test suite.

Single source of truth for which OpenAPI operations this package wraps. Both
``scripts/check_operation_coverage.py`` and ``tests/test_operation_coverage.py``
read these tables, so a new operation cannot be half-registered.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arbitr._spec import pinned_spec

# Deprecated aliases still in the published spec. The canonical replacements
# are implemented; these ids must not grow a wrapper.
IGNORED_OPERATION_IDS = frozenset(
    {
        "getAgentSelection",
        "submitAgentSelection",
        "downloadDeliverablesZip",
        "downloadDeliverable",
        "resumeProject",
        "resumeHumanReview",
    }
)

# operationId -> dotted attribute on ArbitrClient / AsyncArbitrClient
OPERATION_METHODS: dict[str, str] = {
    "getCurrentKey": "me",
    "createProject": "projects.submit",
    "listProjects": "projects.list",
    "getProject": "projects.get",
    "listDeliverables": "projects.deliverables",
    "getDeliverable": "projects.deliverable",
    "listProjectFindings": "projects.findings",
    "getProjectChainOfCustody": "projects.chain_of_custody",
    "createProjectResumption": "projects.resume",
    "createReviewResumption": "projects.resume_human_review",
    "listLanguages": "languages.list",
    "getCreditBalance": "credits.balance",
}

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "patch", "head", "options", "trace"})


def published_operation_ids() -> set[str]:
    """Every operationId in the pinned snapshot."""
    ids: set[str] = set()
    paths = pinned_spec().get("paths")
    if not isinstance(paths, dict):
        return ids
    for item in paths.values():
        if not isinstance(item, dict):
            continue
        for name, op in item.items():
            if name.lower() in _HTTP_METHODS and isinstance(op, dict) and "operationId" in op:
                ids.add(str(op["operationId"]))
    return ids


def resolve_attr(root: object, dotted: str) -> object:
    """Walk a dotted attribute path, raising AttributeError if any part is missing."""
    current = root
    for part in dotted.split("."):
        current = getattr(current, part)
    return current


@dataclass(frozen=True)
class CoverageReport:
    """Drift between the pinned snapshot and the mapping tables."""

    unmapped: list[str] = field(default_factory=list)
    """Published operationIds that are neither mapped nor ignored."""

    unpublished: list[str] = field(default_factory=list)
    """Mapped operationIds absent from the snapshot."""

    stale_ignores: list[str] = field(default_factory=list)
    """Ignored operationIds absent from the snapshot."""

    wrapped_ignores: list[str] = field(default_factory=list)
    """Ignored operationIds that wrongly grew a method mapping."""

    @property
    def ok(self) -> bool:
        """True when the snapshot and the tables agree."""
        return not (self.unmapped or self.unpublished or self.stale_ignores or self.wrapped_ignores)

    def problems(self) -> list[str]:
        """Human-readable lines describing each drift, empty when ``ok``."""
        lines: list[str] = []
        if self.unmapped:
            lines.append(f"published operationIds with no method mapping: {self.unmapped}")
        if self.unpublished:
            lines.append(f"mapped operationIds not in the snapshot: {self.unpublished}")
        if self.stale_ignores:
            lines.append(f"ignored operationIds not in the snapshot: {self.stale_ignores}")
        if self.wrapped_ignores:
            lines.append(f"ignored operationIds must not be wrapped: {self.wrapped_ignores}")
        return lines


def audit_spec_mapping() -> CoverageReport:
    """Compare the pinned snapshot against the mapping tables."""
    published = published_operation_ids()
    mapped = set(OPERATION_METHODS)
    return CoverageReport(
        unmapped=sorted(published - IGNORED_OPERATION_IDS - mapped),
        unpublished=sorted(mapped - published),
        stale_ignores=sorted(IGNORED_OPERATION_IDS - published),
        wrapped_ignores=sorted(IGNORED_OPERATION_IDS & mapped),
    )


def missing_client_methods(client: object) -> list[str]:
    """Mapped operations whose dotted attribute is missing or not callable."""
    missing: list[str] = []
    for op_id, dotted in sorted(OPERATION_METHODS.items()):
        try:
            attr = resolve_attr(client, dotted)
        except AttributeError:
            missing.append(f"{dotted} (operationId {op_id})")
            continue
        if not callable(attr):
            missing.append(f"{dotted} is not callable (operationId {op_id})")
    return missing
