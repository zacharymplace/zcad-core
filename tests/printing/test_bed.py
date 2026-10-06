"""How a print copy sits on the bed, and when it is sliced with supports."""

from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.printing.bed import MINIMUM_BED_SHARE, bed_contact, laid_flat


def box(
    x: float, y: float, z: float, at: tuple[float, float, float] = (0, 0, 0)
) -> cq.Workplane:
    return cq.Workplane("XY").box(x, y, z, centered=(True, True, False)).translate(at)


def test_a_plain_box_lies_wholly_on_the_bed() -> None:
    contact = bed_contact(workplane_shape(box(40, 30, 10)))

    assert contact.share == pytest.approx(1.0)
    assert not contact.needs_support


def test_a_panel_on_four_pads_needs_supports() -> None:
    # A 40 x 30 floor standing 4.5 mm up on four 6 mm pads, as a base with mount
    # pads lies on its floor.
    panel = box(40, 30, 2, at=(0, 0, 4.5))

    for x in (-15, 15):
        for y in (-10, 10):
            panel = panel.union(box(6, 6, 4.5, at=(x, y, 0)))

    contact = bed_contact(workplane_shape(panel))

    assert contact.share < MINIMUM_BED_SHARE
    assert contact.needs_support


def test_a_plate_is_laid_on_its_flattest_face() -> None:
    # Built standing on its edge; laid flat it lies on its 40 x 30 face.
    plate = workplane_shape(box(40, 2, 30))
    flat = laid_flat(plate)

    assert bed_contact(plate).on_bed_mm2 == pytest.approx(80.0)
    assert bed_contact(flat).on_bed_mm2 == pytest.approx(1200.0)


def test_a_part_already_flat_is_kept_as_built() -> None:
    plate = workplane_shape(box(40, 30, 2))

    assert laid_flat(plate) is plate
