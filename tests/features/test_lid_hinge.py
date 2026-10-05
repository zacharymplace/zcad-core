from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    Placement,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.cli import main
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.lid_hinge import (
    CATCH_CLEARANCE_MM,
    CATCH_ENGAGEMENT_MM,
    CATCH_HOOK_HEIGHT_MM,
    CATCH_TONGUE_MM,
    CATCH_WIDTH_MM,
    SWING_DEGREES,
    add_hinge,
    hinge_edges,
    hinge_web_depth_mm,
)
from zcad_core.features.mounts import FLEXURE_STRAIN_LIMIT
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    get_fastener,
    get_raspberry_pi_pico2,
    get_reference_oled_128x64,
)

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
MINIMUM_WALL_MM = 1.2
BARREL_RADIUS_MM = 3.5
AXIS_OFFSET_MM = 3.9


def assembly():  # type: ignore[no-untyped-def]
    return build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )


@cache
def hinged() -> Enclosure:
    return build_enclosure(
        assembly(),
        board=BOARD,
        display=DISPLAY,
        design=EnclosureDesign(lid_attachment="hinge", bottom_clearance_mm=6.0),
    )


def solid(model: cq.Workplane) -> cq.Compound:
    return cq.Compound.makeCompound(
        [
            part
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for part in item.Solids()
        ]
    )


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(solid(model).isInside(cq.Vector(x, y, z)))


def frame(enclosure: Enclosure) -> dict[str, float]:
    """The hinged enclosure's numbers: the hinge wall is +X and the closure
    wall -X, as the Pico's long walls run that way."""

    spec = enclosure.specification
    wall = enclosure.design.wall_mm
    hinge = enclosure.hinge
    assert hinge is not None and hinge.hinge_edge == "positive_x"
    assert hinge.closure_edge == "negative_x"
    top = spec.bottom_z_mm + spec.inner_height_mm

    return {
        "hinge_face": spec.center_x_mm + spec.inner_width_mm / 2 + wall,
        "closure_face": spec.center_x_mm - spec.inner_width_mm / 2 - wall,
        "cy": spec.center_y_mm,
        "top": top,
        "axis_z": top + enclosure.design.lid_mm / 2,
        "depth": spec.inner_depth_mm + 2 * wall,
    }


def test_a_larger_pin_hangs_its_web_lower_and_the_least_is_kept() -> None:
    # The barrel round a 4.5 mm hole is 4.05 mm in radius, from an axis 1 mm above
    # a 2 mm lid's seat, so it reaches 3.05 mm below; an M3's reaches 2.5 mm, the
    # least the builders take, and a thicker lid never makes it less.
    assert hinge_web_depth_mm(get_fastener("M4"), 2.0) == pytest.approx(3.05)
    assert hinge_web_depth_mm(get_fastener("M3"), 2.0) == pytest.approx(2.5)
    assert hinge_web_depth_mm(get_fastener("M3"), 3.0) == pytest.approx(2.5)


def test_hinged_lid_has_no_screws_bosses_or_skirt() -> None:
    enclosure = hinged()

    assert enclosure.fastener_positions == ()
    assert enclosure.design.skirt_depth_mm is None
    assert enclosure.hinge is not None


def test_knuckles_alternate_between_base_and_lid_around_the_pin() -> None:
    enclosure = hinged()
    hinge = enclosure.hinge
    assert hinge is not None
    f = frame(enclosure)
    x_axis = f["hinge_face"] + AXIS_OFFSET_MM
    gap = 0.4
    length = (hinge.span_mm - (hinge.knuckles - 1) * gap) / hinge.knuckles
    start = f["cy"] - hinge.span_mm / 2

    for index in range(hinge.knuckles):
        y = start + index * (length + gap) + length / 2
        in_base = has_material(
            enclosure.base, x_axis + BARREL_RADIUS_MM - 0.3, y, f["axis_z"]
        )
        in_lid = has_material(
            enclosure.lid, x_axis + BARREL_RADIUS_MM - 0.3, y, f["axis_z"]
        )

        assert in_base == (index % 2 == 0)
        assert in_lid == (index % 2 == 1)
        # The pin hole goes through every knuckle, in whichever part it is.
        assert not has_material(enclosure.base, x_axis, y, f["axis_z"])
        assert not has_material(enclosure.lid, x_axis, y, f["axis_z"])
        # A gap between knuckles lets them turn.
        if index:
            gap_y = start + index * (length + gap) - gap / 2
            assert not has_material(enclosure.base, x_axis + 3.0, gap_y, f["axis_z"])
            assert not has_material(enclosure.lid, x_axis + 3.0, gap_y, f["axis_z"])


def test_pin_is_long_enough_and_a_standard_length() -> None:
    hinge = hinged().hinge
    assert hinge is not None

    assert hinge.pin == "M3"
    # Through the span, a nut, and a little slack.
    assert hinge.pin_length_mm >= hinge.span_mm + 2.4
    assert hinge.pin_length_mm in (
        8,
        10,
        12,
        16,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        60,
        70,
        80,
    )


def test_the_hinge_grows_the_hinge_side_and_leaves_the_rest() -> None:
    enclosure = hinged()
    base = solid(enclosure.base).BoundingBox()
    f = frame(enclosure)

    # The barrels stand out of the hinge wall by the axis offset and a radius.
    assert base.xmax == pytest.approx(
        f["hinge_face"] + AXIS_OFFSET_MM + BARREL_RADIUS_MM
    )
    assert base.xmin == pytest.approx(f["closure_face"] - 0.6, abs=0.7)


def test_catch_is_a_tongue_with_a_hook_under_a_bump() -> None:
    enclosure = hinged()
    hinge = enclosure.hinge
    assert hinge is not None
    f = frame(enclosure)
    y = hinge.catch_center_mm
    top = f["top"]
    hook_top = top - hinge.catch.length_mm + CATCH_HOOK_HEIGHT_MM / 2
    hook_bottom = hook_top - CATCH_HOOK_HEIGHT_MM

    def out(distance: float) -> float:
        """A point this far outside the closure wall (-X is outward)."""
        return f["closure_face"] - distance

    # The tongue hangs from the lid, outside the wall.
    assert has_material(enclosure.lid, out(1.5), y, top - 5.0)
    assert not has_material(enclosure.base, out(1.5), y, top - 5.0)
    # The bump is on the wall, and the hook sits just under it.
    assert has_material(enclosure.base, out(0.3), y, hook_top + 0.6)
    assert not has_material(enclosure.lid, out(0.3), y, hook_top + 0.6)
    assert has_material(enclosure.lid, out(0.4), y, hook_bottom + 0.9)
    assert not has_material(enclosure.base, out(0.4), y, hook_bottom + 0.9)
    # The hook reaches the bump's face: its underside is the bump's underside.
    assert has_material(enclosure.lid, out(0.4), y, hook_top - 0.1)
    assert has_material(enclosure.base, out(0.4), y, hook_top + 0.1)
    # A lip at the tongue's foot gives a finger something to pull.
    assert has_material(enclosure.lid, out(2.6), y, hook_bottom + 0.5)
    # The catch is as wide as it is meant to be, and no wider.
    assert has_material(
        enclosure.lid, out(1.5), y + CATCH_WIDTH_MM / 2 - 0.3, top - 5.0
    )
    assert not has_material(
        enclosure.lid, out(1.5), y + CATCH_WIDTH_MM / 2 + 0.3, top - 5.0
    )


@pytest.mark.parametrize("pattern", ["slots", "hex"])
def test_the_catch_keeps_off_the_wall_vents(pattern: str) -> None:
    # Before, the catch's bump and hook stood over vent cells, 29 to 57 per cent
    # of the wall behind them open. Now the vents leave its stretch whole.
    enclosure = build_enclosure(
        assembly(),
        board=BOARD,
        display=DISPLAY,
        design=EnclosureDesign(
            lid_attachment="hinge",
            bottom_clearance_mm=6.0,
            vent_area_mm2=150,
            vent_pattern=pattern,
        ),
    )
    hinge = enclosure.hinge
    assert hinge is not None and enclosure.vents is not None
    f = frame(enclosure)
    x = f["closure_face"] + enclosure.design.wall_mm / 2
    hook_top = f["top"] - hinge.catch.length_mm + CATCH_HOOK_HEIGHT_MM / 2

    for step in range(-8, 9):
        y = hinge.catch_center_mm + step * CATCH_WIDTH_MM / 16
        for z in (hook_top - CATCH_HOOK_HEIGHT_MM, hook_top, hook_top + 1.2):
            assert has_material(enclosure.base, x, y, z), (y, z)


def test_vents_that_leave_no_room_for_the_catch_say_so() -> None:
    with pytest.raises(ValueError, match="catch keeps a stretch of its closure wall"):
        build_enclosure(
            assembly(),
            board=BOARD,
            display=DISPLAY,
            design=EnclosureDesign(
                lid_attachment="hinge",
                bottom_clearance_mm=6.0,
                vent_area_mm2=150,
                vent_pattern="louvers",
            ),
        )


def test_catch_tongue_stays_within_the_strain_limit() -> None:
    hinge = hinged().hinge
    assert hinge is not None
    catch = hinge.catch

    assert catch.strain <= FLEXURE_STRAIN_LIMIT
    assert catch.thickness_mm == CATCH_TONGUE_MM
    assert catch.thickness_mm >= MINIMUM_WALL_MM
    assert catch.deflection_mm == pytest.approx(
        CATCH_ENGAGEMENT_MM + CATCH_CLEARANCE_MM
    )
    expected = 3 * catch.thickness_mm * catch.deflection_mm / (2 * catch.length_mm**2)
    assert catch.strain == pytest.approx(expected)


def test_the_lid_swings_to_100_degrees_clear_of_everything() -> None:
    hinge = hinged().hinge
    assert hinge is not None

    assert hinge.swing_degrees == SWING_DEGREES == 100.0


def test_a_short_wall_is_refused_with_what_it_needs() -> None:
    board_only = build_board_assembly(
        board=BOARD,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )

    with pytest.raises(ValueError, match=r"catch needs 11\.7 mm"):
        build_enclosure(
            board_only, board=BOARD, design=EnclosureDesign(lid_attachment="hinge")
        )


def test_a_tight_fit_that_the_lid_would_hit_is_refused() -> None:
    with pytest.raises(
        ValueError, match=r"hits the base at \d+ degrees.*side_clearance_mm"
    ):
        build_enclosure(
            assembly(),
            board=BOARD,
            display=DISPLAY,
            design=EnclosureDesign(
                lid_attachment="hinge", bottom_clearance_mm=6.0, side_clearance_mm=2.0
            ),
        )


def test_the_display_swings_with_the_lid_not_against_it() -> None:
    # Clear at 3 mm only because the display is swept as part of the lid; as a
    # fixed part it would be hit at the first step.
    enclosure = hinged()

    assert enclosure.side_clearance_mm == (3.0, 3.0)
    assert enclosure.display_support == "clips"


def cavity() -> Cavity:
    return Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=60.0,
        depth_mm=30.0,
        floor_z_mm=2.0,
        top_z_mm=20.0,
        wall_mm=2.0,
    )


def opening(edge: str, offset: float, width: float = 10.0) -> ConnectorCutoutParameters:
    return ConnectorCutoutParameters(
        edge=edge,  # type: ignore[arg-type]
        center_offset_mm=offset,
        bottom_z_mm=5.0,
        width_mm=width,
        height_mm=5.0,
    )


def test_hinge_goes_on_the_back_wall_unless_it_has_an_opening() -> None:
    assert hinge_edges(cavity(), []) == ("positive_y", "negative_y")
    assert hinge_edges(cavity(), [opening("positive_y", 0.0)]) == (
        "negative_y",
        "positive_y",
    )
    # An opening on a short wall does not matter.
    assert hinge_edges(cavity(), [opening("positive_x", 0.0)]) == (
        "positive_y",
        "negative_y",
    )

    with pytest.raises(ValueError, match="Both long walls carry an opening"):
        hinge_edges(cavity(), [opening("positive_y", 0.0), opening("negative_y", 0.0)])


def plate_and_base(c: Cavity) -> tuple[cq.Workplane, cq.Workplane]:
    wall = c.wall_mm
    outer_w, outer_d = c.width_mm + 2 * wall, c.depth_mm + 2 * wall
    base = (
        cq.Workplane("XY")
        .box(outer_w, outer_d, c.top_z_mm, centered=(True, True, False))
        .cut(
            cq.Workplane("XY")
            .box(c.width_mm, c.depth_mm, c.top_z_mm, centered=(True, True, False))
            .translate((0, 0, c.floor_z_mm))
        )
    )
    lid = (
        cq.Workplane("XY")
        .box(outer_w, outer_d, 2.0, centered=(True, True, False))
        .translate((0, 0, c.top_z_mm))
    )

    return base, lid


def test_the_catch_moves_to_clear_an_opening_in_the_closure_wall() -> None:
    c = cavity()
    base, lid = plate_and_base(c)
    clear = add_hinge(
        base,
        lid,
        c,
        lid_mm=2.0,
        pin=get_fastener("M3"),
        hole_compensation_mm=0.0,
        openings=[],
        hardware={},
    )[2]
    # An opening in the middle of the closure wall pushes the catch aside.
    blocked = add_hinge(
        base,
        lid,
        c,
        lid_mm=2.0,
        pin=get_fastener("M3"),
        hole_compensation_mm=0.0,
        openings=[opening("negative_y", 0.0, width=12.0)],
        hardware={},
    )[2]

    assert clear.catch_center_mm == pytest.approx(0.0)
    assert abs(blocked.catch_center_mm) >= 6.0 + 1.0 + CATCH_WIDTH_MM / 2 - 1e-6


def test_no_room_for_the_catch_is_refused() -> None:
    c = cavity()
    base, lid = plate_and_base(c)

    with pytest.raises(ValueError, match="clear of openings"):
        add_hinge(
            base,
            lid,
            c,
            lid_mm=2.0,
            pin=get_fastener("M3"),
            hole_compensation_mm=0.0,
            openings=[opening("negative_y", 0.0, width=60.0)],
            hardware={},
        )


def test_a_part_in_the_lids_path_is_refused_by_name() -> None:
    c = cavity()
    base, lid = plate_and_base(c)
    # A block standing in the cavity, close under the lid.
    post = cq.Solid.makeBox(10.0, 10.0, 6.0, pnt=cq.Vector(-5.0, -5.0, 14.0))
    lid_with_post = lid.union(
        cq.Workplane("XY").add(
            cq.Solid.makeBox(4.0, 4.0, 8.0, pnt=cq.Vector(-2.0, -2.0, 14.0))
        )
    )

    with pytest.raises(ValueError, match="hits cap at"):
        add_hinge(
            base,
            lid_with_post,
            c,
            lid_mm=2.0,
            pin=get_fastener("M3"),
            hole_compensation_mm=0.0,
            openings=[],
            hardware={"cap": post},
        )


def test_hinge_does_not_touch_the_hardware_or_the_lid_in_the_closed_position() -> None:
    enclosure = hinged()

    assert intersection_volume(solid(enclosure.base), solid(enclosure.lid)) < 1e-6


def test_a_lid_hinge_conflicts_with_screw_and_lip_options() -> None:
    with pytest.raises(ValueError, match="no screws to countersink"):
        EnclosureDesign(lid_attachment="hinge", countersunk_screws=True).validate()

    with pytest.raises(ValueError, match="no lip"):
        EnclosureDesign(lid_attachment="hinge", locating_lip=True).validate()

    with pytest.raises(ValueError, match="lid_attachment must be one of"):
        EnclosureDesign(lid_attachment="zip-tie").validate()


def test_cli_builds_a_hinged_lid_and_reports_the_pin(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--display",
            "reference_oled_128x64",
            "--lid",
            "hinge",
            "--bottom-clearance-mm",
            "6",
            "--review",
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert set(output["parts"]) == {"base", "lid"}
    hinge = output["hinge"]
    assert hinge["hinge_wall"] == "positive_x"
    assert hinge["pin"] == "M3 x 60 mm screw and nut"
    assert hinge["catch"]["strain_percent"] <= 1.5
    assert output["review"]["passed"] is True
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["design"]["lid_attachment"] == "hinge"
    assert record["design"]["hinge_pin"] == "M3"
    review = json.loads(Path(output["review"]["report"]).read_text())
    assert review["fasteners"]["lid"] == "hinged"
    assert review["fasteners"]["pin"] == "M3 x 60 mm, with a nut"
