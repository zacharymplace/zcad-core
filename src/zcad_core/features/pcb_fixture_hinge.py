"""The hinged closure's geometry: the pin and catch on the nest and the plate.

The plate hinges on the nest's positive long wall and closes on a snap catch on
the negative one, both built by :func:`zcad_core.features.lid_hinge.add_hinge`,
which is the enclosure's hinge. Here the nest is its base and the plate its lid:
the plate stands on the nest's rim, so the cavity's top is the rim and the lid's
thickness is the plate's.

What the plate carries swings with it. Each pin hangs from the plate down to its
pad, ten millimetres or more below the pin's axis, so swinging the plate swings
every pin through an arc that can meet a part beside its pad, the nest's wall, or
a post. The hinge sweeps the plate and the pins open in steps, against the nest
and the board and its parts, and the build is refused if anything meets.

The nest's finger notch is moved off the middle of the catch's wall, by
:func:`zcad_core.features.pcb_fixture_closure.hinge_notch_offset`, and the hinge
wall has none; the notch is passed to the hinge as an opening so the catch goes
to the widest stretch clear of it.
"""

from __future__ import annotations

from collections.abc import Mapping

import cadquery as cq

from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_hinge import HingeReport, add_hinge
from zcad_core.features.pcb_fixture_closure import (
    NOTCH_RADIUS_MM,
    ClosurePlan,
    hinge_notch_offset,
    hinge_walls,
    window_spans,
)
from zcad_core.features.pcb_fixture_plan import FixturePlan
from zcad_core.hardware.electronics.board_file import BoardFileSpec
from zcad_core.hardware.fasteners import get_fastener


def _cavity(board: BoardFileSpec, plan: FixturePlan) -> Cavity:
    """The nest's cavity as the hinge sees it: the board and its clearance, with
    the rim as its top."""

    return Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=board.board_width_mm + 2 * plan.clearance_mm,
        depth_mm=board.board_length_mm + 2 * plan.clearance_mm,
        floor_z_mm=-board.board_thickness_mm - plan.under_depth_mm,
        top_z_mm=plan.plate_underside_mm,
        wall_mm=plan.nest_wall_mm,
    )


def _opening(edge: str, low: float, high: float) -> ConnectorCutoutParameters:
    return ConnectorCutoutParameters(
        edge=edge,  # type: ignore[arg-type]
        center_offset_mm=(low + high) / 2,
        bottom_z_mm=0.0,
        width_mm=high - low,
        height_mm=1.0,
        width_clearance_mm=0.0,
    )


def _openings(
    board: BoardFileSpec, plan: FixturePlan, closure_edge: str
) -> list[ConnectorCutoutParameters]:
    """The finger notch and the windows cut in the catch's wall, as openings the
    catch keeps clear of."""

    notch = hinge_notch_offset(board)
    spans = [(notch - NOTCH_RADIUS_MM, notch + NOTCH_RADIUS_MM)]
    spans.extend(window_spans(board, plan.clearance_mm, closure_edge))

    return [_opening(closure_edge, low, high) for low, high in spans]


def add_hinged_closure(
    nest: cq.Workplane,
    plate: cq.Workplane,
    *,
    board: BoardFileSpec,
    plan: FixturePlan,
    closure: ClosurePlan,
    hole_compensation_mm: float,
    hardware: Mapping[str, cq.Shape],
    carried: Mapping[str, cq.Shape],
) -> tuple[cq.Workplane, cq.Workplane, HingeReport]:
    """Hinge the plate on the nest and close it with a catch, refusing a plate
    that cannot swing clear with its pins."""

    hinge = closure.hinge

    if hinge is None:
        raise ValueError("The closure has no hinge to build")

    hinge_edge, closure_edge, _ = hinge_walls(board, plan.clearance_mm)

    try:
        return add_hinge(
            nest,
            plate,
            _cavity(board, plan),
            lid_mm=plan.plate_thickness_mm,
            pin=get_fastener(hinge.pin),
            hole_compensation_mm=hole_compensation_mm,
            openings=_openings(board, plan, closure_edge),
            hardware=hardware,
            carried=carried,
            hinge_edge=hinge_edge,
        )
    except ValueError as error:
        raise ValueError(
            f"The hinged closure cannot be built: {error}. Close the plate with "
            "screws instead (closure: screws)"
        ) from error
