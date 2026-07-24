"""Tests for reusable CAD features."""

import cadquery as cq
import pytest

from zcad.features.holes import add_through_holes
from zcad.features.labels import add_embossed_label
from zcad.features.slots import cut_through_slot


def test_through_hole_reduces_volume() -> None:
    base = cq.Workplane("XY").box(
        20,
        20,
        5,
    )

    result = add_through_holes(
        base,
        points=[(0, 0)],
        diameter=4,
    )

    assert result.val().isValid()
    assert result.val().Volume() < base.val().Volume()


@pytest.mark.parametrize(
    ("points", "diameter"),
    [
        ([], 4),
        ([(0, 0)], 0),
        ([(0, 0)], -1),
    ],
)
def test_invalid_hole_inputs_are_rejected(
    points: list[tuple[float, float]],
    diameter: float,
) -> None:
    base = cq.Workplane("XY").box(
        20,
        20,
        5,
    )

    with pytest.raises(ValueError):
        add_through_holes(
            base,
            points=points,
            diameter=diameter,
        )


def test_embossed_label_increases_height() -> None:
    base = cq.Workplane("XY").box(
        30,
        20,
        4,
    )

    result = add_embossed_label(
        base,
        text="A1",
        x=0,
        y=0,
        base_height=4,
        text_size=4,
        emboss_height=0.6,
    )

    bounds = result.val().BoundingBox()

    assert result.val().isValid()
    assert bounds.zlen > 4


@pytest.mark.parametrize(
    ("text", "base_height", "text_size", "emboss_height"),
    [
        ("", 4, 3, 0.6),
        ("A", 0, 3, 0.6),
        ("A", 4, 0, 0.6),
        ("A", 4, 3, 0),
    ],
)
def test_invalid_label_inputs_are_rejected(
    text: str,
    base_height: float,
    text_size: float,
    emboss_height: float,
) -> None:
    base = cq.Workplane("XY").box(
        30,
        20,
        4,
    )

    with pytest.raises(ValueError):
        add_embossed_label(
            base,
            text=text,
            x=0,
            y=0,
            base_height=base_height,
            text_size=text_size,
            emboss_height=emboss_height,
        )


def test_through_slot_reduces_volume() -> None:
    base = cq.Workplane("XY").box(
        30,
        20,
        5,
    )

    result = cut_through_slot(
        base,
        x=0,
        y=0,
        length=12,
        width=4,
        base_height=5,
    )

    assert result.val().isValid()
    assert result.val().Volume() < base.val().Volume()


@pytest.mark.parametrize(
    (
        "length",
        "width",
        "base_height",
    ),
    [
        (0, 4, 5),
        (12, 0, 5),
        (12, 4, 0),
        (4, 4, 5),
        (3, 4, 5),
    ],
)
def test_invalid_slot_inputs_are_rejected(
    length: float,
    width: float,
    base_height: float,
) -> None:
    base = cq.Workplane("XY").box(
        30,
        20,
        5,
    )

    with pytest.raises(ValueError):
        cut_through_slot(
            base,
            x=0,
            y=0,
            length=length,
            width=width,
            base_height=base_height,
        )
