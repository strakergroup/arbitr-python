"""The public surface of ``arbitr``: every exported name resolves, and every
type a caller can reach through an exported model is exported too.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, get_args

import pytest
from pydantic import BaseModel

import arbitr
from arbitr import generated

GENERATED_MODULE = "arbitr.generated.models"


def _referenced_types(annotation: Any) -> Iterator[type]:
    """Every class mentioned anywhere in an annotation, unions and generics included."""
    if isinstance(annotation, type):
        yield annotation
    for arg in get_args(annotation):
        yield from _referenced_types(arg)


def _exported_models() -> Iterator[type[BaseModel]]:
    for name in arbitr.__all__:
        value = getattr(arbitr, name)
        if isinstance(value, type) and issubclass(value, BaseModel):
            yield value


@pytest.mark.parametrize("name", sorted(arbitr.__all__))
def test_every_exported_name_resolves(name: str) -> None:
    assert hasattr(arbitr, name), f"arbitr.__all__ lists {name}, which does not exist"


def test_all_has_no_duplicates() -> None:
    # Ordering is ruff's RUF022 job; this only guards against a repeated name.
    assert len(arbitr.__all__) == len(set(arbitr.__all__))
    assert len(generated.__all__) == len(set(generated.__all__))


def test_generated_reexports_match_the_package() -> None:
    """Anything ``arbitr.generated`` exports must also come off ``arbitr``."""
    assert set(generated.__all__) <= set(arbitr.__all__)


def test_types_reachable_from_exported_models_are_exported() -> None:
    """A caller who holds an exported model must be able to name its parts.

    Reaching into ``arbitr.generated.models`` for the element type of a list
    field, or for the enum on a status field, means the export list is short.
    """
    missing = {
        f"{model.__name__}.{field_name} -> {referenced.__name__}"
        for model in _exported_models()
        for field_name, field in model.model_fields.items()
        for referenced in _referenced_types(field.annotation)
        if referenced.__module__ == GENERATED_MODULE and referenced.__name__ not in arbitr.__all__
    }
    assert not missing, f"reachable but not exported: {sorted(missing)}"
