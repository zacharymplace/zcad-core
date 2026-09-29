"""Lid options: countersinks, a locating lip, a snap-fit lid, and vents."""

from __future__ import annotations

from functools import cache

import cadquery as cq
import pytest

from zcad_core.assemblies import DeviceAssembly, Placement, build_board_assembly
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
from zcad_core.features.enclosure_lid import (
    GROOVE_DEPTH_MM,
    RIDGE_DROP_MM,
    SKIRT_FIT_MM,
    SKIRT_THICKNESS_MM,
    VENT_WIDTH_MM,
)
from zcad_core.features.enclosure_trial import (
    EnclosureCheck,
    applicable_checks,
    nominal_measurements,
)
from zcad_core.hardware import get_board

BOARD = get_board("RASPBERRY_PI_PICO_2")


def assembly() -> DeviceAssembly:
    return build_board_assembly(
        board=BOARD, board_placement=Placement(), connector_access_clearance_mm=2.0
    )


@cache
def built(**settings: object) -> Enclosure:
    return build_enclosure(
        assembly(),
        board=BOARD,
        design=EnclosureDesign(**settings),  # type: ignore[arg-type]
    )


def solid(model: cq.Workplane) -> cq.Solid:
    (only,) = model.solids().vals()
    assert isinstance(only, cq.Solid)
    return only


def top(enclosure: Enclosure) -> float:
    spec = enclosure.specification
    return spec.bottom_z_mm + spec.inner_height_mm


def long_wall_face(enclosure: Enclosure) -> tuple[str, float]:
    """The axis the long walls face, and the +side wall's inner face."""
    spec = enclosure.specification

    if spec.inner_width_mm >= spec.inner_depth_mm:
        return "y", spec.center_y_mm + spec.inner_depth_mm / 2

    return "x", spec.center_x_mm + spec.inner_width_mm / 2


def point(axis: str, across: float, along: float, z: float) -> cq.Vector:
    return cq.Vector(along, across, z) if axis == "y" else cq.Vector(across, along, z)


def test_countersinks_widen_the_top_of_each_lid_hole() -> None:
    plain = solid(built().lid)
    sunk = solid(built(countersunk_screws=True).lid)
    enclosure = built()
    x, y = enclosure.fastener_positions[0]
    # Between the 3.4 mm hole and the 6 mm head, just under the lid's top.
    probe = cq.Vector(x + 2.4, y, top(enclosure) + enclosure.design.lid_mm - 0.1)

    assert plain.isInside(probe)
    assert not sunk.isInside(probe)


def test_countersink_needs_a_thick_enough_lid() -> None:
    with pytest.raises(ValueError, match="needs a lid at least 1.9 mm thick"):
        built(countersunk_screws=True, lid_mm=1.6)


def test_locating_lip_hangs_inside_the_walls_clear_of_the_bosses() -> None:
    enclosure = built(locating_lip=True)
    lid = solid(enclosure.lid)
    axis, face = long_wall_face(enclosure)
    inside = face - SKIRT_FIT_MM - SKIRT_THICKNESS_MM / 2

    assert lid.isInside(point(axis, inside, 0.0, top(enclosure) - 1.0))
    for x, y in enclosure.fastener_positions:
        assert not lid.isInside(cq.Vector(x, y, top(enclosure) - 1.0))


def test_snap_lid_has_no_screws_and_clicks_into_grooves() -> None:
    enclosure = built(lid_attachment="snap")
    base, lid = solid(enclosure.base), solid(enclosure.lid)
    axis, face = long_wall_face(enclosure)
    ridge_z = top(enclosure) - RIDGE_DROP_MM

    assert enclosure.fastener_positions == ()
    # The ridge reaches past the skirt's gap into the wall's groove.
    assert lid.isInside(point(axis, face + 0.1, 0.0, ridge_z))
    assert not base.isInside(point(axis, face + 0.1, 0.0, ridge_z))
    assert base.isInside(point(axis, face + GROOVE_DEPTH_MM + 0.1, 0.0, ridge_z))


def test_snap_lid_trials_skip_the_inserts() -> None:
    enclosure = built(lid_attachment="snap")

    assert EnclosureCheck.INSERTS_INSTALLED not in applicable_checks(enclosure)
    assert "lid_hole_diameter_mm" not in nominal_measurements(enclosure, None)


def test_vents_cut_the_long_walls_but_not_the_cable_wall() -> None:
    enclosure = built(vent_slots=3)
    base = solid(enclosure.base)
    axis, face = long_wall_face(enclosure)
    spec = enclosure.specification
    # The middle slot is centred along the wall, below the rim.
    along = spec.center_x_mm if axis == "y" else spec.center_y_mm
    mid_z = top(enclosure) - 3.0
    wall_mid = face + enclosure.design.wall_mm / 2
    slot = point(axis, wall_mid, along, mid_z)
    between = point(axis, wall_mid, along + VENT_WIDTH_MM, mid_z)

    assert spec.cable_edge not in ("negative_" + axis, "positive_" + axis)
    assert not base.isInside(slot)
    assert base.isInside(between)
    assert solid(built().base).isInside(slot)


def test_vents_refuse_what_does_not_fit() -> None:
    with pytest.raises(ValueError, match="do not fit between the corners"):
        built(vent_slots=40)


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        ({"lid_attachment": "glue"}, "lid_attachment must be one of"),
        (
            {"lid_attachment": "snap", "countersunk_screws": True},
            "no screws to countersink",
        ),
        ({"lid_attachment": "snap", "locating_lip": True}, "already locates"),
        ({"vent_slots": -1}, "vent_slots must not be negative"),
    ],
)
def test_design_rejects_contradictory_lid_settings(
    settings: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        EnclosureDesign(**settings).validate()  # type: ignore[arg-type]
