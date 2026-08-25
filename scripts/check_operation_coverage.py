"""Fail if a published OpenAPI operationId is missing from both clients.

The mapping tables live in ``arbitr._coverage`` so this script and
``tests/test_operation_coverage.py`` cannot drift apart.
"""

from __future__ import annotations

import asyncio
import sys

from arbitr import ArbitrClient, AsyncArbitrClient
from arbitr._coverage import (
    IGNORED_OPERATION_IDS,
    OPERATION_METHODS,
    audit_spec_mapping,
    missing_client_methods,
    published_operation_ids,
)


def _client_errors() -> list[str]:
    """Check both clients expose every mapped operation, closing them after."""
    errors: list[str] = []
    with ArbitrClient(api_key="abr_test_coverage") as sync_client:
        errors += [f"ArbitrClient missing {item}" for item in missing_client_methods(sync_client)]

    async def check_async() -> list[str]:
        async with AsyncArbitrClient(api_key="abr_test_coverage") as async_client:
            return [
                f"AsyncArbitrClient missing {item}" for item in missing_client_methods(async_client)
            ]

    return errors + asyncio.run(check_async())


def main() -> int:
    """Exit 1 when the snapshot and client methods drift."""
    errors = audit_spec_mapping().problems() + _client_errors()

    if errors:
        print("operation coverage failed:", file=sys.stderr)
        for line in errors:
            print(f"  {line}", file=sys.stderr)
        return 1
    ignored = len(published_operation_ids() & IGNORED_OPERATION_IDS)
    print(f"ok: {len(OPERATION_METHODS)} operations on both clients; {ignored} ignored aliases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
