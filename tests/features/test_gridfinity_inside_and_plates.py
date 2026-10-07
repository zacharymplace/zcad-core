"""Gridfinity phase 2: dividers, label tabs and screw holes in bins; magnets, screws and pieces in
baseplates."""

from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.gridfinity import BinSpec, build_bin
from zcad_core.features.gridfinity_baseplate import (
    BaseplateSpec,
    build_baseplate,
    pieces_across,
)
from zcad_core.features.gridfinity_inside import LABEL_TAB_DEPTH_MM, plan_inside
from zcad_core.features.gridfinity_shapes import (
    GridfinityPart,
    require_fits_bed,
    size_of,
)
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def inside(part: GridfinityPart, x: float, y: float, z: float) -> bool:
    shape = part.body.val()
    assert isinstance(shape, cq.Shape)

    return any(solid.isInside(cq.Vector(x, y, z), 1e-4) for solid in shape.Solids())


@pytest.fixture(scope="module")
def divided() -> GridfinityPart:
    return build_bin(
        BinSpec(2, 1, 4, divisions=(3, 1), label_tabs=True, screws=True, magnets=True),
        PROFILE,
    )


def test_dividers_split_the_bin_and_it_still_stacks(divided: GridfinityPart) -> None:
    assert divided.passed, divided.checks
    assert divided.checks["compartments_open"]
    assert divided.checks["stacks"]
    plan = plan_inside(83.5 - 2.4, 41.5 - 2.4, (3, 1), 28.0 - 0.35 - 0.5, 1.2)
    (_, x1, _, _), (x2, _, _, _), _ = plan.compartments

    # Three equal compartments with 1.2 mm between them.
    assert x2 - x1 == pytest.approx(1.2)
    # A divider stands between them, up to half a millimetre under a stacked base.
    assert inside(divided, x1 + 0.6, -10.0, 20.0)
    assert not inside(divided, x1 + 0.6, -10.0, 28.0 - 0.35 - 0.3)


def test_a_label_tab_is_a_shelf_on_the_back_wall(divided: GridfinityPart) -> None:
    back = (41.5 - 2.4) / 2
    top = 28.0 - 0.35 - 0.5

    # On the shelf, just under its top, near its front edge; empty in front of it.
    assert inside(divided, -30.0, back - LABEL_TAB_DEPTH_MM + 0.5, top - 0.5)
    assert not inside(divided, -30.0, back - LABEL_TAB_DEPTH_MM - 0.5, top - 0.5)
    # The 45-degree underside: solid near the wall, empty under the shelf's front.
    assert inside(divided, -30.0, back - 1.0, top - 1.2 - 0.5)
    assert not inside(divided, -30.0, back - LABEL_TAB_DEPTH_MM + 1.0, top - 3.0)


def test_screw_holes_rise_through_the_base_but_not_into_the_cavity(
    divided: GridfinityPart,
) -> None:
    x, y = -21.0 - 13.0, -13.0

    assert not inside(divided, x, y, 4.0)
    # A floor's 1.2 mm is left under the cavity.
    assert inside(divided, x, y, 7.0 - 0.6)


@pytest.mark.parametrize(
    ("divisions", "message"),
    [((5, 1), "under the 10 mm least"), ((0, 1), "at least 1 compartment")],
)
def test_compartments_too_small_are_refused(
    divisions: tuple[int, int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_bin(BinSpec(1, 1, 3, divisions=divisions), PROFILE)


def test_a_label_tab_needs_a_deep_enough_compartment() -> None:
    with pytest.raises(ValueError, match="need twice that"):
        build_bin(BinSpec(1, 1, 3, divisions=(1, 2), label_tabs=True), PROFILE)


def test_a_magnet_and_screw_baseplate_stands_on_a_floor() -> None:
    plate = build_baseplate(BaseplateSpec(1, 1, magnets=True, screws=True), PROFILE)

    assert plate.passed, plate.checks
    # 1 mm, the magnet's 2.4 mm and the countersink's 2.5 mm, under the 5 mm plate.
    assert plate.settings["floor_mm"] == pytest.approx(5.9)
    assert plate.size_mm == pytest.approx((42.0, 42.0, 10.9), abs=0.01)
    # The magnet pocket opens on the floor's top; the screw goes through below it.
    assert not inside(plate, 13.0, 13.0, 5.9 - 1.0)
    assert not inside(plate, 13.0, 13.0, 0.5)
    # Beside the screw, under the pocket, the floor is solid.
    assert inside(plate, 13.0 + 2.6, 13.0, 0.5)


def test_a_screw_only_baseplate_has_its_countersink_at_the_floor_top() -> None:
    plate = build_baseplate(BaseplateSpec(1, 1, screws=True), PROFILE)

    assert plate.passed, plate.checks
    assert plate.settings["floor_mm"] == pytest.approx(3.5)
    # The countersink is 8 mm across at the floor's top.
    assert not inside(plate, 13.0 + 3.9, 13.0, 3.5 - 0.05)


def test_pieces_are_as_few_and_even_as_the_bed_allows() -> None:
    # Four 42 mm cells fit the A1 mini's 180 mm bed.
    assert pieces_across(4, 180) == [4]
    assert pieces_across(5, 180) == [3, 2]
    assert pieces_across(8, 180) == [4, 4]
    assert pieces_across(9, 180) == [3, 3, 3]


def test_a_baseplate_larger_than_the_bed_is_built_in_pieces() -> None:
    plate = build_baseplate(BaseplateSpec(5, 1), PROFILE)

    assert plate.passed, plate.checks
    assert plate.checks["pieces_are_the_plate"]
    assert [size_of(piece)[0] for piece in plate.pieces] == pytest.approx(
        [3 * 42.0, 2 * 42.0], abs=0.01
    )
    assert list(plate.printed) == ["baseplate-1", "baseplate-2"]
    require_fits_bed(plate, PROFILE)


def test_the_commands_build_a_divided_bin_and_a_magnet_baseplate(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        [
            "gridfinity",
            "bin",
            "--units",
            "1x1",
            "--height",
            "3",
            "--divisions",
            "2x1",
            "--screws",
            "--output-directory",
            str(tmp_path / "bin"),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["validation_status"] == "PASS"
    assert report["settings"]["divisions"] == [2, 1]

    code = main(
        [
            "gridfinity",
            "baseplate",
            "--units",
            "5x1",
            "--magnets",
            "--output-directory",
            str(tmp_path / "plate"),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert sorted(report["parts"]) == ["baseplate-1", "baseplate-2"]
    assert report["settings"]["pieces"] == [[126.0, 42.0], [84.0, 42.0]]
