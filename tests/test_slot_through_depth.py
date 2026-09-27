"""Through-depth and analytic volume regression for the shared slot cutter."""

import math

import cadquery as cq
import pytest

from zcad_core.features.slots import cut_through_slot


@pytest.mark.parametrize("height", [1.0, 4.0, 7.5])
@pytest.mark.parametrize("angle", [0, 45, 90])
@pytest.mark.parametrize("bottom_based", [False, True])
def test_full_depth_and_exact_slot_volume(height, angle, bottom_based):
    base = cq.Workplane("XY").box(40, 40, height)
    bottom = -height / 2
    if bottom_based:
        base = base.translate((0, 0, height / 2))
        bottom = 0
    result = cut_through_slot(
        base, x=2, y=-3, length=12, width=4, base_height=height, angle=angle
    ).val()
    assert result.isValid()
    assert len(result.Solids()) == 1
    area = (12 - 4) * 4 + math.pi * 2**2
    assert base.val().Volume() - result.Volume() == pytest.approx(area * height)
    for fraction in (0.01, 0.25, 0.5, 0.75, 0.99):
        assert not result.isInside(cq.Vector(2, -3, bottom + fraction * height))
    assert result.isInside(cq.Vector(15, 15, bottom + height / 2))
