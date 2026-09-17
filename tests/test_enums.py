"""The tolerant base every generated enum uses — unknown values must not raise."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from arbitr._enums import TolerantStrEnum


class Colour(TolerantStrEnum):
    red = "red"
    green = "green"


class Wrapper(BaseModel):
    colour: Colour


def test_known_value_is_the_declared_member() -> None:
    assert Colour("red") is Colour.red


def test_unknown_value_is_accepted() -> None:
    assert Colour("mauve") == "mauve"


def test_unknown_value_keeps_the_value_and_the_type() -> None:
    unknown = Colour("mauve")
    assert isinstance(unknown, Colour)
    assert unknown.value == "mauve"
    assert unknown.name == "mauve"


def test_unknown_value_hashes_as_its_string() -> None:
    lookup: dict[str, int] = {Colour("mauve"): 1}
    assert lookup["mauve"] == 1


def test_unknown_value_does_not_join_the_members() -> None:
    Colour("mauve")
    assert list(Colour) == [Colour.red, Colour.green]
    assert set(Colour.__members__) == {"red", "green"}


def test_unknown_value_is_not_reachable_by_attribute() -> None:
    Colour("mauve")
    assert not hasattr(Colour, "mauve")


def test_non_string_is_still_rejected() -> None:
    with pytest.raises(ValueError, match="is not a valid Colour"):
        Colour(7)


def test_is_known_separates_declared_members_from_unknown_ones() -> None:
    assert Colour.is_known("red") is True
    assert Colour.is_known(Colour.red) is True
    assert Colour.is_known("mauve") is False
    assert Colour.is_known(Colour("mauve")) is False


def test_model_validate_accepts_an_unknown_value() -> None:
    assert Wrapper.model_validate({"colour": "mauve"}).colour == "mauve"


def test_model_validate_json_accepts_an_unknown_value() -> None:
    # pydantic's JSON path calls ``_missing_`` with None before the real value
    # (pydantic#12960), so a shim that assumes a str breaks only on this path.
    assert Wrapper.model_validate_json('{"colour": "mauve"}').colour == "mauve"


def test_unknown_value_serializes_back_to_its_string() -> None:
    assert Wrapper.model_validate({"colour": "mauve"}).model_dump(mode="json") == {
        "colour": "mauve"
    }
