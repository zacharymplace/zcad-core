from __future__ import annotations

import itertools
import json
import math
from dataclasses import replace
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
from zcad_core.features.enclosure_lid import Cavity
from zcad_core.features.vent_patterns import (
    MAX_CELLS,
    MIN_WEB_MM,
    PATTERNS,
    CellSpec,
    LidZone,
    WallZone,
    _cell_area,
    _profile,
    add_lid_outlets,
    add_wall_inlets,
    fill_zone,
    grid,
    solid_tester,
)
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def cavity() -> Cavity:
    return Cavity(
        center_x_mm=0.0,
        center_y_mm=0.0,
        width_mm=60.0,
        depth_mm=30.0,
        floor_z_mm=2.0,
        top_z_mm=24.0,
        wall_mm=2.0,
    )


def box(c: Cavity) -> cq.Workplane:
    """A base with a plain cavity, and a plate over it."""

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


def plate(c: Cavity, lid_mm: float = 2.0) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(c.width_mm + 4.0, c.depth_mm + 4.0, lid_mm, centered=(True, True, False))
        .translate((0, 0, c.top_z_mm))
    )


def has_material(model: cq.Workplane, point: cq.Vector) -> bool:
    return solid_tester(model)(point)


def wall_zone(c: Cavity, edge: str = "positive_y") -> WallZone:
    return WallZone(edge, c, v_range=(3.5, 15.5), keepout_mm=5.0)


# --- the cell shapes -------------------------------------------------------


def test_hex_area_and_round_area_follow_the_formulas() -> None:
    hexagon = CellSpec("hex", 5.0, 0.0)
    round_hole = CellSpec("round", 6.0, 6.0)

    assert _cell_area(hexagon, wall=False) == pytest.approx(math.sqrt(3) / 2 * 25.0)
    # A 24-sided polygon is a hair under the circle, so the figure is honest.
    assert _cell_area(round_hole, wall=False) == pytest.approx(math.pi * 9.0, rel=0.02)
    assert _cell_area(round_hole, wall=False) < math.pi * 9.0
    assert _cell_area(CellSpec("slots", 2.0, 10.0), wall=True) == pytest.approx(20.0)
    # A louver's flow area is counted at the cosine of its 45 degree slant.
    assert _cell_area(CellSpec("louvers", 14.0, 3.0), wall=True) == pytest.approx(
        14.0 * 3.0 * math.cos(math.radians(45))
    )


@pytest.mark.parametrize(
    "spec", [CellSpec("hex", 5.0, 0.0), CellSpec("round", 6.0, 6.0)]
)
def test_a_hole_through_a_wall_has_no_ceiling_flatter_than_45_degrees(
    spec: CellSpec,
) -> None:
    points = _profile(spec, wall=True)
    edges = list(zip(points, [*points[1:], points[0]]))

    for (u0, v0), (u1, v1) in edges:
        if v0 >= -1e-9 and v1 >= -1e-9:
            # An edge in the upper half is a ceiling. It is at least 45 degrees
            # steep, or a level bridge no longer than 4 mm.
            level_bridge = abs(v1 - v0) < 1e-9 and abs(u1 - u0) <= 4.0
            assert level_bridge or abs(v1 - v0) >= abs(u1 - u0) - 1e-9


def test_a_round_hole_through_a_wall_is_pointed_and_through_the_lid_is_round() -> None:
    wall = _profile(CellSpec("round", 6.0, 6.0), wall=True)
    lid = _profile(CellSpec("round", 6.0, 6.0), wall=False)

    assert max(v for _, v in wall) == pytest.approx(3.0 * math.sqrt(2))
    assert max(v for _, v in lid) == pytest.approx(3.0, abs=0.01)


@pytest.mark.parametrize(
    ("spec", "pitch"),
    [
        (CellSpec("hex", 5.0, 0.0), 5.0 + MIN_WEB_MM),
        (CellSpec("round", 6.0, 6.0), 6.0 + MIN_WEB_MM),
    ],
)
def test_staggered_cells_are_a_web_apart_in_every_direction(
    spec: CellSpec, pitch: float
) -> None:
    centers = grid(spec, (-30.0, 30.0, -15.0, 15.0))
    nearest = min(
        math.dist(a, b) for i, a in enumerate(centers) for b in centers[i + 1 :]
    )

    assert len(centers) > 20
    assert nearest == pytest.approx(pitch)


def test_cells_fit_inside_the_region_and_slots_keep_their_web() -> None:
    spec = CellSpec("slots", 2.0, 6.0)
    region = (-20.0, 20.0, -10.0, 10.0)
    centers = grid(spec, region)

    assert centers
    for u, v in centers:
        assert region[0] <= u - 1.0 and u + 1.0 <= region[1]
        assert region[2] <= v - 3.0 and v + 3.0 <= region[3]
    xs = sorted({round(u, 6) for u, _ in centers})
    assert min(b - a for a, b in itertools.pairwise(xs)) == pytest.approx(
        2.0 + MIN_WEB_MM
    )


# --- cells in a real zone --------------------------------------------------


@pytest.mark.parametrize("kind", ["slots", "hex", "round", "louvers"])
def test_a_wall_fill_reaches_its_target_and_cuts_through_the_wall(kind: str) -> None:
    c = cavity()
    base = box(c)
    cut, fills = add_wall_inlets(
        base,
        c,
        kind=kind,
        target_mm2=120.0,
        blocked_edges=[],
        top_z_mm=c.top_z_mm - 4.0,
        corner_keepout_mm=5.0,
    )

    # Two long walls share the target.
    assert len(fills) == 2
    assert all(fill.area_mm2 >= 60.0 for fill in fills)
    zone = wall_zone(c)
    first = fills[1] if zone.edge == "positive_y" else fills[0]
    u, v = first.centers[0]
    # Through the wall's thickness the cell is open, and the web round it solid.
    assert not has_material(cut, zone.point(u, v, 1.0))
    if kind != "louvers":
        # A louver slides down across the wall, so only the middle is level.
        assert not has_material(cut, zone.point(u, v, 0.3))
    assert has_material(cut, zone.point(u, v + 12.0, 1.0))
    assert len(cut.solids().vals()) == 1


def test_inlets_sit_low_in_the_wall_and_the_lid_takes_the_outlets() -> None:
    c = cavity()
    base = box(c)
    _, fills = add_wall_inlets(
        base,
        c,
        kind="hex",
        target_mm2=100.0,
        blocked_edges=[],
        top_z_mm=20.0,
        corner_keepout_mm=5.0,
    )
    lid, outlet = add_lid_outlets(
        plate(c), c, lid_mm=2.0, kind="hex", target_mm2=sum(f.area_mm2 for f in fills)
    )

    for fill in fills:
        for _, v in fill.centers:
            assert c.floor_z_mm + 1.5 <= v <= 14.0
    assert outlet.area_mm2 >= sum(f.area_mm2 for f in fills)
    u, v = outlet.centers[0]
    assert not has_material(lid, LidZone(c, lid_mm=2.0, inset_mm=3.0).point(u, v, 1.0))
    assert len(lid.solids().vals()) == 1


def test_an_opening_in_the_wall_keeps_cells_a_web_away() -> None:
    c = cavity()
    base = box(c).cut(cq.Workplane("XY").box(8.0, 8.0, 6.0).translate((0.0, 15.0, 8.0)))
    zone = wall_zone(c)
    fill = fill_zone(zone, "hex", 80.0, is_solid=solid_tester(base))

    assert fill.centers
    for u, v in fill.centers:
        # The opening spans u in [-4, 4] and z in [5, 11]; cells stay clear of it.
        assert abs(u) > 4.0 + 2.5 or v < 5.0 - 2.5 or v > 11.0 + 2.5


def test_a_boss_behind_the_wall_keeps_cells_from_opening_onto_it() -> None:
    c = cavity()
    boss = cq.Workplane("XY").box(10.0, 6.0, 14.0).translate((0.0, 12.0, 9.0))
    base = box(c).union(boss)
    zone = wall_zone(c)
    fill = fill_zone(zone, "round", 60.0, is_solid=solid_tester(base))

    assert fill.centers
    for u, _ in fill.centers:
        # The boss stands behind u in [-5, 5].
        assert abs(u) >= 5.0 + 2.0


def test_cells_are_taken_from_the_middle_of_the_zone_outward() -> None:
    c = cavity()
    zone = wall_zone(c)
    fill = fill_zone(zone, "hex", 40.0, is_solid=solid_tester(box(c)))
    middle = sum(u for u, _ in fill.centers) / len(fill.centers)

    assert abs(middle) < 4.0


def test_louvers_slope_down_to_the_outside_and_block_a_straight_look() -> None:
    c = cavity()
    base = box(c)
    cut, fills = add_wall_inlets(
        base,
        c,
        kind="louvers",
        target_mm2=40.0,
        blocked_edges=[],
        top_z_mm=20.0,
        corner_keepout_mm=5.0,
    )
    zone = wall_zone(c, "positive_y")
    u, v = (fills[1] if fills[1].centers else fills[0]).centers[0]

    # On the inner face the slot is at its height; on the outer face it has
    # slid 2 mm down, so a level line through the middle meets wall.
    assert not has_material(cut, zone.point(u, v, 2.0 - 0.01))  # inner face
    assert not has_material(cut, zone.point(u, v - 1.9, 0.01))  # outer face, lower
    assert has_material(cut, zone.point(u, v + 1.5, 0.01))  # a level look is stopped


def test_louvers_are_for_walls_not_the_lid() -> None:
    c = cavity()

    with pytest.raises(ValueError, match="louvers vents are for walls"):
        fill_zone(
            LidZone(c, lid_mm=2.0, inset_mm=3.0),
            "louvers",
            50.0,
            is_solid=solid_tester(plate(c)),
        )


def test_a_target_the_zone_cannot_pass_says_how_much_it_can() -> None:
    c = cavity()

    with pytest.raises(ValueError, match=r"can pass at most \d+ mm2"):
        fill_zone(wall_zone(c), "hex", 5000.0, is_solid=solid_tester(box(c)))


def test_both_long_walls_open_leaves_nowhere_to_vent() -> None:
    c = cavity()

    with pytest.raises(ValueError, match="nowhere to vent"):
        add_wall_inlets(
            box(c),
            c,
            kind="hex",
            target_mm2=50.0,
            blocked_edges=["positive_y", "negative_y"],
            top_z_mm=20.0,
            corner_keepout_mm=5.0,
        )


def test_walls_too_low_for_a_band_are_refused() -> None:
    c = cavity()

    with pytest.raises(ValueError, match="too low for vent inlets"):
        add_wall_inlets(
            box(c),
            c,
            kind="hex",
            target_mm2=50.0,
            blocked_edges=[],
            top_z_mm=c.floor_z_mm + 3.0,
            corner_keepout_mm=5.0,
        )


def test_the_cell_count_is_bounded() -> None:
    assert MAX_CELLS == 400
    assert set(PATTERNS) == {"slots", "hex", "round", "louvers"}


# --- through the enclosure builder -----------------------------------------


def board_assembly():  # type: ignore[no-untyped-def]
    return build_board_assembly(
        board=BOARD,
        board_placement=Placement(),
        connector_access_clearance_mm=2.0,
    )


def display_assembly():  # type: ignore[no-untyped-def]
    return build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )


@cache
def vented(pattern: str = "hex", area: float = 300.0) -> Enclosure:
    return build_enclosure(
        board_assembly(),
        board=BOARD,
        design=EnclosureDesign(
            bottom_clearance_mm=6.0, vent_pattern=pattern, vent_area_mm2=area
        ),
    )


@pytest.mark.parametrize("pattern", ["slots", "hex", "round", "louvers"])
def test_the_builder_cuts_inlets_and_larger_outlets_and_reports_them(
    pattern: str,
) -> None:
    enclosure = vented(pattern, 300.0 if pattern != "louvers" else 150.0)
    report = enclosure.vents

    assert report is not None
    assert report.pattern == pattern
    assert report.inlet_cells > 0 and report.outlet_cells > 0
    assert report.inlet_mm2 >= report.target_mm2 / 2
    assert report.outlet_not_smaller
    assert report.outlet_mm2 >= report.target_mm2
    # Louvers are for walls, so the lid takes slots.
    if pattern == "louvers":
        assert report.outlet.startswith("slots")
    assert len(enclosure.base.solids().vals()) == 1
    assert len(enclosure.lid.solids().vals()) == 1


def test_a_vented_box_has_less_material_and_the_same_footprint() -> None:
    plain = build_enclosure(
        board_assembly(),
        board=BOARD,
        design=EnclosureDesign(bottom_clearance_mm=6.0),
    )
    enclosure = vented("hex", 300.0)

    assert enclosure.vents is not None and plain.vents is None
    assert enclosure.base.val().Volume() < plain.base.val().Volume()  # type: ignore[union-attr]
    assert enclosure.lid.val().Volume() < plain.lid.val().Volume()  # type: ignore[union-attr]
    base = enclosure.base.val().BoundingBox()  # type: ignore[union-attr]
    assert base.xlen == pytest.approx(plain.base.val().BoundingBox().xlen)  # type: ignore[union-attr]


def test_a_display_lid_gets_outlets_clear_of_its_window() -> None:
    enclosure = build_enclosure(
        display_assembly(),
        board=BOARD,
        display=DISPLAY,
        design=EnclosureDesign(vent_pattern="hex", vent_area_mm2=250.0),
    )

    assert enclosure.vents is not None and enclosure.vents.outlet_cells > 0
    assert len(enclosure.lid.solids().vals()) == 1


@pytest.mark.parametrize("attachment", ["screws", "snap", "hinge", "slide"])
def test_vents_work_with_every_lid_attachment(attachment: str) -> None:
    enclosure = build_enclosure(
        board_assembly(),
        board=BOARD,
        design=EnclosureDesign(
            lid_attachment=attachment,
            bottom_clearance_mm=10.0,
            vent_pattern="hex",
            vent_area_mm2=100.0,
        ),
    )

    assert enclosure.vents is not None
    assert enclosure.vents.outlet_not_smaller
    assert len(enclosure.lid.solids().vals()) == 1


def test_a_target_the_walls_cannot_pass_is_refused_with_the_shared_target() -> None:
    with pytest.raises(ValueError, match="shared between 2 walls"):
        build_enclosure(
            board_assembly(),
            board=BOARD,
            design=EnclosureDesign(
                lid_attachment="slide",
                bottom_clearance_mm=10.0,
                vent_pattern="hex",
                vent_area_mm2=900.0,
            ),
        )


def test_the_design_checks_its_vent_settings() -> None:
    with pytest.raises(ValueError, match="vent_pattern must be one of"):
        EnclosureDesign(vent_pattern="zigzag").validate()

    with pytest.raises(ValueError, match="vent_area_mm2 must not be negative"):
        EnclosureDesign(vent_area_mm2=-1.0).validate()

    with pytest.raises(ValueError, match="vent_slots or vent_area_mm2, not both"):
        EnclosureDesign(vent_slots=2, vent_area_mm2=100.0).validate()

    with pytest.raises(ValueError, match="needs a vent_area_mm2"):
        EnclosureDesign(vent_pattern="hex").validate()


def test_vent_slots_alone_is_unchanged_and_has_no_report() -> None:
    enclosure = build_enclosure(
        board_assembly(),
        board=BOARD,
        design=EnclosureDesign(bottom_clearance_mm=6.0, vent_slots=2),
    )

    assert enclosure.vents is None


def run_build(
    capsys: pytest.CaptureFixture[str], output: Path, *extra: str
) -> tuple[int, dict[str, object], str]:
    exit_code = main(
        [
            "enclosure",
            "build",
            "--board",
            "raspberry_pi_pico_2",
            "--bottom-clearance-mm",
            "6",
            "--output-directory",
            str(output),
            "--printer-profile",
            str(PRINTER_PROFILE),
            *extra,
        ]
    )
    captured = capsys.readouterr()

    return exit_code, json.loads(captured.out) if captured.out else {}, captured.err


def test_cli_cuts_a_pattern_and_reports_and_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, output, _ = run_build(
        capsys,
        tmp_path,
        "--vent-pattern",
        "hex",
        "--vent-area-mm2",
        "300",
        "--review",
    )

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    vents = output["vents"]
    assert isinstance(vents, dict)
    assert vents["pattern"] == "hex" and vents["outlet_not_smaller"] is True
    assert vents["inlet_mm2"] >= 150.0
    assert "credits no vents" in vents["note"]
    review = output["review"]
    assert isinstance(review, dict) and review["passed"] is True
    record = json.loads((tmp_path / "enclosure.json").read_text())
    assert record["vents"]["pattern"] == "hex"
    assert record["design"]["vent_area_mm2"] == 300.0


def test_cli_refuses_a_pattern_with_no_area_or_with_slots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code, _, err = run_build(capsys, tmp_path / "a", "--vent-pattern", "hex")
    assert exit_code == 1 and "needs a vent_area_mm2" in err

    exit_code, _, err = run_build(
        capsys, tmp_path / "b", "--vent-area-mm2", "100", "--vent-slots", "2"
    )
    assert exit_code == 1 and "not both" in err


def test_vent_settings_survive_a_revision_record(tmp_path: Path) -> None:
    design = replace(EnclosureDesign(), vent_pattern="round", vent_area_mm2=200.0)

    assert EnclosureDesign(**json.loads(json.dumps(design.__dict__))) == design
