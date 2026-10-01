"""A built PCB test fixture: its nest and plate, and the checks between them."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.pcb_fixture import (
    PcbFixture,
    build_fixture,
    fixture_record,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.pcb_fixture_file import (
    fixture_template,
    load_fixture,
    load_fixture_board,
    probed_points,
)
from zcad_core.hardware import board_template
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


def write_board(directory: Path) -> Path:
    """A 30 x 45 board with a tall header, a chip, a battery under it, and a
    connector overhanging its right edge, and three test points."""

    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = [
        component("HEADER", 0, -5, 20, 3, 8.5),
        component("CHIP", 8, 0, 6, 6, 1.5),
        component("BATTERY", 0, 5, 14, 10, 3.0, z=-4.8),
        component("USB", 15, -12, 6, 8, 3.0, access_edge="positive_x"),
    ]
    data["test_points"] = [
        {"identifier": "TP1", "x_mm": -8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
        {"identifier": "TP2", "x_mm": 8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
        {"identifier": "TP3", "x_mm": 0.0, "y_mm": 5.0, "pad_diameter_mm": 3.0},
    ]
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def make_fixture(directory: Path, **changes: Any) -> PcbFixture:
    board = write_board(directory)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    data.update(changes)
    path = directory / "fixture.json"
    path.write_text(json.dumps(data))
    spec = load_fixture(path)
    loaded = load_fixture_board(spec)

    return build_fixture(spec, loaded, probed_points(spec, loaded), PROFILE)


@pytest.fixture(scope="module")
def outline(tmp_path_factory: pytest.TempPathFactory) -> PcbFixture:
    return make_fixture(tmp_path_factory.mktemp("outline"))


@pytest.fixture(scope="module")
def holes(tmp_path_factory: pytest.TempPathFactory) -> PcbFixture:
    return make_fixture(tmp_path_factory.mktemp("holes"), locating="holes")


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, model.val()).isInside(cq.Vector(x, y, z)))


# --- the checks -----------------------------------------------------------------------


@pytest.mark.parametrize("which", ["outline", "holes"])
def test_the_fixture_passes_its_checks_either_way_it_is_located(
    which: str, outline: PcbFixture, holes: PcbFixture
) -> None:
    fixture = outline if which == "outline" else holes

    assert fixture.passed, (fixture.checks, fixture.problems)
    assert fixture.checks == {
        "nest_one_solid": True,
        "plate_one_solid": True,
        "board_fits_nest": True,
        "board_lifts_out": True,
        "plate_clear_of_board": True,
        "plate_clear_of_nest": True,
        "pins_clear": True,
    }


def test_an_unbuildable_plan_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pin is too short"):
        make_fixture(
            tmp_path,
            pin={**fixture_template()["pin"], "free_length_mm": 8.0, "travel_mm": 2.0},
            working_travel_mm=1.0,
        )


# --- the nest ------------------------------------------------------------------------------


def test_the_board_rests_on_a_ledge_over_a_hollow(outline: PcbFixture) -> None:
    nest = outline.nest

    # Below the board's edge the ring is solid; inside it, under the board, the
    # nest is hollow; and the board's own pocket is open above.
    assert inside(nest, 14.5, 10.0, -3.0)
    assert not inside(nest, -10.0, 0.0, -3.0)
    assert not inside(nest, 0.0, 14.0, 3.0)
    # The floor, 2 mm thick under the hollow.
    assert inside(nest, -10.0, 0.0, -7.0)


def test_each_test_point_is_propped_except_where_a_part_sits_under_it(
    outline: PcbFixture,
) -> None:
    assert outline.plan.unsupported == ("TP3",)
    assert inside(outline.nest, -8.0, 14.0, -3.0)
    assert inside(outline.nest, 8.0, 14.0, -3.0)
    assert not inside(outline.nest, 0.0, 5.0, -3.0)


def test_a_window_is_cut_where_a_part_hangs_over_the_edge(outline: PcbFixture) -> None:
    # The USB connector stands 3 mm past the right edge: the wall is cut for it
    # above the board, and stands elsewhere.
    assert not inside(outline.nest, 16.5, -12.0, 1.0)
    assert inside(outline.nest, 16.5, 5.0, 1.0)
    # The window is open to the rim, so the part lifts out with the board.
    assert not inside(outline.nest, 16.5, -12.0, 9.5)


def test_the_walls_rise_to_a_rim_the_plate_rests_on(outline: PcbFixture) -> None:
    assert inside(outline.nest, 16.5, 5.0, 9.5)
    assert outline.plan.plate_underside_mm == 10.0
    box = cast(cq.Shape, outline.nest.val()).BoundingBox()

    # The rim is at 10 mm; the dowels stand 1.8 mm above it, into the plate.
    assert box.zmax == pytest.approx(11.8, abs=0.05)


def test_the_dowels_stand_on_ears_beyond_the_ends_of_the_board(
    outline: PcbFixture,
) -> None:
    for y in (-27.1, 27.1):
        assert inside(outline.nest, 0.0, y, 5.0)  # the ear
        assert inside(outline.nest, 0.0, y, 11.0)  # the dowel above the rim
        assert not inside(outline.nest, 2.2, y, 11.0)  # and nothing beside it there


def test_locating_by_holes_puts_posts_up_through_them(holes: PcbFixture) -> None:
    # Holes at (+-12, +-19); the pair across a diagonal.
    assert inside(holes.nest, 12.0, 19.0, 0.5)
    assert inside(holes.nest, -12.0, -19.0, 11.0)
    assert not inside(holes.nest, 12.0, -19.0, 0.5)
    assert {a.kind for a in holes.plan.anchors} == {"post"}


# --- the plate --------------------------------------------------------------------------------


def test_the_plate_has_a_bore_over_each_pad_and_a_socket_for_each_dowel(
    outline: PcbFixture,
) -> None:
    plate = outline.plate

    for x, y in ((-8.0, 14.0), (8.0, 14.0), (0.0, 5.0)):
        assert not inside(plate, x, y, 11.0)
        assert inside(plate, x + 1.0, y, 11.0)

    assert not inside(plate, 0.0, 27.1, 11.0)
    assert inside(plate, 0.0, 27.1 + 3.0, 11.0)


def test_the_plate_is_a_slab_at_the_top_of_the_rim(outline: PcbFixture) -> None:
    box = cast(cq.Shape, outline.plate.val()).BoundingBox()

    assert box.zmin == pytest.approx(10.0, abs=0.05)
    assert box.zmax == pytest.approx(12.0, abs=0.05)
    assert inside(outline.plate, 0.0, 0.0, 11.0)


def test_each_part_prints_on_its_lowest_face(outline: PcbFixture) -> None:
    for model in print_oriented(outline).values():
        assert cast(cq.Shape, model.val()).BoundingBox().zmin == pytest.approx(
            0.0, abs=0.05
        )


def test_a_part_too_big_for_the_bed_is_refused(outline: PcbFixture) -> None:
    small = {"build_volume_mm": {"x": 20, "y": 20, "z": 20}}

    with pytest.raises(ValueError, match="printer's bed"):
        require_fits_bed(outline, small)

    require_fits_bed(outline, dict(PROFILE))


# --- the record ---------------------------------------------------------------------------------


def test_the_record_names_the_board_and_claims_nothing(outline: PcbFixture) -> None:
    record = fixture_record(outline, {})

    assert record["verified"] is False
    assert record["closure_built"] is False
    assert record["board"]["sha256"] == outline.spec.board_sha256
    assert record["pin"]["figures_from"].startswith("the user's file")
    assert record["tolerance_status"] == "provisional"
    assert "accuracy_mm" not in json.dumps(record)
    assert record["plan"]["misalignment"]["note"].startswith("A worst case")
    assert {p["identifier"] for p in record["points"]} == {"TP1", "TP2", "TP3"}
    assert all(p["misalignment_mm"] <= p["slack_mm"] for p in record["points"])


# --- the command ----------------------------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_command_builds_and_exports_a_fixture(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path)
    data = fixture_template(board)
    data["board"]["file"] = board.name
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(data))
    exit_code, output = run(
        capsys,
        "fixture",
        "build",
        "--fixture-file",
        str(path),
        "--output-directory",
        str(tmp_path / "out"),
        "--printer-profile",
        str(PRINTER_PATH),
    )

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    assert output["verified"] is False
    assert "held by hand" in output["closure"]
    assert set(output["parts"]) == {"nest", "plate"}
    assert Path(output["parts"]["nest"]["stl_path"]).is_file()
    assert all(output["checks"].values())

    record = json.loads(Path(output["build_record"]).read_text())

    assert record["parts"]["plate"]["stl_sha256"]


def test_the_command_refuses_a_fixture_that_cannot_land(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path)
    data = json.loads(board.read_text())

    for entry in data["test_points"]:
        entry["pad_diameter_mm"] = 1.5

    board.write_text(json.dumps(data))
    fixture = fixture_template(board)
    fixture["board"]["file"] = board.name
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture))

    assert (
        main(
            [
                "fixture",
                "build",
                "--fixture-file",
                str(path),
                "--output-directory",
                str(tmp_path / "out"),
                "--printer-profile",
                str(PRINTER_PATH),
            ]
        )
        == 1
    )
    assert "can move the tip" in capsys.readouterr().err
