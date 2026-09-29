from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import (
    Bay,
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi5

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


@pytest.fixture(scope="module")
def mixed() -> GroupEnclosure:
    """A raised Pi over a board mounted under it, beside one under a HAT."""

    return build_group_enclosure((Bay(standoff_height_mm=12.0), Bay(headroom_mm=30.0)))


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    probe = cq.Solid.makeBox(0.4, 0.4, 0.4, pnt=cq.Vector(x - 0.2, y - 0.2, z - 0.2))
    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Shape)

    return intersection_volume(solid, probe) > 0.01


def standoff_xy(group: GroupEnclosure, index: int) -> tuple[float, float]:
    """A point on the ring of the bay's first standoff, off its pilot hole."""

    pi = get_raspberry_pi5()
    bay = group.bays[index]
    x = group.design.wall_mm + bay.center_x_mm - pi.mounting_hole_spacing_x_mm / 2
    y = group.pi_center_y_mm - pi.mounting_hole_spacing_y_mm / 2

    return x - 2.5, y


def test_a_bay_with_no_overrides_takes_the_design_defaults() -> None:
    plain = build_group_enclosure(("pi5", Bay("pi5")))

    assert plain.passed
    assert [bay.standoff_height_mm for bay in plain.bays] == [4.0, 4.0]
    assert [bay.headroom_mm for bay in plain.bays] == [18.0, 18.0]


def test_each_bay_stands_its_pi_at_its_own_height(mixed: GroupEnclosure) -> None:
    floor = mixed.design.floor_mm
    tall_x, tall_y = standoff_xy(mixed, 0)
    short_x, short_y = standoff_xy(mixed, 1)

    assert mixed.bays[0].board_bottom_z_mm == floor + 12.0
    assert mixed.bays[1].board_bottom_z_mm == floor + 4.0
    assert has_material(mixed.base, tall_x, tall_y, floor + 10.0)
    assert has_material(mixed.base, short_x, short_y, floor + 2.0)
    assert not has_material(mixed.base, short_x, short_y, floor + 6.0)


def test_the_box_is_as_tall_as_its_tallest_bay_needs(mixed: GroupEnclosure) -> None:
    assert mixed.passed, mixed.checks
    # Bay 1: 2 floor + 4 standoff + 1.4 board + 30 headroom.
    assert mixed.cavity_top_z_mm == pytest.approx(37.4)
    assert mixed.outer_size_mm[2] == pytest.approx(37.4)
    assert mixed.cavity_top_z_mm >= max(bay.needed_top_z_mm for bay in mixed.bays)


def test_a_shorter_bay_gets_spare_room_above_its_board(mixed: GroupEnclosure) -> None:
    # Bay 0 needs 18 mm above its board and the taller bay leaves it 22.
    assert mixed.room_above_board_mm(mixed.bays[0]) == pytest.approx(22.0)
    assert mixed.room_above_board_mm(mixed.bays[1]) == pytest.approx(30.0)


def test_openings_follow_each_bays_board_height(mixed: GroupEnclosure) -> None:
    wall = mixed.design.wall_mm
    pi = get_raspberry_pi5()
    ethernet = next(port for port in pi.ports if port.identifier == "ETHERNET")
    back = mixed.outer_size_mm[1] - wall / 2

    for bay in mixed.bays:
        x = wall + bay.center_x_mm + ethernet.center_mm
        centre = bay.board_top_z_mm + ethernet.height_mm / 2

        assert not has_material(mixed.base, x, back, centre)
        assert has_material(mixed.base, x, back, bay.board_top_z_mm - 2.0)


def test_a_bays_headroom_is_checked_against_the_lid() -> None:
    low = build_group_enclosure((Bay(headroom_mm=10.0),))

    assert not low.checks["hardware_clear_of_lid"]


def test_a_low_headroom_bay_beside_a_tall_one_still_fits() -> None:
    row = build_group_enclosure((Bay(headroom_mm=10.0), Bay(headroom_mm=30.0)))

    assert row.passed, row.checks


def test_an_open_bays_headroom_sets_the_shelf_height() -> None:
    row = build_group_enclosure(("pi5", Bay("open", headroom_mm=40.0)))

    assert row.passed
    assert row.bays[1].board_top_z_mm == row.design.floor_mm
    assert row.cavity_top_z_mm == pytest.approx(row.design.floor_mm + 40.0)


def test_an_open_bay_takes_no_standoff() -> None:
    with pytest.raises(ValueError, match="no board to stand off"):
        build_group_enclosure((Bay("open", standoff_height_mm=5.0),))


def test_a_standoff_too_short_for_the_sd_card_is_refused() -> None:
    with pytest.raises(ValueError, match="microSD card clears the floor"):
        build_group_enclosure((Bay(standoff_height_mm=1.5),))


def test_a_zero_headroom_is_refused() -> None:
    with pytest.raises(ValueError, match="headroom_mm"):
        build_group_enclosure((Bay(headroom_mm=0.0),))


def test_the_design_defaults_apply_to_a_bay_that_sets_none() -> None:
    row = build_group_enclosure(
        ("pi5", Bay(standoff_height_mm=6.0)),
        design=GroupDesign(standoff_height_mm=8.0),
    )

    assert [bay.standoff_height_mm for bay in row.bays] == [8.0, 6.0]


def run(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str
) -> tuple[int, str, str]:
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            bays,
            "--output-directory",
            str(tmp_path),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    captured = capsys.readouterr()

    return exit_code, captured.out, captured.err


def test_the_cli_takes_per_bay_heights_and_reports_them(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, out, _ = run(capsys, tmp_path, "pi5:standoff=12,pi5:headroom=30")
    output = json.loads(out)

    assert exit_code == 0
    assert output["bays"] == ["pi5", "pi5"]
    assert output["validation_status"] == "PASS"
    assert output["outer_size_mm"][2] == pytest.approx(37.4)
    assert [bay["standoff_mm"] for bay in output["bay_heights"]] == [12.0, 4.0]
    assert [bay["room_above_board_mm"] for bay in output["bay_heights"]] == [
        22.0,
        30.0,
    ]


@pytest.mark.parametrize(
    ("bays", "message"),
    [
        ("pi5:height=3", "standoff=<mm> or headroom=<mm>"),
        ("pi5:standoff", "standoff=<mm> or headroom=<mm>"),
        ("pi5:standoff=tall", "needs a number"),
        ("hat", "bay kind must be one of"),
    ],
)
def test_the_cli_refuses_a_malformed_bay(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str, message: str
) -> None:
    exit_code, _, err = run(capsys, tmp_path, bays)

    assert exit_code == 1
    assert message in err
