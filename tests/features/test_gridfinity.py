"""Gridfinity bins and baseplates, checked against the figures they are built to.

The figures are the unofficial specification's and Gridfinity Rebuilt's (see
``features/gridfinity_standard.py``). The tests check the built solids, so a change that drifts
from the standard fails here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.gridfinity import (
    BinSpec,
    GridfinityPart,
    build_baseplate,
    build_bin,
    require_fits_bed,
    seat_height_mm,
    stack_seat_mm,
)
from zcad_core.features.gridfinity_standard import (
    BASE_PROFILE_HEIGHT_MM,
    BASE_PROFILE_STEPS_MM,
    BASEPLATE_CLEARANCE_MM,
    BASEPLATE_PROFILE_HEIGHT_MM,
    LIP_DEPTH_MM,
    LIP_HEIGHT_MM,
    REBUILT,
    SPECIFICATION,
    profile_insets,
)
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


@pytest.fixture(scope="module")
def small_bin() -> GridfinityPart:
    return build_bin(BinSpec(1, 1, 3, magnets=True), PROFILE)


@pytest.fixture(scope="module")
def plate() -> GridfinityPart:
    return build_baseplate(2, 2, PROFILE)


def inside(part: GridfinityPart, x: float, y: float, z: float) -> bool:
    shape = part.body.val()
    assert isinstance(shape, cq.Shape)

    return any(solid.isInside(cq.Vector(x, y, z), 1e-4) for solid in shape.Solids())


def test_the_figures_add_up_to_the_drawings() -> None:
    # The base profile's steps make the drawing's 4.75 mm, 2.95 mm in from the 41.5 mm top.
    assert profile_insets(BASE_PROFILE_STEPS_MM) == [
        (0.0, 2.95),
        (0.8, 2.15),
        (2.6, 2.15),
        (4.75, 0.0),
    ]
    assert BASE_PROFILE_HEIGHT_MM == pytest.approx(4.75)
    # The baseplate's profile and its clearance make the drawing's 5 mm.
    assert BASEPLATE_PROFILE_HEIGHT_MM + BASEPLATE_CLEARANCE_MM == pytest.approx(5.0)
    assert BASEPLATE_CLEARANCE_MM == pytest.approx(0.35)
    assert (LIP_HEIGHT_MM, LIP_DEPTH_MM) == pytest.approx((4.4, 2.6))
    assert "910e22d" in REBUILT and "gridfinity-unofficial" in SPECIFICATION


def test_a_one_unit_bin_keeps_to_the_standard(small_bin: GridfinityPart) -> None:
    assert small_bin.passed, small_bin.checks
    assert small_bin.checks == {
        "one_solid": True,
        "base_to_standard": True,
        "seats_in_baseplate": True,
        "stacks": True,
    }
    # 41.5 mm square; three 7 mm units to the top of its wall, with the 4.4 mm lip above.
    assert small_bin.size_mm == pytest.approx((41.5, 41.5, 21.0 + 4.4), abs=0.01)


def test_magnet_holes_open_on_the_underside_in_every_corner(
    small_bin: GridfinityPart,
) -> None:
    # 8 mm in from each side of the 42 mm unit: 13 mm from its centre.
    for x, y in ((13, 13), (-13, 13), (13, -13), (-13, -13)):
        assert not inside(small_bin, x, y, 1.0)
        assert inside(small_bin, x, y, 3.0)


def test_the_lip_overhangs_nothing_past_45_degrees(small_bin: GridfinityPart) -> None:
    # Under the lip's inner tip, 2.6 mm in from the outside, the shoulder is solid; at the
    # wall's 1.2 mm it is the cavity just under the shoulder's start.
    top = 21.0
    assert inside(small_bin, 41.5 / 2 - 2.0, 0.0, top - 0.2)
    assert not inside(small_bin, 41.5 / 2 - 2.0, 0.0, top - 1.6)


def test_a_bin_of_several_units_rests_on_the_ridges() -> None:
    assert seat_height_mm(1, 1) == 0.0
    assert seat_height_mm(2, 1) == pytest.approx(0.25)
    assert stack_seat_mm(BinSpec(1, 1, 3)) == pytest.approx(21.0 - 0.35)

    wide = build_bin(BinSpec(2, 1, 2, lip=False), PROFILE)

    assert wide.passed, wide.checks
    assert wide.settings["seat_height_mm"] == pytest.approx(0.25)
    assert "stacks" not in wide.checks
    assert wide.size_mm == pytest.approx((83.5, 41.5, 14.0), abs=0.01)


def test_a_baseplate_is_cells_of_the_standard(plate: GridfinityPart) -> None:
    assert plate.passed, plate.checks
    assert plate.size_mm == pytest.approx((84.0, 84.0, 5.0), abs=0.01)
    # A cell's bottom opening: 42 mm less the baseplate profile's 2.85 mm each side.
    assert not inside(plate, -21.0 + 36.3 / 2 - 0.05, -21.0, 0.1)
    assert inside(plate, -21.0 + 36.3 / 2 + 0.05, -21.0, 0.1)


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (BinSpec(1, 1, 1), "at least 2 units tall"),
        (BinSpec(0, 1, 3), "1 to 8 units along x"),
        (BinSpec(1, 9, 3), "1 to 8 units along y"),
        (BinSpec(1, 1, 3, wall_mm=0.8), "under the printer's 1.2 mm minimum"),
    ],
)
def test_a_bin_that_cannot_be_built_is_refused(spec: BinSpec, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        build_bin(spec, PROFILE)


def test_a_part_larger_than_the_bed_is_refused() -> None:
    part = build_baseplate(5, 1, PROFILE, check=False)

    with pytest.raises(ValueError, match="larger than the printer's"):
        require_fits_bed(part, PROFILE)


def test_a_printer_that_closes_the_gap_is_warned_and_the_bin_unchanged() -> None:
    spec = BinSpec(1, 1, 2, lip=False)
    tight = build_bin(spec, PROFILE, side_shortfall_mm=0.3)
    fine = build_bin(spec, PROFILE, side_shortfall_mm=0.1)

    assert "may bind" in tight.warnings[0]
    assert fine.warnings == ()
    assert tight.size_mm == pytest.approx(fine.size_mm)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any]:
    code = main(list(args))
    out = capsys.readouterr().out

    return code, json.loads(out) if out else None


def test_the_commands_build_a_bin_and_a_baseplate(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, report = run(
        capsys,
        "gridfinity",
        "bin",
        "--units",
        "1x1",
        "--height",
        "2",
        "--no-lip",
        "--output-directory",
        str(tmp_path / "bin"),
    )

    assert code == 0
    assert report["validation_status"] == "PASS"
    record = json.loads((tmp_path / "bin" / "gridfinity.json").read_text())
    assert record["verified"] is False
    assert record["standard"]["sources"] == [SPECIFICATION, REBUILT]
    assert record["settings"]["units"] == [1, 1]

    code, report = run(
        capsys,
        "gridfinity",
        "baseplate",
        "--units",
        "1x1",
        "--output-directory",
        str(tmp_path / "plate"),
    )

    assert code == 0
    assert report["checks"]["holds_a_bin"]


def test_units_must_be_written_x_by_y(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(
            [
                "gridfinity",
                "baseplate",
                "--units",
                "2by3",
                "--output-directory",
                "out",
            ]
        )

    capsys.readouterr()
