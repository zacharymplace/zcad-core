"""Half-grid Gridfinity bins: Gridfinity Rebuilt's bases on a 21 mm pitch, checked on the solids.

The figures are Rebuilt's (``REBUILT_HALF_GRID``); the unofficial specification has no half
grid. A half base is the full profile on a 20.5 mm top, so half-grid bins fit an ordinary
baseplate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from zcad_core.cli import main
from zcad_core.features.gridfinity import BinSpec, build_bin, hole_points
from zcad_core.features.gridfinity_baseplate import BaseplateSpec, build_baseplate
from zcad_core.features.gridfinity_shapes import GridfinityPart, held, section
from zcad_core.features.gridfinity_standard import (
    BASE_PROFILE_HEIGHT_MM,
    REBUILT_HALF_GRID,
)
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def half(x: int, y: int, **options: object) -> BinSpec:
    return BinSpec(x, y, height_units=3, half_grid=True, **options)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def quarter() -> GridfinityPart:
    """Four half units: a full 1 x 1's outside on four bases."""

    return build_bin(half(2, 2), PROFILE)


@pytest.fixture(scope="module")
def lone() -> GridfinityPart:
    return build_bin(half(1, 1), PROFILE)


def test_four_half_units_have_a_full_units_outside_on_four_bases(
    quarter: GridfinityPart,
) -> None:
    full = build_bin(BinSpec(1, 1, height_units=3), PROFILE)

    assert quarter.size_mm == pytest.approx(full.size_mm, abs=1e-3)
    assert quarter.passed
    assert quarter.checks["takes_a_full_base"]
    assert quarter.warnings == ()
    assert quarter.settings["pitch_mm"] == 21.0
    # Four bases: under the bridge, two 20.5 mm tops with the 0.5 mm gap between.
    assert section(quarter.body, 0.0) == pytest.approx((35.6, 35.6), abs=0.05)


def test_a_half_base_is_the_full_profile_on_a_20_5_mm_top(
    lone: GridfinityPart,
) -> None:
    assert section(lone.body, BASE_PROFILE_HEIGHT_MM - 0.01) == pytest.approx(
        (20.5, 20.5), abs=0.05
    )
    # The bottom is the top less the profile's 2.95 mm each side, as on the full grid.
    assert section(lone.body, 0.0) == pytest.approx((14.6, 14.6), abs=0.05)


def test_a_bin_one_half_unit_across_is_warned_of_and_still_seats(
    lone: GridfinityPart,
) -> None:
    assert lone.passed
    assert "can slide half a cell" in lone.warnings[0]


def test_a_bin_covering_one_and_a_half_cells_rests_on_the_ridge() -> None:
    spec = half(3, 2)
    part = build_bin(spec, PROFILE)

    assert spec.cells == (2, 1)
    assert part.passed
    assert part.warnings == ()
    assert part.settings["seat_height_mm"] == pytest.approx(0.25)


def test_the_seat_check_tells_resting_on_the_slopes_from_the_ridges(
    quarter: GridfinityPart,
) -> None:
    plate = build_baseplate(BaseplateSpec(1, 1), {}, check=False).body

    assert held(quarter.body, plate, 0.0)
    assert not held(quarter.body, plate, 0.25)


def test_magnets_go_in_the_outer_corners_only() -> None:
    # Rebuilt's corners: 4.8 mm in from the bases' 35.6 mm bottom, as on a full 1 x 1.
    assert sorted(hole_points(half(2, 2, magnets=True))) == pytest.approx(
        [(-13.0, -13.0), (-13.0, 13.0), (13.0, -13.0), (13.0, 13.0)]
    )
    assert len(hole_points(half(4, 2, magnets=True))) == 4


@pytest.mark.parametrize("options", [{"magnets": True}, {"screws": True}])
def test_no_holes_on_a_bin_one_half_unit_across(options: dict[str, bool]) -> None:
    with pytest.raises(ValueError, match="holes would overlap"):
        build_bin(half(1, 3, **options), PROFILE)


def test_the_half_grid_counts_up_to_twice_the_full_grids_units() -> None:
    with pytest.raises(ValueError, match="1 to 16 units"):
        build_bin(half(17, 1), PROFILE)


def test_the_command_names_the_half_grid_and_cites_rebuilt(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = tmp_path / "bin"
    command = ["gridfinity", "bin", "--half-grid", "--units", "1x1", "--height", "2"]

    assert main([*command, "--output-directory", str(output)]) == 0
    built = json.loads(capsys.readouterr().out)
    record = json.loads((output / "gridfinity.json").read_text())

    assert built["design_name"] == "gridfinity-bin-half-1x1x2"
    assert built["warnings"]
    assert record["settings"]["half_grid"] is True
    assert REBUILT_HALF_GRID in record["standard"]["sources"]
