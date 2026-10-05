"""Electronics layers: a plate and spacers that stack over a board."""

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
from zcad_core.features.stack_layers import (
    build_layer,
    check_layer_data,
    check_layer_file,
    check_layers,
    layer_template,
    load_layer,
    require_layer_fits_bed,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import board_template
from zcad_core.profiles import load_printer_profile

PRINTER_PATH = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PRINTER = load_printer_profile(PRINTER_PATH)
HOLES = [[-12.0, -19.0], [12.0, -19.0], [-12.0, 19.0], [12.0, 19.0]]


def write_board(directory: Path, name: str = "board.json", **changes: Any) -> Path:
    data = copy.deepcopy(board_template())
    data.update(changes)
    path = directory / name
    path.write_text(json.dumps(data))

    return path


def real_parts_board(
    directory: Path, parts: list[dict[str, Any]], **changes: Any
) -> Path:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = parts
    data.update(changes)
    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def part(identifier: str, x: float, y: float, **changes: Any) -> dict[str, Any]:
    return {
        "identifier": identifier,
        "center_x_mm": x,
        "center_y_mm": y,
        "width_mm": 6.0,
        "depth_mm": 6.0,
        "bottom_offset_from_board_top_mm": 0.0,
        "height_mm": 4.0,
        **changes,
    }


def write_layer(
    directory: Path, board: Path, name: str = "layer.json", **changes: Any
) -> Path:
    data = layer_template(board)
    data["source"] = "a layer for tests"
    data.update(changes)
    path = directory / name
    path.write_text(json.dumps(data))

    return path


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return any(
        solid.isInside(cq.Vector(x, y, z))
        for solid in cast(cq.Shape, model.val()).Solids()
    )


def run(*args: str) -> tuple[int, dict[str, Any]]:
    out = io.StringIO()

    with contextlib.redirect_stdout(out):
        code = main(list(args))

    return code, cast(dict[str, Any], json.loads(out.getvalue()))


# --- the file -----------------------------------------------------------------------------------


def test_the_template_names_its_board_by_hash(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    data = layer_template(board)

    assert len(data["board"]["sha256"]) == 64 and data["board"]["sha256"] != "0" * 64
    assert check_layer_data(data).valid


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"file_kind": "stack"}, "file_kind must be"),
        ({"colour": "red"}, "Unknown field"),
        ({"fastener": "M9"}, "must name a catalogued fastener"),
        ({"spacer_mm": -1}, "spacer_mm"),
        ({"plate_mm": 0.1}, "plate_mm"),
        ({"board": {"file": "b.json", "sha256": "abc"}}, "board.sha256"),
        ({"needs_review": "unchecked"}, "not reviewed"),
    ],
)
def test_a_layer_file_that_cannot_be_right_is_refused(
    changes: dict[str, Any], message: str
) -> None:
    data = {**layer_template(), **changes}
    report = check_layer_data(data)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


def test_a_layer_is_refused_if_its_board_has_changed(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    layer = write_layer(tmp_path, board)
    write_board(tmp_path, identifier="CHANGED")
    report = check_layer_file(layer, PRINTER)

    assert not report.valid
    assert any("has changed since the layer file named it" in e for e in report.errors)


# --- the plan -----------------------------------------------------------------------------------


def test_the_spacer_clears_the_tallest_part_with_the_air_the_file_asks_for(
    tmp_path: Path,
) -> None:
    board = real_parts_board(tmp_path, [part("CHIP", 0.0, 5.0, height_mm=10.0)])
    report = check_layer_file(write_layer(tmp_path, board), PRINTER)

    assert report.valid, report.errors
    assert report.summary is not None
    assert report.summary["tallest_part"] == "CHIP"
    assert report.summary["minimum_spacer_mm"] == 11.0
    assert report.summary["spacer_mm"] == 11.0
    assert report.summary["stack_height_mm"] == 13.0


def test_the_spacer_is_rounded_up_to_the_half_millimetre(tmp_path: Path) -> None:
    board = real_parts_board(tmp_path, [part("CHIP", 0.0, 5.0, height_mm=3.6)])
    report = check_layer_file(write_layer(tmp_path, board, clearance_mm=0.7), PRINTER)

    assert report.summary is not None
    assert report.summary["minimum_spacer_mm"] == 4.3
    assert report.summary["spacer_mm"] == 4.5


@pytest.mark.parametrize(
    ("layer", "parts", "message"),
    [
        (
            {"spacer_mm": 5.0},
            [part("CHIP", 0.0, 5.0, height_mm=10.0)],
            "under the 11 mm needed",
        ),
        ({"fastener": "M3"}, [], "will not pass"),
        ({"wall_mm": 0.8}, [], "minimum wall"),
        ({"plate_mm": 0.8}, [], "minimum floor"),
        ({}, [part("TALL", -12.0, -15.0)], "would stand on TALL"),
        (
            {},
            [part("EDGE", 13.0, 15.0, access_edge="positive_x")],
            "comes within",
        ),
    ],
)
def test_a_layer_that_cannot_be_built_is_refused_with_why(
    tmp_path: Path, layer: dict[str, Any], parts: list[Any], message: str
) -> None:
    board = real_parts_board(tmp_path, parts) if parts else write_board(tmp_path)
    report = check_layer_file(write_layer(tmp_path, board, **layer), PRINTER)

    assert not report.valid
    assert any(message in e for e in report.errors), report.errors


# --- the solids ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("layer")
    board = real_parts_board(
        directory,
        [
            part("CHIP", 0.0, 5.0, height_mm=4.0, lid_vent=True),
            part(
                "JACK", 13.0, -5.0, width_mm=5.0, depth_mm=5.0, access_edge="positive_x"
            ),
        ],
    )

    return build_layer(load_layer(write_layer(directory, board)), PRINTER)


def test_a_layer_builds_a_plate_and_a_spacer_that_clear_the_board(built: Any) -> None:
    assert built.passed, built.checks
    assert set(built.checks) == {
        "plate.one_solid",
        "spacer.one_solid",
        "spacers_clear_of_the_board",
    }
    assert set(built.parts) == {"plate", "spacer"}
    assert "makes no electrical connection" in built.notes[0]
    assert built.summary["spacers_to_print"] == 4


def test_the_spacer_is_a_tube_round_the_fastener(built: Any) -> None:
    spacer = built.parts["spacer"]
    box = workplane_shape(spacer).BoundingBox()

    assert box.xlen == pytest.approx(2.9 + 2 * 1.2, abs=0.01)
    assert box.zlen == pytest.approx(built.summary["spacer_mm"], abs=0.001)
    assert not inside(spacer, 0.0, 0.0, 2.0)
    assert inside(spacer, 1.8, 0.0, 2.0)


def test_the_plate_is_the_outline_with_the_holes_and_an_opening_each_way_a_part_is_reached(
    built: Any,
) -> None:
    plate = built.parts["plate"]
    z = 1.0
    box = workplane_shape(plate).BoundingBox()

    assert (box.xlen, box.ylen, box.zlen) == pytest.approx((30.0, 45.0, 2.0), abs=0.01)
    # A hole at each corner pattern point, solid beside it.
    for x, y in HOLES:
        assert not inside(plate, x, y, z)
        assert inside(plate, x * 0.7, y * 0.7, z)
    # A window over the vented part, and a notch from the edge part out to its edge.
    assert not inside(plate, 0.0, 5.0, z)
    assert inside(plate, 10.0, 5.0, z)
    assert not inside(plate, 13.0, -5.0, z)
    assert not inside(plate, 14.8, -5.0, z)
    assert inside(plate, 8.0, -5.0, z)
    assert built.summary["openings"] == [
        "CHIP, which draws air from above",
        "JACK, open to its edge",
        "USB_C, open to its edge",
    ]


def test_the_cable_connector_is_open_to_its_edge_too(built: Any) -> None:
    plate = built.parts["plate"]

    # USB_C is against the negative_y edge in the template, 9 mm wide.
    assert not inside(plate, 0.0, -21.0, 1.0)
    assert inside(plate, 10.0, -21.0, 1.0)


def test_a_layer_too_big_for_the_bed_is_refused(tmp_path: Path) -> None:
    board = write_board(
        tmp_path,
        board={"width_mm": 200.0, "length_mm": 50.0, "thickness_mm": 1.6},
        mounting_holes={
            "diameter_mm": 2.7,
            "positions_mm": [[-90.0, -20.0], [90.0, -20.0]],
        },
    )
    layer = build_layer(load_layer(write_layer(tmp_path, board)), PRINTER)

    with pytest.raises(ValueError, match="the printer's bed"):
        require_layer_fits_bed(layer, PRINTER)


# --- check-layers -------------------------------------------------------------------------------


def test_two_layers_with_the_same_holes_stack(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    lower = write_layer(tmp_path, board, "lower.json")
    upper = write_layer(tmp_path, board, "upper.json")
    report = check_layers(upper, lower, PRINTER)

    assert report.stacks, report.errors
    assert report.summary["hole_offset_mm"] == 0.0
    assert report.summary["stack_height_mm"] == 9.0
    assert "makes no electrical connection" in report.summary["not_claimed"]


@pytest.mark.parametrize(
    ("holes", "message"),
    [
        (
            [[-12.0, -19.0], [12.0, -19.0], [-12.0, 19.0], [12.0, 19.5]],
            "differ by 0.50 mm",
        ),
        ([[-12.0, -19.0], [12.0, -19.0]], "2 and 4 mounting holes"),
    ],
)
def test_layers_whose_holes_differ_do_not_stack(
    tmp_path: Path, holes: list[list[float]], message: str
) -> None:
    lower_board = write_board(tmp_path, "lower_board.json")
    other = write_board(
        tmp_path,
        "other_board.json",
        mounting_holes={"diameter_mm": 2.7, "positions_mm": holes},
    )
    lower = write_layer(tmp_path, lower_board, "lower.json")
    upper = write_layer(tmp_path, other, "upper.json")
    report = check_layers(upper, lower, PRINTER)

    assert not report.stacks
    assert any(message in e for e in report.errors), report.errors


def test_layers_on_different_fasteners_do_not_stack(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    lower = write_layer(tmp_path, board, "lower.json")
    upper = write_layer(tmp_path, board, "upper.json", fastener="M2")
    report = check_layers(upper, lower, PRINTER)

    assert not report.stacks
    assert any("different fasteners" in e for e in report.errors)


def test_an_upper_board_with_a_part_underneath_does_not_stack(tmp_path: Path) -> None:
    # It rests on the lower layer's plate; a 6 mm part under it, its bottom 9 mm
    # below the board's top, would stand 7.4 mm into that plate and below.
    (tmp_path / "lo").mkdir()
    (tmp_path / "up").mkdir()
    lower_board = real_parts_board(tmp_path / "lo", [part("U1", 0, 0)])
    upper_board = real_parts_board(
        tmp_path / "up",
        [
            part("U1", 0, 0),
            part(
                "BOT",
                0,
                0,
                width_mm=10,
                depth_mm=10,
                bottom_offset_from_board_top_mm=-9.0,
                height_mm=6.0,
            ),
        ],
    )
    lower = write_layer(tmp_path / "lo", lower_board, "lower.json")
    upper = write_layer(tmp_path / "up", upper_board, "upper.json")
    report = check_layers(upper, lower, PRINTER)

    assert not report.stacks
    assert any("BOT 7.4 mm under it" in e for e in report.errors), report.errors
    assert report.summary["upper_underside_checked"] is True


# --- the commands -------------------------------------------------------------------------------


def test_the_commands_write_check_and_build_a_layer(tmp_path: Path) -> None:
    board = write_board(tmp_path)
    layer = tmp_path / "layer.json"
    code, _ = run(
        "stack", "layer", "template", "--board-file", str(board), "--output", str(layer)
    )
    data = json.loads(layer.read_text())
    data["source"] = "a layer for tests"
    layer.write_text(json.dumps(data))

    assert code == 0
    code, report = run("stack", "check", str(layer))

    assert code == 0 and report["kind"] == "layer" and report["valid"] is True
    code, built_ = run(
        "stack",
        "layer",
        "build",
        "--layer-file",
        str(layer),
        "--output-directory",
        str(tmp_path / "out"),
    )

    assert code == 0
    assert built_["validation_status"] == "PASS"
    assert set(built_["parts"]) == {"plate", "spacer"}
    assert all(built_["checks"].values())
    assert "makes no electrical connection" in built_["not_claimed"][0]


def test_the_check_layers_command_exits_1_when_layers_do_not_stack(
    tmp_path: Path,
) -> None:
    lower_board = write_board(tmp_path, "lower_board.json")
    other = write_board(
        tmp_path,
        "other_board.json",
        mounting_holes={
            "diameter_mm": 2.7,
            "positions_mm": [
                [-12.0, -19.0],
                [12.0, -19.0],
                [-12.0, 19.0],
                [11.0, 19.0],
            ],
        },
    )
    lower = write_layer(tmp_path, lower_board, "lower.json")
    upper = write_layer(tmp_path, other, "upper.json")
    code, report = run(
        "stack", "check-layers", "--upper", str(upper), "--lower", str(lower)
    )

    assert code == 1 and report["stacks"] is False

    code, report = run(
        "stack", "check-layers", "--upper", str(lower), "--lower", str(lower)
    )

    assert code == 0 and report["stacks"] is True
