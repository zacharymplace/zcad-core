from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import (
    Bay,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.features.enclosure_group_dividers import (
    Divider,
    DividerPlacement,
    divider_cuts,
    notch_cut,
    tie_cuts,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi5

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PI = get_raspberry_pi5()


def row(divider: Divider | None, kind: str = "pi5") -> GroupEnclosure:
    return build_group_enclosure(("pi5", Bay(kind, divider=divider)))  # type: ignore[arg-type]


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    probe = cq.Solid.makeBox(0.4, 0.4, 0.4, pnt=cq.Vector(x - 0.2, y - 0.2, z - 0.2))
    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Shape)

    return intersection_volume(solid, probe) > 0.01


def middle(group: GroupEnclosure) -> float:
    """The X of the divider's middle."""

    bay = group.bays[1]

    return group.design.wall_mm + bay.divider_start_mm + group.design.divider_mm / 2


def top(group: GroupEnclosure) -> float:
    return group.cavity_top_z_mm


def test_a_bay_without_a_divider_is_unchanged() -> None:
    plain = build_group_enclosure()

    assert plain.bays[1].divider is None
    assert plain.outer_size_mm[0] == 176.0
    assert not has_material(plain.base, middle(row(Divider())), 40.0, 10.0)


def test_a_solid_divider_runs_wall_to_wall_and_floor_to_lid() -> None:
    group = row(Divider())
    x = middle(group)
    floor = group.design.floor_mm

    assert group.passed, group.checks
    for y in (3.0, 30.0, 60.0, group.outer_size_mm[1] - 3.0):
        for z in (floor + 1.0, floor + 10.0, top(group) - 0.5):
            assert has_material(group.base, x, y, z), (y, z)


def test_a_divider_adds_its_clearance_and_thickness_to_the_width() -> None:
    group = row(Divider())

    assert group.outer_size_mm[0] == pytest.approx(176.0 + 0.75 + 2.0)
    # The right-hand Pi still has the same slot; the row just moved over.
    assert group.bays[1].slot_start_mm - group.bays[1].gap_start_mm == 25.0


def test_the_divider_stands_clear_of_the_pi_beside_it() -> None:
    group = row(Divider(vents=True, notch=True, tie_slots=True))
    left = group.bays[0]
    board_edge = group.design.wall_mm + left.slot_end_mm - group.design.slot_pad_mm
    divider_face = group.design.wall_mm + group.bays[1].divider_start_mm

    assert divider_face - board_edge == pytest.approx(0.75 + group.design.slot_pad_mm)
    assert group.checks["hardware_clear_of_base"]


def test_a_low_divider_stops_at_its_height() -> None:
    group = row(Divider(height_mm=12.0))
    x = middle(group)
    floor = group.design.floor_mm

    assert group.passed
    assert has_material(group.base, x, 30.0, floor + 11.0)
    assert not has_material(group.base, x, 30.0, floor + 13.0)


def test_vents_are_slots_near_the_top_of_a_full_divider() -> None:
    group = row(Divider(vents=True))
    x = middle(group)
    z = top(group) - 6.0

    # The first slot is 12 mm along, 2.4 mm wide; the next 6 mm on.
    assert not has_material(group.base, x, group.design.wall_mm + 12.0, z)
    assert has_material(group.base, x, group.design.wall_mm + 15.0, z)
    assert not has_material(group.base, x, group.design.wall_mm + 18.0, z)
    # Solid below the vent zone and above it.
    assert has_material(
        group.base, x, group.design.wall_mm + 12.0, group.design.floor_mm + 4.0
    )
    assert has_material(group.base, x, group.design.wall_mm + 12.0, top(group) - 1.5)


def test_the_notch_passes_the_left_pis_header() -> None:
    group = row(Divider(notch=True))
    x = middle(group)
    left = group.bays[0]
    header_y = group.pi_center_y_mm + PI.header_center_y_mm

    for offset in (-8.0, 0.0, 8.0):
        assert not has_material(
            group.base, x, header_y + offset, left.board_top_z_mm + 4.0
        )

    assert has_material(group.base, x, header_y + 13.0, left.board_top_z_mm + 4.0)
    assert has_material(group.base, x, header_y, left.board_top_z_mm - 2.0)
    assert has_material(group.base, x, header_y, left.board_top_z_mm + 11.5)


def test_tie_slots_are_two_rows_of_slot_pairs_a_way_back() -> None:
    group = row(Divider(tie_slots=True))
    x = middle(group)
    floor = group.design.floor_mm
    center = group.design.wall_mm + 0.75 * group.inner_size_mm[1]

    for side in (-10.0, 10.0):
        for bottom in (3.0, 9.0):
            assert not has_material(group.base, x, center + side, floor + bottom + 1.0)

    assert has_material(group.base, x, center, floor + 4.0)
    assert has_material(group.base, x, center + 10.0, floor + 7.0)


def test_vents_leave_out_slots_that_would_crowd_the_notch_or_ties() -> None:
    placement = DividerPlacement(
        x_start_mm=100.0,
        thickness_mm=2.0,
        front_y_mm=2.0,
        back_y_mm=94.0,
        floor_top_z_mm=2.0,
        inner_height_mm=23.4,
        notch_center_y_mm=38.5,
        notch_bottom_z_mm=7.4,
        notch_width_mm=20.0,
        notch_height_mm=10.0,
    )
    plain = divider_cuts(Divider(vents=True), placement)
    crowded = divider_cuts(Divider(vents=True, notch=True, tie_slots=True), placement)
    features = [notch_cut(placement), *tie_cuts(placement)]
    vents = [cut for cut in crowded if cut not in features]

    # Slots at 6 mm pitch from 12 mm in to 12 mm short of the back wall.
    assert len(plain) == 12
    assert 0 < len(vents) < len(plain)
    for y_min, y_max, _, _ in vents:
        for n_min, n_max, _, _ in features:
            assert y_max + 3.0 <= n_min or y_min - 3.0 >= n_max


def test_a_divider_bonds_into_the_walls_as_one_solid_with_the_lid_seat_clear() -> None:
    group = row(Divider(vents=True, notch=True, tie_slots=True))

    assert len(group.base.solids().vals()) == 1
    assert group.checks["base_and_lid_clear"]


def test_the_gap_boss_sits_against_the_divider_and_the_cable_exit_stays_open() -> None:
    group = row(Divider())
    wall = group.design.wall_mm
    right = group.bays[1]
    boss_x = wall + right.gap_start_mm + 4.1 - 0.5
    boss_y = wall + 4.1 - 0.5
    exit_x = wall + right.slot_start_mm - 1.0 - 4.0

    assert group.passed
    # The ring beside the pilot hole, and the boss's edge sunk into the divider.
    assert has_material(group.base, boss_x + 3.2, boss_y, top(group) - 8.0)
    assert has_material(group.base, boss_x - 3.9, boss_y, top(group) - 8.0)
    assert not has_material(
        group.base, exit_x, wall / 2, group.bays[1].board_top_z_mm + 4.0
    )


def test_a_divider_beside_an_open_bay_centres_its_notch_mid_cavity() -> None:
    group = build_group_enclosure(("open", Bay("pi5", divider=Divider(notch=True))))
    x = middle(group)

    assert group.passed
    assert not has_material(
        group.base, x, group.pi_center_y_mm, group.design.floor_mm + 6.0
    )


def test_the_first_bay_takes_no_divider() -> None:
    with pytest.raises(ValueError, match="first bay takes none"):
        build_group_enclosure((Bay("pi5", divider=Divider()), "pi5"))


@pytest.mark.parametrize(
    ("divider", "message"),
    [
        (Divider(height_mm=0.0), "height_mm must be greater than zero"),
        (Divider(height_mm=12.0, vents=True), "vents are for a full-height divider"),
        (Divider(height_mm=30.0), "as tall as the"),
        (Divider(height_mm=12.0, notch=True), "notch reaches"),
        (Divider(height_mm=10.0, tie_slots=True), "tie slots need"),
    ],
)
def test_an_unworkable_divider_is_refused(divider: Divider, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        row(divider)


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


def test_the_cli_takes_dividers_and_reports_them(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, out, _ = run(capsys, tmp_path, "pi5,pi5:divider=vents+notch+ties")
    output = json.loads(out)
    divider = output["bay_heights"][1]["divider"]

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    assert output["bay_heights"][0]["divider"] is None
    assert divider["vents"] and divider["notch"] and divider["tie_slots"]
    assert divider["full_height"] is True
    assert output["outer_size_mm"][0] == pytest.approx(178.75)


def test_the_cli_takes_a_low_divider(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, out, _ = run(capsys, tmp_path, "pi5,pi5:divider=h12")
    divider = json.loads(out)["bay_heights"][1]["divider"]

    assert exit_code == 0
    assert divider["full_height"] is False
    assert divider["height_mm"] == 12.0


@pytest.mark.parametrize(
    ("bays", "message"),
    [
        ("pi5,pi5:divider=thick", "a divider is solid, vents, notch, ties"),
        ("pi5,pi5:divider=hhigh", "a divider is solid, vents, notch, ties"),
        ("pi5,pi5:divider", "bay option must be standoff=<mm>"),
        ("pi5:divider=solid,pi5", "first bay takes none"),
        ("pi5,pi5:divider=h12+vents", "vents are for a full-height divider"),
    ],
)
def test_the_cli_refuses_a_bad_divider(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str, message: str
) -> None:
    exit_code, _, err = run(capsys, tmp_path, bays)

    assert exit_code == 1
    assert message in err
