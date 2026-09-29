from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import (
    Bay,
    BayOpening,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.geometry.intersection import intersection_volume

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def shelf(*openings: BayOpening, headroom_mm: float | None = None) -> GroupEnclosure:
    return build_group_enclosure(
        ("pi5", Bay("open", headroom_mm=headroom_mm, openings=openings))
    )


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    probe = cq.Solid.makeBox(0.4, 0.4, 0.4, pnt=cq.Vector(x - 0.2, y - 0.2, z - 0.2))
    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Shape)

    return intersection_volume(solid, probe) > 0.01


def wall_point(
    group: GroupEnclosure, wall: str, x_offset: float
) -> tuple[float, float]:
    """A point in the middle of the front or back wall, over the open bay."""

    thickness = group.design.wall_mm
    bay = group.bays[1]
    y = thickness / 2 if wall == "front" else group.outer_size_mm[1] - thickness / 2

    return thickness + bay.center_x_mm + x_offset, y


def test_an_open_bay_with_no_openings_has_solid_walls() -> None:
    plain = shelf()
    x, y = wall_point(plain, "back", 0.0)

    assert plain.passed
    assert has_material(plain.base, x, y, plain.design.floor_mm + 5.0)


def test_a_back_wall_opening_is_cut_where_asked() -> None:
    group = shelf(BayOpening("back", 20.0, 10.0, offset_mm=-5.0, bottom_mm=3.0))
    floor = group.design.floor_mm
    x, y = wall_point(group, "back", -5.0)

    assert group.passed, group.checks
    assert not has_material(group.base, x, y, floor + 3.0 + 5.0)
    # Solid below it, above it, and past its edge.
    assert has_material(group.base, x, y, floor + 1.5)
    assert has_material(group.base, x, y, floor + 3.0 + 10.0 + 2.0)
    assert has_material(group.base, x + 10.0 + 1.5, y, floor + 8.0)
    # The front wall is untouched.
    fx, fy = wall_point(group, "front", -5.0)
    assert has_material(group.base, fx, fy, floor + 8.0)


def test_a_front_wall_opening_is_cut_in_the_front_wall() -> None:
    group = shelf(BayOpening("front", 12.0, 8.0))
    x, y = wall_point(group, "front", 0.0)

    assert not has_material(group.base, x, y, group.design.floor_mm + 4.0)
    bx, by = wall_point(group, "back", 0.0)
    assert has_material(group.base, bx, by, group.design.floor_mm + 4.0)


def test_an_opening_leaves_the_base_one_solid_and_clear_of_the_lid() -> None:
    group = shelf(
        BayOpening("back", 10.0, 6.0, offset_mm=-12.0),
        BayOpening("back", 10.0, 6.0, offset_mm=12.0),
        BayOpening("front", 30.0, 12.0),
    )

    assert group.passed, group.checks
    assert len(group.base.solids().vals()) == 1


def test_the_pi_bays_openings_are_untouched() -> None:
    with_shelf = shelf(BayOpening("back", 20.0, 10.0))
    without = shelf()
    pi = with_shelf.bays[0]
    x = with_shelf.design.wall_mm + pi.center_x_mm
    y = with_shelf.outer_size_mm[1] - with_shelf.design.wall_mm / 2
    z = pi.board_top_z_mm + 6.0

    assert has_material(with_shelf.base, x - 8.0, y, z) == has_material(
        without.base, x - 8.0, y, z
    )


@pytest.mark.parametrize("kind", ["pi5", "reserved"])
def test_a_pi_bay_takes_no_openings(kind: str) -> None:
    with pytest.raises(ValueError, match="only an open bay takes openings"):
        build_group_enclosure(
            (Bay(kind, openings=(BayOpening("back", 10.0, 5.0),)),)  # type: ignore[arg-type]
        )


def test_an_opening_outside_the_shelf_is_refused() -> None:
    # The shelf is 40 mm wide: 20 mm each way, less 1 mm of wall.
    with pytest.raises(ValueError, match="does not fit the 40 mm shelf"):
        shelf(BayOpening("back", 20.0, 5.0, offset_mm=10.0))

    assert shelf(BayOpening("back", 20.0, 5.0, offset_mm=9.0)).passed


@pytest.mark.parametrize(
    "opening",
    [
        BayOpening("back", 0.0, 5.0),
        BayOpening("back", 5.0, -1.0),
        BayOpening("back", 5.0, 5.0, bottom_mm=-1.0),
        BayOpening("left", 5.0, 5.0),  # type: ignore[arg-type]
    ],
)
def test_a_malformed_opening_is_refused(opening: BayOpening) -> None:
    with pytest.raises(ValueError, match="opening"):
        shelf(opening)


def test_two_overlapping_openings_in_one_wall_are_refused() -> None:
    with pytest.raises(ValueError, match="overlap"):
        shelf(
            BayOpening("back", 10.0, 6.0, offset_mm=0.0),
            BayOpening("back", 10.0, 6.0, offset_mm=5.0),
        )


def test_the_same_span_in_different_walls_or_heights_is_fine() -> None:
    assert shelf(
        BayOpening("back", 10.0, 6.0),
        BayOpening("front", 10.0, 6.0),
        BayOpening("back", 10.0, 6.0, bottom_mm=8.0),
    ).passed


def test_an_opening_that_reaches_the_lid_is_refused_and_headroom_fixes_it() -> None:
    # The Pi bay sets the box: 23.4 mm inside, so an opening may reach 22.4.
    with pytest.raises(ValueError, match="raise headroom_mm on a bay"):
        shelf(BayOpening("back", 10.0, 23.0))

    assert shelf(BayOpening("back", 10.0, 22.0)).passed
    assert shelf(BayOpening("back", 10.0, 30.0), headroom_mm=40.0).passed


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


def test_the_cli_takes_openings_and_reports_them(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, out, _ = run(capsys, tmp_path, "pi5,open:back=20x10@-5/3:front=12x8")
    output = json.loads(out)

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    assert output["bay_heights"][0]["openings"] == []
    assert output["bay_heights"][1]["openings"] == [
        {
            "wall": "back",
            "width_mm": 20.0,
            "height_mm": 10.0,
            "offset_mm": -5.0,
            "bottom_mm": 3.0,
        },
        {
            "wall": "front",
            "width_mm": 12.0,
            "height_mm": 8.0,
            "offset_mm": 0.0,
            "bottom_mm": 0.0,
        },
    ]


@pytest.mark.parametrize(
    ("bays", "message"),
    [
        ("pi5,open:back=20", "an opening must be back=<width>x<height>"),
        ("pi5,open:back=20x", "an opening must be back=<width>x<height>"),
        ("pi5,open:front=widexhigh", "an opening must be front=<width>x<height>"),
        ("pi5,open:back=20x10@left", "an opening must be back=<width>x<height>"),
        ("pi5,open:back", "bay option must be standoff=<mm>"),
        ("pi5,open:side=20x10", "bay option must be standoff=<mm>"),
        ("pi5:back=20x10,open", "only an open bay takes openings"),
        ("pi5,open:back=60x10", "does not fit the 40 mm shelf"),
    ],
)
def test_the_cli_refuses_a_bad_opening(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str, message: str
) -> None:
    exit_code, _, err = run(capsys, tmp_path, bays)

    assert exit_code == 1
    assert message in err
