"""Build a PCB test fixture: a nest that holds the board and a plate of pins.

The **nest** is a tray that follows the board's outline. The board rests on a
ledge round its edge, over a hollow for the parts under it, with a prop under
each test point where nothing is in the way; the walls rise past the board to a
rim, and windows are cut where a part overhangs the edge. The **plate** rests on
that rim, so it never touches the board, with a bore over each test point for a
pin, and sockets for the posts that locate it: two dowels on ears outside the
nest, or two posts up through the board's mounting holes.

The build refuses a fixture whose parts do not fit: the board must drop into the
nest and lift out again, the plate must clear every part, and each pin's barrel
must clear its bore and the parts beside it. Two screws hold the plate down
against the pins' force: ears on the nest with heat-set inserts, and clearance
holes through the plate (see :mod:`zcad_core.features.pcb_fixture_closure`).

Frame: the board's own, as in :mod:`zcad_core.features.pcb_fixture_plan`; the
board's top face is ``z == 0``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.features.board_solids import board_assembly
from zcad_core.features.board_solids import box as _box
from zcad_core.features.board_solids import cylinder as _cylinder
from zcad_core.features.board_solids import shape_of as _solid
from zcad_core.features.lid_hinge import HingeReport, swung_lid
from zcad_core.features.pcb_fixture_closure import (
    NOTCH_RADIUS_MM,
    ClosurePlan,
    hinge_notch_offset,
)
from zcad_core.features.pcb_fixture_file import PcbFixtureSpec, closure_for
from zcad_core.features.pcb_fixture_hinge import add_hinged_closure
from zcad_core.features.pcb_fixture_plan import (
    EAR_RADIUS_MM,
    FLOOR_MM,
    LEDGE_MM,
    RELIEF_MARGIN_MM,
    SUPPORT_POST_MM,
    FixturePlan,
    outline_points,
    plan_fixture,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.geometry.outline_prism import outline_prism
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardFileSpec,
)

FIXTURE_RECORD_SCHEMA_VERSION = "1.0.0"
FIXTURE_RECORD = "fixture.json"
# How far the board is lifted per step in the release check.
RELEASE_STEP_MM = 2.0
# How far short of the plate's top a post stops.
POST_STOP_MM = 0.2
_TOLERANCE_MM3 = 1e-6


@dataclass(frozen=True)
class PcbFixture:
    """The built nest and plate, and what they were built from."""

    spec: PcbFixtureSpec
    board: BoardFileSpec
    plan: FixturePlan
    closure: ClosurePlan
    nest: cq.Workplane
    plate: cq.Workplane
    profile_id: str
    tolerance_status: str
    checks: dict[str, bool]
    problems: tuple[str, ...] = ()
    hinge: HingeReport | None = None

    @property
    def passed(self) -> bool:
        return all(self.checks.values()) and not self.problems


def _build_nest(
    board: BoardFileSpec, plan: FixturePlan, closure: ClosurePlan
) -> cq.Workplane:
    points = outline_points(board)
    thickness = board.board_thickness_mm
    ledge_z = -thickness
    cavity_z = ledge_z - plan.under_depth_mm
    bottom_z = cavity_z - FLOOR_MM
    rim_z = plan.plate_underside_mm
    reach = plan.clearance_mm + plan.nest_wall_mm
    nest = outline_prism(points, bottom_z, rim_z, reach)

    for anchor in plan.anchors:
        if anchor.kind == "dowel":
            nest = nest.union(
                _cylinder(anchor.x_mm, anchor.y_mm, bottom_z, rim_z, 2 * EAR_RADIUS_MM)
            )

    for x, y in closure.screws:
        nest = nest.union(_cylinder(x, y, bottom_z, rim_z, 2 * closure.ear_radius_mm))

    nest = nest.cut(outline_prism(points, ledge_z, rim_z + 1.0, plan.clearance_mm))
    inner = min(board.board_width_mm, board.board_length_mm) - 2 * LEDGE_MM

    if inner > 2.0:
        nest = nest.cut(outline_prism(points, cavity_z, ledge_z + 0.01, -LEDGE_MM))

    for x, y in plan.supports:
        nest = nest.union(_cylinder(x, y, cavity_z - 0.01, ledge_z, SUPPORT_POST_MM))

    for part in board.components:
        if part.identifier == ENVELOPE_IDENTIFIER:
            continue

        z0 = part.bottom_offset_from_board_top_mm
        nest = nest.cut(
            _box(
                part.center_x_mm,
                part.center_y_mm,
                part.width_mm + 2 * RELIEF_MARGIN_MM,
                part.depth_mm + 2 * RELIEF_MARGIN_MM,
                z0 - 0.3,
                # Open to the rim, so a part standing in the wall lifts out with
                # the board instead of being caught under it.
                rim_z + 1.0,
            )
        )

    for x, y in closure.screws:
        nest = nest.cut(
            _cylinder(
                x,
                y,
                rim_z - closure.pocket_depth_mm,
                rim_z + 0.5,
                closure.pocket_diameter_mm,
            )
        )

    nest = _add_posts(nest, plan, rim_z, cavity_z)

    return _cut_notches(nest, board, plan, closure, ledge_z, rim_z)


def _add_posts(
    nest: cq.Workplane, plan: FixturePlan, rim_z: float, cavity_z: float
) -> cq.Workplane:
    """The posts the plate locates on: dowels up from the rim, or posts up from
    the nest's floor through the board's holes."""

    stop = rim_z + plan.plate_thickness_mm - POST_STOP_MM

    for anchor in plan.anchors:
        start = rim_z - 0.01 if anchor.kind == "dowel" else cavity_z - 0.01
        nest = nest.union(
            _cylinder(anchor.x_mm, anchor.y_mm, start, stop, anchor.post_diameter_mm)
        )

    return nest


def _cut_notches(
    nest: cq.Workplane,
    board: BoardFileSpec,
    plan: FixturePlan,
    closure: ClosurePlan,
    ledge_z: float,
    rim_z: float,
) -> cq.Workplane:
    """Two finger notches through the wall, on the sides the dowels are not. A
    hinged closure takes one, on the catch's wall and off the middle, since the
    hinge is on the other wall and the catch needs the middle."""

    reach = plan.clearance_mm + plan.nest_wall_mm
    points = outline_points(board)
    along_x = board.board_width_mm >= board.board_length_mm
    xs = [x for x, _ in points]
    ys = [y for _, y in points]

    hinged = closure.hinge is not None
    # The notch is on the catch's wall: the one opposite the hinge.
    catch_sign = (
        -1.0
        if closure.hinge is not None
        and closure.hinge.closure_edge.startswith("negative")
        else 1.0
    )

    for sign in (catch_sign,) if hinged else (-1.0, 1.0):
        edge = (
            (max(ys) if sign > 0 else min(ys))
            if along_x
            else (max(xs) if sign > 0 else min(xs))
        )
        middle = edge + sign * reach / 2
        lateral = hinge_notch_offset(board) if hinged else 0.0
        at = (lateral, middle) if along_x else (middle, lateral)
        nest = nest.cut(
            _cylinder(at[0], at[1], ledge_z, rim_z + 1.0, 2 * NOTCH_RADIUS_MM)
        )

    return nest


def _build_plate(
    board: BoardFileSpec, plan: FixturePlan, closure: ClosurePlan
) -> cq.Workplane:
    points = outline_points(board)
    reach = plan.clearance_mm + plan.nest_wall_mm
    bottom, top = plan.plate_underside_mm, plan.plate_top_mm
    plate = outline_prism(points, bottom, top, reach)

    for anchor in plan.anchors:
        if anchor.kind == "dowel":
            plate = plate.union(
                _cylinder(anchor.x_mm, anchor.y_mm, bottom, top, 2 * EAR_RADIUS_MM)
            )

    for x, y in closure.screws:
        plate = plate.union(_cylinder(x, y, bottom, top, 2 * closure.ear_radius_mm))
        plate = plate.cut(
            _cylinder(x, y, bottom - 0.5, top + 0.5, closure.clearance_hole_mm)
        )

    for point in plan.points:
        plate = plate.cut(
            _cylinder(
                point.x_mm, point.y_mm, bottom - 0.5, top + 0.5, plan.bore_diameter_mm
            )
        )

    for anchor in plan.anchors:
        plate = plate.cut(
            _cylinder(
                anchor.x_mm,
                anchor.y_mm,
                bottom - 0.5,
                top + 0.5,
                anchor.socket_diameter_mm,
            )
        )

    return plate


def _lifts_out(nest: cq.Shape, board: cq.Shape, height: float) -> bool:
    """Lift the board straight up out of the nest in steps, to clear of it, and
    refuse a nest it meets on the way."""

    lift = RELEASE_STEP_MM

    while lift <= height + RELEASE_STEP_MM:
        moved = board.moved(cq.Location(cq.Vector(0, 0, lift)))

        if intersection_volume(nest, moved) > _TOLERANCE_MM3:
            return False

        lift += RELEASE_STEP_MM

    return True


def _pin_solids(plan: FixturePlan) -> dict[str, cq.Shape]:
    """Each pin as a cylinder of its barrel, from its tip at the pad to the
    plate's top."""

    return {
        f"the pin at {point.identifier}": cq.Solid.makeCylinder(
            plan.pin.barrel_diameter_mm / 2,
            plan.plate_top_mm,
            pnt=cq.Vector(point.x_mm, point.y_mm, 0.0),
            dir=cq.Vector(0, 0, 1),
        )
        for point in plan.points
    }


def _hardware(board: BoardFileSpec, assembly: cq.Shape) -> dict[str, cq.Shape]:
    """The board and each of its parts by name, for the hinge's sweep."""

    names = ["the board", *(part.identifier for part in board.components)]

    return dict(zip(names, assembly.Solids(), strict=True))


def _plate_open_clears_board(
    nest: cq.Shape,
    plate: cq.Shape,
    assembly: cq.Shape,
    pins: dict[str, cq.Shape],
    hinge: HingeReport,
    height: float,
) -> bool:
    """Swing the plate and its pins open, and lift the board out past them."""

    opened = [
        swung_lid(shape, hinge, hinge.swing_degrees)
        for shape in (plate, *pins.values())
    ]
    shut = cq.Compound.makeCompound([nest, *opened])

    return _lifts_out(shut, assembly, height)


def _pins_clear(plate: cq.Shape, plan: FixturePlan, parts: cq.Shape) -> bool:
    """Each pin, as a cylinder of its barrel from its tip at the pad to the plate's
    top, meets neither its plate nor a part."""

    for pin in _pin_solids(plan).values():
        if (
            intersection_volume(plate, pin) > _TOLERANCE_MM3
            or intersection_volume(parts, pin) > _TOLERANCE_MM3
        ):
            return False

    return True


def build_fixture(
    spec: PcbFixtureSpec,
    board: BoardFileSpec,
    probed: list[Any],
    profile: dict[str, Any],
) -> PcbFixture:
    """The nest and plate for a board, refused if the plan cannot hold (a pin
    that cannot land, a part under a pin) or a part does not fit."""

    plan = plan_fixture(
        board=board,
        points=probed,
        pin=spec.pin,
        working_travel_mm=spec.working_travel_mm,
        locating=spec.locating,
        profile=profile,
        nest_wall_mm=spec.nest_wall_mm,
        plate_thickness_mm=spec.plate_thickness_mm,
    )

    if plan.errors:
        raise ValueError("The fixture cannot be built:\n- " + "\n- ".join(plan.errors))

    closure = closure_for(spec, board, plan, profile)

    if closure.errors:
        raise ValueError(
            "The fixture cannot be built:\n- " + "\n- ".join(closure.errors)
        )

    nest = _build_nest(board, plan, closure)
    plate = _build_plate(board, plan, closure)
    assembly = board_assembly(board)
    hinge = None
    pins = _pin_solids(plan)

    if closure.hinge is not None:
        nest, plate, hinge = add_hinged_closure(
            nest,
            plate,
            board=board,
            plan=plan,
            closure=closure,
            hole_compensation_mm=_hole_oversize(profile),
            hardware=_hardware(board, assembly),
            carried=pins,
        )

    parts = cq.Compound.makeCompound(
        [s for s in assembly.Solids()[1:] if s.BoundingBox().zmax > 0.05]
    )
    nest_shape, plate_shape = _solid(nest), _solid(plate)
    checks = {
        "nest_one_solid": len(nest.solids().vals()) == 1,
        "plate_one_solid": len(plate.solids().vals()) == 1,
        "board_fits_nest": intersection_volume(nest_shape, assembly) <= _TOLERANCE_MM3,
        "board_lifts_out": _lifts_out(
            nest_shape, assembly, board.board_thickness_mm + plan.tallest_part_mm
        ),
        "plate_clear_of_nest": intersection_volume(plate_shape, nest_shape)
        <= _TOLERANCE_MM3,
        "pins_clear": _pins_clear(plate_shape, plan, parts),
    }

    # A screwed plate is a prism whose underside is refused below the tallest
    # part and a margin, so it clears the board by construction; a hinged one
    # carries a catch that hangs below it, so it is checked.
    if hinge is not None:
        checks["plate_clear_of_board"] = (
            intersection_volume(plate_shape, assembly) <= _TOLERANCE_MM3
        )
        checks["board_lifts_out_plate_open"] = _plate_open_clears_board(
            nest_shape,
            plate_shape,
            assembly,
            pins,
            hinge,
            board.board_thickness_mm + plan.tallest_part_mm,
        )

    # The preload and the catch's load are refused at the build when over the
    # limit (closure_for), so a built fixture always meets them; they are in
    # the plan's record, not repeated here as checks.

    return PcbFixture(
        spec=spec,
        board=board,
        plan=plan,
        closure=closure,
        nest=nest,
        plate=plate,
        profile_id=str(profile.get("profile_id", "")),
        tolerance_status=str(profile.get("tolerance_status", "unknown")),
        checks=checks,
        hinge=hinge,
    )


def print_oriented(fixture: PcbFixture) -> dict[str, cq.Workplane]:
    """Each part as it goes on the bed, its lowest face on it: the nest on its
    floor, the plate on its underside. A hinged plate goes on its top face
    instead, as an enclosure's hinged lid does, since the catch's tongue hangs
    below its underside and would stand it on the tongue."""

    parts = {}

    for name, model in (("nest", fixture.nest), ("plate", fixture.plate)):
        if name == "plate" and fixture.hinge is not None:
            model = model.rotate((0, 0, 0), (1, 0, 0), 180)

        low = _solid(model).BoundingBox().zmin
        parts[name] = model.translate((0, 0, -low))

    return parts


def require_fits_bed(fixture: PcbFixture, profile: dict[str, Any]) -> None:
    """Refuse a part that will not lie on the printer's bed."""

    volume = profile.get("build_volume_mm")

    if not volume:
        return

    for name, model in print_oriented(fixture).items():
        box = _solid(model).BoundingBox()
        fits = box.xlen <= volume["x"] and box.ylen <= volume["y"]
        turned = box.xlen <= volume["y"] and box.ylen <= volume["x"]

        if not (fits or turned) or box.zlen > volume["z"]:
            raise ValueError(
                f"The {name} is {box.xlen:.0f} x {box.ylen:.0f} x {box.zlen:.0f} mm; "
                f"the printer's bed is {volume['x']:.0f} x {volume['y']:.0f} x "
                f"{volume['z']:.0f} mm"
            )


def hinge_summary(hinge: HingeReport | None) -> dict[str, Any] | None:
    """What the hinge and catch came out as, or ``None`` for a screwed plate."""

    if hinge is None:
        return None

    return {
        "hinge_wall": hinge.hinge_edge,
        "catch_wall": hinge.closure_edge,
        "knuckles": hinge.knuckles,
        "pin": hinge.pin_description,
        "swing_degrees": hinge.swing_degrees,
        "catch_strain_percent": round(100 * hinge.catch.strain, 2),
        "wall_needed_mm": round(hinge.wall_needed_mm, 1),
    }


def _hole_oversize(profile: dict[str, Any]) -> float:
    return float(profile["tolerances_mm"]["hole_oversize"])


def fixture_record(
    fixture: PcbFixture,
    files: dict[str, dict[str, Any]],
    *,
    material_profile_id: str = "",
    accuracy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """What a build says about itself: the fixture file and the board by hash, the
    pin and its figures' source, the layout and the misalignment budget, and that
    nothing here is verified."""

    spec, board, plan = fixture.spec, fixture.board, fixture.plan

    return {
        "schema_version": FIXTURE_RECORD_SCHEMA_VERSION,
        "design_type": "pcb-test-fixture",
        "identifier": spec.identifier,
        "fixture_file": {"path": str(spec.file_path), "sha256": spec.file_sha256},
        "board": {
            "identifier": board.identifier,
            "path": str(spec.board_path),
            "sha256": spec.board_sha256,
            "size_mm": [board.board_width_mm, board.board_length_mm],
            "thickness_mm": board.board_thickness_mm,
        },
        "pin": {
            "maker": spec.pin.maker,
            "model": spec.pin.model,
            "barrel_diameter_mm": spec.pin.barrel_diameter_mm,
            "tip_diameter_mm": spec.pin.tip_diameter_mm,
            "free_length_mm": spec.pin.free_length_mm,
            "travel_mm": spec.pin.travel_mm,
            "force_n": spec.pin.force_n,
            "force_at_travel_mm": spec.pin.force_at_travel_mm,
            "figures_from": spec.pin.figures_from,
        },
        "working_travel_mm": spec.working_travel_mm,
        "side": spec.side,
        "board_turned_over": spec.side == "bottom",
        "locating": spec.locating,
        "closure": spec.closure,
        "closure_built": True,
        "closure_plan": fixture.closure.to_dict(),
        "hinge": hinge_summary(fixture.hinge),
        "points": [
            {
                "identifier": p.identifier,
                "position_mm": [p.x_mm, p.y_mm],
                "position_in_board_mm": [
                    -p.x_mm if spec.side == "bottom" else p.x_mm,
                    p.y_mm,
                ],
                "pad_diameter_mm": p.pad_diameter_mm,
                "net": p.net,
                "slack_mm": round(
                    p.pad_diameter_mm / 2 - spec.pin.tip_diameter_mm / 2, 3
                ),
                "misalignment_mm": round(plan.budgets[p.identifier].total_mm, 3),
            }
            for p in plan.points
        ],
        "plan": plan.to_dict(),
        "printer_profile_id": fixture.profile_id,
        "tolerance_status": fixture.tolerance_status,
        "material_profile_id": material_profile_id,
        "measured_accuracy": accuracy,
        "checks": fixture.checks,
        # The engine states no accuracy: a trial measures it.
        "verified": False,
        "parts": files,
    }


def write_fixture_record(
    fixture: PcbFixture,
    files: dict[str, dict[str, Any]],
    directory: Path,
    *,
    material_profile_id: str = "",
    accuracy: dict[str, Any] | None = None,
) -> Path:
    """Write ``fixture.json`` beside the exported parts; refuses to overwrite."""

    path = directory / FIXTURE_RECORD

    if path.exists():
        raise FileExistsError(f"Refusing to overwrite build record: {path}")

    path.write_text(
        json.dumps(
            fixture_record(
                fixture,
                files,
                material_profile_id=material_profile_id,
                accuracy=accuracy,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return path
