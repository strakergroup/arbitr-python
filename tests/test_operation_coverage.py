"""Every published operationId has a method on both clients, or is ignored.

The mapping tables live in ``arbitr._coverage`` and are shared with
``scripts/check_operation_coverage.py`` so the two cannot disagree.
"""

from __future__ import annotations

from arbitr import ArbitrClient, AsyncArbitrClient
from arbitr._coverage import (
    IGNORED_OPERATION_IDS,
    OPERATION_METHODS,
    audit_spec_mapping,
    missing_client_methods,
    published_operation_ids,
)


def test_snapshot_and_mapping_tables_agree() -> None:
    report = audit_spec_mapping()
    assert report.problems() == []
    assert report.ok


def test_sync_client_exposes_mapped_methods() -> None:
    with ArbitrClient(api_key="abr_test_coverage") as client:
        assert missing_client_methods(client) == []


async def test_async_client_exposes_mapped_methods() -> None:
    async with AsyncArbitrClient(api_key="abr_test_coverage") as client:
        assert missing_client_methods(client) == []


def test_ignored_aliases_are_still_published() -> None:
    """The ignore list only exists to excuse ids that are actually in the spec."""
    assert published_operation_ids() >= IGNORED_OPERATION_IDS


def test_deprecated_operations_are_never_wrapped() -> None:
    assert IGNORED_OPERATION_IDS.isdisjoint(OPERATION_METHODS)
