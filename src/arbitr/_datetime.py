"""The timestamp type every generated model uses for ``format: date-time``.

``AwareDatetime`` would reject a naive ISO string outright, and a plain
``datetime`` would hand the caller a naive value that raises ``TypeError`` the
moment it is compared against an aware one. Both are worse than assuming UTC:
every timestamp the API returns is UTC, it just has not always carried the
offset. ``scripts/generate_models.py`` rewrites ``AwareDatetime`` to this.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def assume_utc(value: datetime) -> datetime:
    """Tag a naive timestamp as UTC; convert an aware one to UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(assume_utc)]
