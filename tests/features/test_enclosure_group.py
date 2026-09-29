from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import (
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi5

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
A1_MINI_BED_MM = 180.0


@pytest.fixture(scope="module")
def pair() -> GroupEnclosure:
    return build_group_enclosure()


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    probe = cq.Solid.makeBox(0.4, 0.4, 0.4, pnt=cq.Vector(x - 0.2, y - 0.2, z - 0.2))

    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Shape)

    return intersection_volume(solid, probe) > 0.01


def test_pi5_spec_matches_the_published_board() -> None:
    pi = get_raspberry_pi5()

    assert (pi.board_width_mm, pi.board_length_mm) == (56.0, 85.0)
    # The 58 x 49 mm hole pattern, portrait.
    assert (pi.mounting_hole_spacing_x_mm, pi.mounting_hole_spacing_y_mm) == (
        49.0,
        58.0,
    )
    assert {port.edge for port in pi.ports} == {"positive_y", "negative_x"}


def test_a_pair_passes_every_check_and_fits_the_a1_mini_bed(
    pair: GroupEnclosure,
) -> None:
    assert pair.passed, pair.checks
    assert pair.outer_size_mm[0] < A1_MINI_BED_MM
    assert pair.outer_size_mm[1] < A1_MINI_BED_MM
    assert len(pair.hardware) == 2


def test_each_pi_sits_on_four_standoffs_with_a_pilot_hole(pair: GroupEnclosure) -> None:
    pi = get_raspberry_pi5()
    wall = pair.design.wall_mm

    for bay in pair.bays:
        center_x = wall + bay.center_x_mm

        for sx in (-1, 1):
            for sy in (-1, 1):
                x = center_x + sx * pi.mounting_hole_spacing_x_mm / 2
                y = pair.pi_center_y_mm + sy * pi.mounting_hole_spacing_y_mm / 2
                z = pair.design.floor_mm + pair.design.standoff_height_mm / 2

                assert has_material(pair.base, x + 2.5, y, z)
                assert not has_material(pair.base, x, y, z)


def test_growing_the_row_adds_a_bay_without_changing_the_others() -> None:
    three = build_group_enclosure(("pi5", "reserved", "pi5"))
    two = build_group_enclosure(("pi5", "pi5"))

    assert three.passed
    assert three.bays[1].kind == "reserved"
    # A reserved bay holds a Pi's slot, so a Pi drops in later.
    assert len(three.hardware) == 3
    assert three.bays[0].slot_start_mm == two.bays[0].slot_start_mm
    assert three.outer_size_mm[0] > two.outer_size_mm[0]


def test_an_open_bay_is_a_shelf_with_no_pi_envelope() -> None:
    row = build_group_enclosure(("pi5", "open"))

    assert row.passed
    assert len(row.hardware) == 1
    assert row.bays[1].slot_end_mm - row.bays[1].slot_start_mm == 40.0


def test_the_lid_check_fails_when_headroom_is_too_low() -> None:
    low = build_group_enclosure(design=GroupDesign(headroom_mm=10.0))

    assert not low.checks["hardware_clear_of_lid"]
    assert not low.passed


def test_join_bosses_and_holes_line_up_on_opposite_walls(pair: GroupEnclosure) -> None:
    (y, z), _ = pair.join_positions
    wall = pair.design.wall_mm

    # An insert boss inside the left wall; a clearance hole through the right.
    assert has_material(pair.base, wall + 4.0, y, z + 3.0)
    assert not has_material(pair.base, pair.outer_size_mm[0] - wall / 2, y, z)
    assert has_material(pair.base, pair.outer_size_mm[0] - wall / 2, y, z + 3.0)


def test_without_join_bolts_the_walls_are_plain() -> None:
    plain = build_group_enclosure(design=GroupDesign(join_bolts=False))

    assert plain.join_positions == ()
    assert plain.recommended_join_screw_mm is None
    assert has_material(
        plain.base, plain.outer_size_mm[0] - 1.0, 60.0, plain.design.floor_mm + 8.0
    )


def test_the_lid_has_vents_over_each_soc(pair: GroupEnclosure) -> None:
    pi = get_raspberry_pi5()
    top = pair.cavity_top_z_mm + pair.design.lid_mm / 2

    for bay in pair.bays:
        x = pair.design.wall_mm + bay.center_x_mm
        y = pair.pi_center_y_mm + pi.cooler_center_y_mm

        assert not has_material(pair.lid, x, y, top)
        assert has_material(pair.lid, x, y + 2.5, top)

    unvented = build_group_enclosure(design=GroupDesign(vents=False))

    assert has_material(unvented.lid, x, y, top)


def test_screw_lengths_follow_the_lid_and_walls(pair: GroupEnclosure) -> None:
    # 3 mm lid + 5 mm insert; 2 x 2 mm walls + 5 mm insert.
    assert pair.recommended_lid_screw_mm == 8
    assert pair.recommended_join_screw_mm == 8


@pytest.mark.parametrize("bays", [(), ("pi5", "nope")])
def test_bad_bays_are_refused(bays: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        build_group_enclosure(bays)  # type: ignore[arg-type]


def test_a_tiny_service_gap_is_refused() -> None:
    with pytest.raises(ValueError, match="service_gap_mm"):
        build_group_enclosure(design=GroupDesign(service_gap_mm=15.0))


def test_the_cli_exports_a_validated_pair_with_a_review(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    assert output["bays"] == ["pi5", "pi5"]
    assert output["screws"]["lid"].startswith("M3 x 8 mm")
    assert Path(output["review_step"]).is_file()
    assert Path(output["parts"]["base"]["stl"]).is_file()


def test_the_cli_refuses_a_row_wider_than_the_printer(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            "pi5,pi5,pi5",
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "bolt them together" in captured.err
    assert not list(tmp_path.glob("*.stl"))
