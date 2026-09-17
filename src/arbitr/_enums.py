"""The open enum base ``scripts/generate_models.py`` gives every generated enum.

A closed ``StrEnum`` would make each value Arbitr adds a breaking change for
already-installed clients, and findings are a discriminated union, so one
unknown value fails a whole page.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class TolerantStrEnum(StrEnum):
    """A ``StrEnum`` that accepts values it was not generated with."""

    @classmethod
    def _missing_(cls, value: object) -> TolerantStrEnum | None:
        if not isinstance(value, str):
            return None
        # Not registered in ``_value2member_map_``: iteration and ``__members__``
        # stay the pinned spec, and unseen values cannot grow the class.
        unknown = str.__new__(cls, value)
        unknown._name_ = value
        unknown._value_ = str(value)
        return unknown

    @classmethod
    def is_known(cls, value: Any) -> bool:
        """Whether ``value`` is a member this build of the SDK was generated with."""
        return value in cls._value2member_map_
