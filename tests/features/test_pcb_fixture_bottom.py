"""A fixture that probes the board's bottom side, with the board turned over."""

from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.pcb_fixture import PcbFixture, build_fixture, fixture_record
from zcad_core.features.pcb_fixture_file import (
    check_fixture_data,
    check_fixture_file,
    fixture_template,
    load_fixture,
    load_fixture_board,
    probed_points,
)
from zcad_core.features.pcb_fixture_turn import turn_over
from zcad_core.hardware import board_template, load_board
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PROFILE = load_printer_profile(PRINTER_PATH)


def component(
    name: str,
    x: float,
    y: float,
    w: float,
    d: float,
    h: float,
    z: float = 0.0,
    **more: Any,
) -> dict[str, Any]:
    return {
        "identifier": name,
        "center_x_mm": x,
        "center_y_mm": y,
        "width_mm": w,
        "depth_mm": d,
        "height_mm": h,
        "bottom_offset_from_board_top_mm": z,
        **more,
    }


def point(name: str, x: float, y: float, side: str = "bottom") -> dict[str, Any]:
    return {
        "identifier": name,
        "x_mm": x,
        "y_mm": y,
        "pad_diameter_mm": 3.0,
        "side": side,
    }


def write_board(directory: Path, points: list[dict[str, Any]] | None = None) -> Path:
    """A 30 x 45 board with a tall header and a connector on top, a chip and a battery
    under it, and test points on its bottom side."""

    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = [
        component("HEADER", 0, -5, 20, 3, 8.5),
        component("USB", 15, -12, 6, 8, 3.0, access_edge="positive_x"),
        component("CHIP", 8, 0, 6, 6, 1.0, z=-2.6),
        component("BATTERY", 0, 10, 10, 8, 2.0, z=-3.6),
    ]
    data["test_points"] = points or [
        point("BP1", -8.0, 14.0),
        point("BP2", 8.0, 14.0),
        point("BP3", -8.0, 5.0),
        point("TOP1", 0.0, -14.0, side="top"),
    ]
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def make_fixture(directory: Path, **changes: Any) -> PcbFixture:
    board = write_board(directory)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["side"] = "bottom"
    data.update(changes)
    path = directory / "fixture.json"
    path.write_text(json.dumps(data))
    spec = load_fixture(path)
    loaded = load_fixture_board(spec)

    return build_fixture(spec, loaded, probed_points(spec, loaded), PROFILE)


@pytest.fixture(scope="module")
def bottom(tmp_path_factory: pytest.TempPathFactory) -> PcbFixture:
    return make_fixture(tmp_path_factory.mktemp("bottom"))


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, model.val()).isInside(cq.Vector(x, y, z)))


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


# --- the board turned over ----------------------------------------------------------


def test_turning_a_board_over_mirrors_left_to_right_and_swaps_top_and_bottom(
    tmp_path: Path,
) -> None:
    board = load_board(write_board(tmp_path))
    turned = turn_over(board)
    thickness = board.board_thickness_mm
    by_name = {p.identifier: p for p in turned.components}

    # Points: x mirrored, and the bottom side is now the top.
    sides = {p.identifier: (p.x_mm, p.y_mm, p.side) for p in turned.test_points}
    assert sides["BP1"] == (8.0, 14.0, "top")
    assert sides["TOP1"] == (0.0, -14.0, "bottom")
    # A part that stood on the top face hangs under it, by its own height and the board.
    assert by_name["HEADER"].bottom_offset_from_board_top_mm == pytest.approx(
        -thickness - 8.5
    )
    # A part under the board, 1 mm tall with its underside 2.6 mm below the face, stands on
    # the new top face; the battery, 2 mm tall and 3.6 below, stands 0 above it too.
    chip = by_name["CHIP"]
    assert chip.center_x_mm == -8.0
    assert chip.bottom_offset_from_board_top_mm == pytest.approx(0.0)
    assert by_name["BATTERY"].bottom_offset_from_board_top_mm == pytest.approx(0.0)
    # An edge on the right is on the left.
    assert by_name["USB"].access_edge == "negative_x"


def test_turning_a_board_over_twice_gives_the_board_back(tmp_path: Path) -> None:
    board = load_board(write_board(tmp_path))
    again = turn_over(turn_over(board))

    for original, back in zip(board.components, again.components, strict=True):
        assert back.center_x_mm == pytest.approx(original.center_x_mm)
        assert back.bottom_offset_from_board_top_mm == pytest.approx(
            original.bottom_offset_from_board_top_mm
        )
        assert back.access_edge == original.access_edge

    for was, now in zip(board.test_points, again.test_points, strict=True):
        assert now.x_mm == pytest.approx(was.x_mm) and now.side == was.side


# --- the fixture -----------------------------------------------------------------------


def test_a_bottom_side_fixture_passes_its_checks(bottom: PcbFixture) -> None:
    assert bottom.passed, (bottom.checks, bottom.problems)
    assert all(bottom.checks.values())


def test_it_probes_the_bottom_pads_where_they_are_in_the_turned_frame(
    bottom: PcbFixture,
) -> None:
    positions = {p.identifier: (p.x_mm, p.y_mm) for p in bottom.plan.points}

    # The top-side point is left alone, and the bottom ones are mirrored.
    assert set(positions) == {"BP1", "BP2", "BP3"}
    assert positions["BP1"] == (8.0, 14.0)
    assert positions["BP2"] == (-8.0, 14.0)
    assert positions["BP3"] == (8.0, 5.0)

    for x, y in positions.values():
        assert not inside(bottom.plate, x, y, bottom.plan.plate_underside_mm + 1.0)


def test_the_header_hangs_in_the_nests_cavity_and_the_board_rests_on_its_ledge(
    bottom: PcbFixture,
) -> None:
    # The 8.5 mm header, turned under the board, hangs where the cavity is open.
    assert not inside(bottom.nest, 0.0, -5.0, -1.6 - 6.0)
    # And the board's edge rests on the ledge ring round the cavity.
    assert inside(bottom.nest, 14.5, 10.0, -3.0)


def test_the_record_says_the_board_is_turned_over_and_where_each_pad_is_on_it(
    bottom: PcbFixture,
) -> None:
    record = fixture_record(bottom, {})
    points = {p["identifier"]: p for p in record["points"]}

    assert record["side"] == "bottom" and record["board_turned_over"] is True
    assert points["BP1"]["position_mm"] == [8.0, 14.0]
    assert points["BP1"]["position_in_board_mm"] == [-8.0, 14.0]


def test_a_pin_that_would_land_on_a_part_on_the_bottom_is_refused(
    tmp_path: Path,
) -> None:
    board = write_board(tmp_path, [point("BP1", 8.0, 3.5), point("BP2", -8.0, 14.0)])
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["side"] = "bottom"
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    spec = load_fixture(path)
    loaded = load_fixture_board(spec)

    # The chip under the board at x = 8 is a part the pins must clear once the board is
    # turned: BP1 sits 0.5 mm from it.
    with pytest.raises(ValueError, match="part"):
        build_fixture(spec, loaded, probed_points(spec, loaded), PROFILE)


def test_a_board_with_no_bottom_points_is_refused_for_the_bottom_side(
    tmp_path: Path,
) -> None:
    board = write_board(tmp_path, [point("TOP1", 0.0, 10.0, side="top")])
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["side"] = "bottom"
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    report = check_fixture_file(path, PROFILE)

    assert not report.valid
    assert any("has no test points on its bottom side" in e for e in report.errors)


def test_the_file_accepts_the_bottom_side_and_names_the_turn() -> None:
    data = fixture_template()
    data["side"] = "bottom"

    assert check_fixture_data(data).valid

    data["side"] = "left"

    assert any("side must be one of" in e for e in check_fixture_data(data).errors)


def test_the_commands_build_a_bottom_side_fixture_and_its_trial_says_which_frame(
    tmp_path: Path,
) -> None:
    board = write_board(tmp_path)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data["side"] = "bottom"
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(data))
    code, report = run("fixture", "check", str(fixture))

    assert code == 0 and report["valid"] is True, report
    assert report["fixture"]["board_turned_over"] is True
    code, built = run(
        "fixture",
        "build",
        "--fixture-file",
        str(fixture),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0 and built["validation_status"] == "PASS", built
    code, started = run(
        "fixture",
        "trial",
        "start",
        "--build-record",
        str(tmp_path / "out" / "fixture.json"),
    )
    measurements = json.loads(Path(started["measurements"]).read_text())

    assert code == 0
    assert measurements["frame"].startswith(
        "This fixture probes the board's bottom side"
    )
