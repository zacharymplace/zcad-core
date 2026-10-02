from __future__ import annotations

import json
import math
from functools import cache
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.cli import main
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
from zcad_core.features.connector_cutouts import ConnectorCutoutParameters
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.fan_bay import (
    FAN_DIRECTIONS,
    FAN_POSITIONS,
    GUARD_CELL_MM,
    cut_fan_bay,
    fan_report,
    plan_fan,
    screw_length_mm,
)
from zcad_core.features.lid_hinge import add_hinge
from zcad_core.features.lid_slide import add_slide
from zcad_core.features.vent_patterns import MIN_WEB_MM, solid_tester
from zcad_core.hardware import (
    get_fan,
    get_fastener,
    get_raspberry_pi5,
    get_raspberry_pi_pico2,
    list_fans,
)
from zcad_core.hardware.thermal import get_power_figure

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
FAN_40 = "NOCTUA_NF_A4X10_5V"
FAN_60 = "NOCTUA_NF_A6X25_5V"
FAN_30 = "SUNON_MF30100V1_1000U_A99"


# --- the catalog -----------------------------------------------------------


def test_the_catalog_has_the_three_sizes() -> None:
    assert set(list_fans()) == {FAN_30, FAN_40, FAN_60}
    assert [get_fan(f).size_mm for f in (FAN_30, FAN_40, FAN_60)] == [30.0, 40.0, 60.0]
    assert [get_fan(f).hole_spacing_mm for f in (FAN_30, FAN_40, FAN_60)] == [
        24.0,
        32.0,
        50.0,
    ]


@pytest.mark.parametrize("identifier", [FAN_30, FAN_40, FAN_60])
def test_every_fan_carries_a_source_and_says_what_is_still_unverified(
    identifier: str,
) -> None:
    fan = get_fan(identifier)

    assert fan.source.url.startswith("https://")
    assert fan.source.kind == "vendor"
    assert "screw" in fan.source.unverified
    assert "assumption" in fan.source.detail
    assert get_fastener(fan.screw).clearance_hole_mm > 0
    assert fan.hole_spacing_mm < fan.size_mm
    assert fan.opening_diameter_mm == pytest.approx(0.9 * fan.size_mm)


@pytest.mark.parametrize("identifier", [FAN_40, FAN_60])
def test_the_noctua_fans_were_checked_against_the_info_sheet_but_not_their_holes(
    identifier: str,
) -> None:
    fan = get_fan(identifier)

    # The maker's sheet gives the size, the maximum power and the airflow; it gives no
    # hole pattern, so that is still an excerpt and the entry says so.
    assert "information sheet was read" in fan.source.detail
    assert "could not be opened" in fan.source.detail
    assert fan.source.read is False
    assert "hole_spacing_mm" in fan.source.unverified
    assert "current_typical_a" in fan.source.unverified
    assert "hole_spacing_mm" in fan.unverified_note


def test_the_noctua_sheets_agree_with_the_catalog_on_what_they_state() -> None:
    small, large = get_fan(FAN_40), get_fan(FAN_60)

    # NF-A4x10 5V: 40 x 40 mm, 0.25 W at 5 V maximum (0.05 A), 8.2 m3/h.
    assert small.size_mm == 40.0 and small.rated_v == 5.0
    assert small.peak_w == pytest.approx(0.25) and small.airflow_m3h == 8.2
    # The sheet says 10 mm thick and a search excerpt of the page says 11 without
    # pads: the larger is kept, and the entry names the difference.
    assert small.thickness_mm == 11.0 and "thickness_mm" in small.source.unverified
    assert "the sheet says 10 mm" in small.source.detail
    # NF-A6x25 5V: 60 x 60 x 25 mm, 1.3 W at 5 V maximum (0.26 A), 29.2 m3/h.
    assert large.size_mm == 60.0 and large.thickness_mm == 25.0
    assert large.peak_w == pytest.approx(1.3) and large.airflow_m3h == 29.2


def test_the_sunon_fan_was_read_in_the_makers_catalog() -> None:
    fan = get_fan(FAN_30)

    assert fan.source.read is True
    assert "catalog page was read" in fan.source.detail
    assert fan.source.unverified == ("current_max_a", "screw")
    # 30 x 30 x 10 mm, holes 24 mm square and 3.2 mm across, 5 V, 120 mA, 0.60 W, 5.5 CFM.
    assert (fan.size_mm, fan.thickness_mm, fan.hole_spacing_mm) == (30.0, 10.0, 24.0)
    assert fan.typical_w == pytest.approx(0.60)
    assert fan.airflow_m3h == pytest.approx(5.5 * 1.69901, abs=0.01)
    # A 3.2 mm hole takes an M3, not the M2 an earlier excerpt assumed.
    assert fan.screw == "M3"
    assert "not from a document that was read" in fan.unverified_note


def test_a_fans_draw_is_its_voltage_times_its_listed_current() -> None:
    fan = get_fan(FAN_60)

    assert fan.typical_w == pytest.approx(5.0 * 0.187)
    # The maker's own typical input power is 0.935 W, so the two agree.
    assert fan.typical_w == pytest.approx(0.935)
    assert fan.peak_w == pytest.approx(5.0 * 0.26)
    assert get_fan(FAN_30).peak_w is None


def test_a_fans_heat_is_in_the_power_table_with_its_source() -> None:
    figure = get_power_figure(FAN_40)

    assert figure is not None
    assert figure.typical_w == pytest.approx(0.22)
    assert figure.peak_w == pytest.approx(0.25)
    assert "excerpt" in figure.source.detail
    assert figure.source.url == get_fan(FAN_40).source.url


@pytest.mark.parametrize(
    ("identifier", "length"), [(FAN_30, 10), (FAN_40, 10), (FAN_60, 25)]
)
def test_the_screw_stops_short_of_the_frames_far_face(
    identifier: str, length: int
) -> None:
    assert screw_length_mm(2.0, get_fan(identifier)) == length


# --- a synthetic box -------------------------------------------------------


def cavity(width: float = 100.0, depth: float = 80.0, top: float = 30.0) -> Cavity:
    return Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=width,
        depth_mm=depth,
        floor_z_mm=2.0,
        top_z_mm=top,
        wall_mm=2.0,
    )


def box(c: Cavity) -> cq.Workplane:
    wall = c.wall_mm
    return (
        cq.Workplane("XY")
        .box(
            c.width_mm + 2 * wall,
            c.depth_mm + 2 * wall,
            c.top_z_mm,
            centered=(True, True, False),
        )
        .cut(
            cq.Workplane("XY")
            .box(c.width_mm, c.depth_mm, c.top_z_mm, centered=(True, True, False))
            .translate((0, 0, c.floor_z_mm))
        )
    )


def lid_plate(c: Cavity) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(c.width_mm + 4.0, c.depth_mm + 4.0, 2.0, centered=(True, True, False))
        .translate((0, 0, c.top_z_mm))
    )


def has_material(model: cq.Workplane, point: cq.Vector) -> bool:
    return solid_tester(model)(point)


def lid_plan(identifier: str = FAN_40, **overrides):  # type: ignore[no-untyped-def]
    c = overrides.pop("cavity", cavity())
    arguments = {
        "fan": get_fan(identifier),
        "position": "lid",
        "direction": "out",
        "lid_mm": 2.0,
        "offset_mm": (0.0, 0.0),
        "openings": [],
        "wall_top_z_mm": c.top_z_mm,
        "hardware": {},
        "display_bounds": None,
        **overrides,
    }

    return c, plan_fan(box(c), c, **arguments)


def test_a_lid_fan_hangs_under_the_lid_with_its_frame_against_it() -> None:
    c, plan = lid_plan(FAN_40)
    body = plan.body.BoundingBox()

    assert plan.center == (0.0, 0.0)
    assert body.xlen == pytest.approx(40.0) and body.ylen == pytest.approx(40.0)
    assert body.zmax == pytest.approx(c.top_z_mm)
    assert body.zmin == pytest.approx(c.top_z_mm - 11.0)
    assert plan.opening is None


def test_the_guard_and_holes_are_cut_through_the_lid() -> None:
    c, plan = lid_plan(FAN_40)
    lid, guard = cut_fan_bay(
        lid_plate(c),
        plan,
        plate_mm=2.0,
        screw=get_fastener("M3"),
        hole_compensation_mm=0.0,
    )
    z = c.top_z_mm + 1.0

    # Four mounting holes on the fan's 32 mm square, clear of the opening.
    for sx in (-16.0, 16.0):
        for sy in (-16.0, 16.0):
            assert not has_material(lid, cq.Vector(sx, sy, z))
            assert has_material(
                lid, cq.Vector(sx * 1.0 + 3.0 * math.copysign(1, sx), sy, z)
            )
    # The frame's seat, outside the round opening and between the holes, is plate.
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            assert has_material(lid, cq.Vector(19.0 * sx, 19.0 * sy, z))
    # The guard: open cells inside the opening, solid between them.
    u, v = guard.centers[0]
    assert not has_material(lid, cq.Vector(u, v, z))
    assert len(lid.solids().vals()) == 1


def test_every_guard_cell_is_whole_inside_the_round_opening() -> None:
    c, plan = lid_plan(FAN_40)
    _, guard = cut_fan_bay(
        lid_plate(c),
        plan,
        plate_mm=2.0,
        screw=get_fastener("M3"),
        hole_compensation_mm=0.0,
    )
    radius = plan.fan.opening_diameter_mm / 2
    reach = GUARD_CELL_MM / math.sqrt(3.0)

    assert guard.spec.width_mm == GUARD_CELL_MM
    for u, v in guard.centers:
        assert math.hypot(u, v) + reach <= radius + 1e-9
    # A finger cannot get through: every cell is under 8 mm, with 1.2 mm webs.
    nearest = min(
        math.dist(a, b)
        for i, a in enumerate(guard.centers)
        for b in guard.centers[i + 1 :]
    )
    assert nearest == pytest.approx(GUARD_CELL_MM + MIN_WEB_MM)
    opening_area = math.pi * radius**2
    assert 0.3 < guard.area_mm2 / opening_area < 0.7


def test_a_wall_fan_stands_against_the_walls_inner_face_and_takes_the_wall() -> None:
    c = cavity(top=60.0)
    c, plan = lid_plan(FAN_40, cavity=c, position="wall", wall_top_z_mm=58.0)

    body = plan.body.BoundingBox()
    # The back wall is free, so the fan is on it, its frame against the face.
    assert plan.edge == "positive_y"
    assert body.ymax == pytest.approx(c.depth_mm / 2)
    assert body.ymin == pytest.approx(c.depth_mm / 2 - 11.0)
    assert body.zlen == pytest.approx(40.0)
    # It stands in for an opening, so the hinge, catch, and vents leave it be.
    assert plan.opening is not None and plan.opening.edge == "positive_y"
    assert plan.opening.opening_width_mm == pytest.approx(40.0)
    assert plan.opening.opening_height_mm == pytest.approx(40.0)

    base, guard = cut_fan_bay(
        box(c), plan, plate_mm=2.0, screw=get_fastener("M3"), hole_compensation_mm=0.0
    )
    wall_y = c.depth_mm / 2 + 1.0
    u, v = guard.centers[0]
    assert not has_material(base, cq.Vector(u, wall_y, v))
    assert not has_material(base, cq.Vector(16.0, wall_y, plan.center[1] + 16.0))
    assert has_material(base, cq.Vector(19.0, wall_y, plan.center[1] + 19.0))


def test_a_wall_fan_goes_on_the_wall_without_an_opening() -> None:
    c = cavity(top=60.0)
    blocked = ConnectorCutoutParameters(
        edge="positive_y",
        center_offset_mm=0.0,
        bottom_z_mm=5.0,
        width_mm=10.0,
        height_mm=5.0,
    )
    _, plan = lid_plan(
        FAN_40, cavity=c, position="wall", wall_top_z_mm=58.0, openings=[blocked]
    )

    assert plan.edge == "negative_y"


# --- refusals --------------------------------------------------------------


def test_a_fan_too_big_for_the_lid_is_refused() -> None:
    with pytest.raises(ValueError, match="the lid has 34 x 34 mm"):
        lid_plan(FAN_40, cavity=cavity(width=40.0, depth=40.0))


def test_a_fan_moved_past_the_lids_usable_area_is_refused() -> None:
    with pytest.raises(ValueError, match="reach past the lid's usable area"):
        lid_plan(FAN_40, offset_mm=(30.0, 0.0))


def test_a_fan_over_the_display_is_refused() -> None:
    display = cq.Workplane("XY").box(20.0, 20.0, 2.0).val().BoundingBox()  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="The display is under the"):
        lid_plan(FAN_40, display_bounds=display)


def test_a_fan_that_would_hit_a_part_is_refused_by_name_with_the_fix() -> None:
    part = cq.Solid.makeBox(10.0, 10.0, 10.0, pnt=cq.Vector(-5.0, -5.0, 22.0))

    with pytest.raises(ValueError, match="would hit usb.*top_clearance_mm"):
        lid_plan(FAN_40, hardware={"usb": part})


def test_a_fan_that_would_hit_the_base_is_refused() -> None:
    c = cavity()
    boss = cq.Workplane("XY").box(10.0, 10.0, 12.0).translate((0.0, 0.0, 26.0))
    base = box(c).union(boss)

    with pytest.raises(ValueError, match="would hit the base"):
        plan_fan(
            base,
            c,
            fan=get_fan(FAN_40),
            position="lid",
            direction="out",
            lid_mm=2.0,
            offset_mm=(0.0, 0.0),
            openings=[],
            wall_top_z_mm=c.top_z_mm,
            hardware={},
            display_bounds=None,
        )


def test_a_wall_too_short_for_the_fan_says_how_tall_it_must_be() -> None:
    with pytest.raises(ValueError, match="needs 46.0 mm"):
        lid_plan(FAN_40, position="wall", wall_top_z_mm=28.0)


def test_bad_position_or_direction_is_refused() -> None:
    with pytest.raises(ValueError, match="fan_position must be one of"):
        lid_plan(FAN_40, position="floor")

    with pytest.raises(ValueError, match="fan_direction must be one of"):
        lid_plan(FAN_40, direction="sideways")

    assert FAN_POSITIONS == ("lid", "wall") and FAN_DIRECTIONS == ("in", "out")


def test_a_mounting_hole_that_falls_on_a_gap_is_refused() -> None:
    c, plan = lid_plan(FAN_40)
    # A slot in the plate where one mounting hole is.
    slot = cq.Workplane("XY").box(8.0, 8.0, 6.0).translate((16.0, 16.0, 30.0))

    with pytest.raises(ValueError, match="mounting hole.*gap in the plate"):
        cut_fan_bay(
            lid_plate(c).cut(slot),
            plan,
            plate_mm=2.0,
            screw=get_fastener("M3"),
            hole_compensation_mm=0.0,
        )


def test_a_fan_with_nowhere_to_draw_from_says_so() -> None:
    c, plan = lid_plan(FAN_40)
    _, guard = cut_fan_bay(
        lid_plate(c),
        plan,
        plate_mm=2.0,
        screw=get_fastener("M3"),
        hole_compensation_mm=0.0,
    )
    shut = fan_report(
        plan,
        guard,
        plate_mm=2.0,
        screw=get_fastener("M3"),
        openings=[],
        vent_free_mm2=0.0,
    )
    open_box = fan_report(
        plan,
        guard,
        plate_mm=2.0,
        screw=get_fastener("M3"),
        openings=[],
        vent_free_mm2=1000.0,
    )

    assert shut.air_path is False and "add vents" in shut.to_dict()["note"]
    assert open_box.air_path is True and "add vents" not in open_box.to_dict()["note"]
    # The unread figures are flagged every time.
    assert "not read from the maker's own page" in open_box.to_dict()["note"]
    assert open_box.to_dict()["airflow_free_air_m3h"] == 8.2
    assert "not credited" in open_box.to_dict()["note"]


# --- with the hinge and the slide ------------------------------------------


def lid_with_a_fan(c: Cavity) -> tuple[cq.Workplane, cq.Workplane, cq.Shape]:
    _, plan = lid_plan(FAN_30, cavity=c)

    return box(c), lid_plate(c), plan.body


def test_a_fan_on_a_sliding_lid_would_hit_the_entry_wall() -> None:
    c = cavity(width=60.0, depth=100.0)
    base, lid, fan = lid_with_a_fan(c)

    with pytest.raises(
        ValueError, match="fan on the lid needs a hinged or screwed lid"
    ):
        add_slide(
            base,
            lid,
            c,
            lid_mm=2.0,
            clearance_mm=0.2,
            hole_compensation_mm=0.0,
            openings=[],
            hardware={},
            carried={"fan": fan},
        )


def test_a_fan_on_a_hinged_lid_swings_with_it_and_is_checked() -> None:
    c = cavity(width=60.0, depth=50.0)
    pin = get_fastener("M3")
    _, plan = lid_plan(FAN_30, cavity=c)

    def hinge_with(parts: dict[str, cq.Shape]) -> object:
        return add_hinge(
            box(c),
            lid_plate(c),
            c,
            lid_mm=2.0,
            pin=pin,
            hole_compensation_mm=0.0,
            openings=[],
            hardware=parts,
            carried={"fan": plan.body},
        )

    # A part beside the fan, half a millimetre off its frame toward the closure
    # wall: it is clear at rest, but the fan swings toward that wall as the lid
    # lifts, so it meets the part.
    beside = cq.Solid.makeBox(20.0, 5.0, 8.0, pnt=cq.Vector(-10.0, -20.5, 21.0))
    far = cq.Solid.makeBox(20.0, 5.0, 8.0, pnt=cq.Vector(-10.0, -34.0, 21.0))

    assert hinge_with({"far": far}) is not None
    with pytest.raises(ValueError, match="Fan hits beside"):
        hinge_with({"beside": beside})


# --- through the builder ---------------------------------------------------


PI5 = get_raspberry_pi5()
PICO = get_raspberry_pi_pico2()


def assembly(board):  # type: ignore[no-untyped-def]
    return build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )


@cache
def pi5_with_a_fan(**overrides) -> Enclosure:  # type: ignore[no-untyped-def]
    return build_enclosure(
        assembly(PI5),
        board=PI5,
        design=EnclosureDesign(fan=FAN_40, top_clearance_mm=12.0, **dict(overrides)),
    )


def test_the_builder_adds_the_fan_and_reports_it() -> None:
    enclosure = pi5_with_a_fan()
    fan = enclosure.fan

    assert fan is not None
    assert fan.model == "Noctua NF-A4x10 5V" and fan.position == "lid"
    assert fan.screws == "M3 x 10 mm, 4"
    assert fan.guard_cells > 10 and 0.3 < fan.open_ratio < 0.7
    assert fan.air_path and fan.datasheet_read is False
    assert len(enclosure.base.solids().vals()) == 1
    assert len(enclosure.lid.solids().vals()) == 1


def test_the_fans_own_heat_is_in_the_temperature_estimate() -> None:
    enclosure = pi5_with_a_fan()

    assert enclosure.thermal is not None
    assert enclosure.thermal.typical_w == pytest.approx(3.0 + 0.22)
    assert enclosure.thermal.peak_w == pytest.approx(3.0 + 0.25)
    # The fan's airflow is not credited: only its heat is counted.
    assert enclosure.thermal.coefficient_w_m2k == 8.0


def test_vents_keep_off_the_fans_frame() -> None:
    enclosure = build_enclosure(
        assembly(PI5),
        board=PI5,
        design=EnclosureDesign(
            fan=FAN_40, top_clearance_mm=12.0, vent_pattern="hex", vent_area_mm2=300.0
        ),
    )
    spec = enclosure.specification
    z = spec.bottom_z_mm + spec.inner_height_mm + 1.0

    assert enclosure.vents is not None and enclosure.fan is not None
    # The frame's seat, outside the opening and between its holes, is plain
    # plate: no vent was cut under the fan.
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            point = cq.Vector(
                spec.center_x_mm + 19.0 * sx, spec.center_y_mm + 19.0 * sy, z
            )
            assert has_material(enclosure.lid, point)


def test_a_fan_a_pico_box_cannot_hold_is_refused() -> None:
    with pytest.raises(ValueError, match="the lid has"):
        build_enclosure(assembly(PICO), board=PICO, design=EnclosureDesign(fan=FAN_40))


def test_the_design_checks_its_fan_settings() -> None:
    with pytest.raises(ValueError, match="fan must be one of"):
        EnclosureDesign(fan="ACME_9000").validate()

    with pytest.raises(ValueError, match="fan_position must be one of"):
        EnclosureDesign(fan=FAN_40, fan_position="floor").validate()

    with pytest.raises(ValueError, match="fan_direction must be one of"):
        EnclosureDesign(fan=FAN_40, fan_direction="up").validate()

    EnclosureDesign().validate()


def run_build(
    capsys: pytest.CaptureFixture[str], output: Path, *extra: str
) -> tuple[int, dict[str, object], str]:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_5",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *extra,
        ]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_cli_builds_a_fan_bay_and_reports_and_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output, _ = run_build(
        capsys, tmp_path, "--fan", FAN_40, "--top-clearance-mm", "12", "--review"
    )

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    fan = output["fan"]
    assert isinstance(fan, dict)
    assert fan["model"] == "Noctua NF-A4x10 5V" and fan["direction"] == "out"
    assert fan["datasheet_read"] is False and fan["air_path"] is True
    review = output["review"]
    assert isinstance(review, dict) and review["passed"] is True
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["fan"]["fan"] == FAN_40
    assert record["design"]["fan"] == FAN_40
    assert record["thermal"]["typical_w"] == pytest.approx(3.22)


def test_cli_lists_the_fans(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["enclosure", "hardware"]) == 0
    assert set(json.loads(capsys.readouterr().out)["fans"]) == set(list_fans())


def test_cli_refuses_a_fan_that_hits_the_boards_parts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, _, err = run_build(capsys, tmp_path, "--fan", FAN_40)

    assert exit_code == 1
    assert "would hit" in err and "top_clearance_mm" in err
