"""Units that join: the standard joint face, the pass-through, and the join check."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.enclosure_group import Bay, GroupDesign, build_group_enclosure
from zcad_core.features.enclosure_group_join import check_join
from zcad_core.hardware import board_template, load_board
from zcad_core.hardware.electronics.board_file import BoardFileSpec

STANDARD = {"joint_face": "standard"}


def write_board(directory: Path, **changes: Any) -> Path:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data.pop("test_points", None)
    data["components"] = []

    for key, value in changes.items():
        data[key] = value

    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


@pytest.fixture(scope="module")
def board(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(write_board(tmp_path_factory.mktemp("board")))


def unit(bays: Any, **design: Any) -> Any:
    return build_group_enclosure(bays, design=GroupDesign(**design))


def small_unit(board: BoardFileSpec, **design: Any) -> Any:
    return unit((Bay("board", board=board, align="front"),), **design)


def empty(unit_: Any, x: float, y: float, z: float) -> bool:
    return not any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, unit_.base.val()).Solids()
    )


# --- where the bolts go -----------------------------------------------------------------------


def test_the_original_face_is_the_default_and_is_unchanged() -> None:
    group = unit(("pi5", "pi5"))
    inner_depth = group.inner_size_mm[1]

    assert group.design.joint_face == "fractions"
    assert group.join_positions == (
        (group.design.wall_mm + inner_depth * 0.65, group.design.floor_mm + 8.0),
        (group.design.wall_mm + inner_depth * 0.83, group.design.floor_mm + 8.0),
    )


def test_the_standard_face_puts_the_bolts_in_the_same_place_in_any_unit(
    board: BoardFileSpec,
) -> None:
    deep = unit(("pi5",), **STANDARD)
    shallow = small_unit(board, **STANDARD)

    assert deep.outer_size_mm[1] != shallow.outer_size_mm[1]
    assert deep.join_positions == shallow.join_positions == ((20.0, 10.0), (38.0, 10.0))


def test_a_unit_too_shallow_for_the_standard_face_is_refused(tmp_path: Path) -> None:
    tiny = load_board(
        write_board(
            tmp_path,
            board={"width_mm": 20.0, "length_mm": 25.0, "thickness_mm": 1.6},
            mounting_holes={
                "diameter_mm": 2.7,
                "positions_mm": [[-7.0, -9.0], [7.0, -9.0], [-7.0, 9.0], [7.0, 9.0]],
            },
        )
    )

    with pytest.raises(ValueError, match="the standard joint face needs"):
        small_unit(tiny, **STANDARD)

    # The original face fits it.
    assert small_unit(tiny).passed


def test_the_standard_bolts_keep_clear_of_the_lids_corner_bosses(
    tmp_path: Path,
) -> None:
    shallow = load_board(
        write_board(
            tmp_path,
            board={"width_mm": 30.0, "length_mm": 36.0, "thickness_mm": 1.6},
            mounting_holes={
                "diameter_mm": 2.7,
                "positions_mm": [[-12.0, -14.0], [12.0, -14.0], [-12.0, 14.0]],
            },
        )
    )

    with pytest.raises(ValueError, match="meet the lid's corner bosses"):
        small_unit(shallow, **STANDARD)


def test_a_pass_through_needs_the_standard_face_and_sensible_sides() -> None:
    with pytest.raises(ValueError, match="part of the standard joint face"):
        GroupDesign(pass_through_mm=(16.0, 6.0)).validate()

    with pytest.raises(ValueError, match="joint_face must be one of"):
        GroupDesign(joint_face="glue").validate()

    with pytest.raises(ValueError, match="pass_through_sides must be one of"):
        GroupDesign(joint_face="standard", pass_through_sides="top").validate()

    with pytest.raises(ValueError, match="above zero"):
        GroupDesign(joint_face="standard", pass_through_mm=(0.0, 6.0)).validate()


# --- the pass-through -------------------------------------------------------------------------


def test_a_pass_through_is_cut_in_both_join_walls(board: BoardFileSpec) -> None:
    group = small_unit(board, pass_through_mm=(16.0, 6.0), **STANDARD)
    wall = group.design.wall_mm
    right = group.outer_size_mm[0] - wall / 2

    assert empty(group, wall / 2, 29.0, 18.0)
    assert empty(group, right, 29.0, 18.0)
    # Wall stands above, below and beside it.
    assert not empty(group, wall / 2, 29.0, 23.5)
    assert not empty(group, wall / 2, 29.0, 15.0)
    assert not empty(group, wall / 2, 40.0, 18.0)


def test_a_pass_through_can_be_on_one_wall_only(board: BoardFileSpec) -> None:
    group = small_unit(
        board, pass_through_mm=(16.0, 6.0), pass_through_sides="left", **STANDARD
    )

    assert empty(group, group.design.wall_mm / 2, 29.0, 18.0)
    assert not empty(group, group.outer_size_mm[0] - 1.0, 29.0, 18.0)


def test_a_pass_through_that_would_reach_the_lids_seat_is_refused(
    board: BoardFileSpec,
) -> None:
    with pytest.raises(ValueError, match="make it shorter or raise headroom_mm"):
        small_unit(board, pass_through_mm=(16.0, 9.0), **STANDARD)

    assert small_unit(board, pass_through_mm=(16.0, 9.0), headroom_mm=24.0, **STANDARD)


def test_a_pass_through_too_wide_for_the_lids_corner_bosses_is_refused(
    board: BoardFileSpec,
) -> None:
    with pytest.raises(ValueError, match="would meet the lid's corner bosses"):
        small_unit(board, pass_through_mm=(40.0, 6.0), **STANDARD)


# --- joining ----------------------------------------------------------------------------------


def test_units_of_different_depth_on_the_standard_face_bolt_together(
    board: BoardFileSpec,
) -> None:
    deep = unit(("pi5",), **STANDARD)
    shallow = small_unit(board, **STANDARD)

    for left, right in ((deep, shallow), (shallow, deep), (deep, deep)):
        report = check_join(left, right)

        assert report.passed, report.checks
        assert report.details["gap_mm"] == 0.0 and report.details["overlap_mm3"] == 0.0
        assert report.notes == ()

    assert check_join(deep, shallow).details["shared_depth_mm"] == pytest.approx(
        shallow.outer_size_mm[1], abs=0.1
    )


def test_units_of_the_original_face_mate_only_at_the_same_depth(
    board: BoardFileSpec,
) -> None:
    deep, shallow = unit(("pi5",)), small_unit(board)
    same = check_join(deep, deep)

    assert same.passed
    assert any("not on the standard joint face" in note for note in same.notes)

    mixed = check_join(deep, shallow)

    assert not mixed.passed
    assert mixed.checks["bolts_pass_through_the_holes"] is False
    assert mixed.checks["bolts_reach_the_bosses"] is False
    # The walls themselves still meet.
    assert mixed.checks["walls_meet"] is True


def test_a_standard_unit_and_an_original_one_of_another_depth_do_not_mate(
    board: BoardFileSpec,
) -> None:
    assert not check_join(unit(("pi5",)), small_unit(board, **STANDARD)).passed


def test_a_pass_through_on_both_sides_of_a_joint_lines_up(
    board: BoardFileSpec,
) -> None:
    left = unit(("pi5",), pass_through_mm=(16.0, 6.0), **STANDARD)
    right = small_unit(board, pass_through_mm=(16.0, 6.0), **STANDARD)

    report = check_join(left, right)

    assert report.passed and report.checks["pass_through_lines_up"] is True

    odd = small_unit(board, pass_through_mm=(14.0, 6.0), **STANDARD)

    assert check_join(left, odd).checks["pass_through_lines_up"] is False


def test_a_pass_through_on_one_side_only_is_noted(board: BoardFileSpec) -> None:
    left = unit(("pi5",), pass_through_mm=(16.0, 6.0), **STANDARD)
    report = check_join(left, small_unit(board, **STANDARD))

    assert report.passed
    assert any("Only one unit has a pass-through" in n for n in report.notes)


def test_units_with_different_screws_do_not_join(board: BoardFileSpec) -> None:
    m3 = unit(("pi5",), **STANDARD)
    m4 = unit(("pi5",), fastener="M4", **STANDARD)

    assert check_join(m3, m4).checks["same_screw"] is False


def test_a_unit_with_no_join_bolts_does_not_join(board: BoardFileSpec) -> None:
    bare = unit(("pi5",), join_bolts=False, **STANDARD)
    report = check_join(unit(("pi5",), **STANDARD), bare)

    assert not report.passed


# --- the command line ---------------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["enclosure-group", *args])

    return code, cast(dict[str, Any], json.loads(capsys.readouterr().out))


def test_the_check_command_says_whether_two_units_bolt(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = write_board(tmp_path)
    right = f"board:file={path}:align=front"
    code, report = run(
        capsys, "check-join", "--left-bays", "pi5", "--right-bays", right
    )

    assert code == 0 and report["passed"] is True
    assert report["details"]["depths_mm"][0] > report["details"]["depths_mm"][1]

    code, report = run(
        capsys,
        "check-join",
        "--left-bays",
        "pi5",
        "--right-bays",
        right,
        "--left-joint",
        "fractions",
    )

    assert code == 1 and report["passed"] is False
    assert any("not on the standard joint face" in n for n in report["notes"])


def test_the_build_reports_its_joint_and_takes_a_pass_through(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, output = run(
        capsys,
        "build",
        "--bays",
        "pi5",
        "--joint",
        "standard",
        "--pass-through",
        "16x6",
        "--output-directory",
        str(tmp_path / "out"),
        "--printer-profile",
        str(
            Path(__file__).resolve().parents[2]
            / "profiles/printers/bambu-lab-a1-mini.json"
        ),
    )

    assert code == 0
    assert output["joint"] == {
        "face": "standard",
        "bolts_y_z_mm": [[20.0, 10.0], [38.0, 10.0]],
        "pass_through_mm": [16.0, 6.0],
    }
