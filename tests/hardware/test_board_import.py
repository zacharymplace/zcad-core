"""Reading a board from a STEP model: a small synthetic board stands in for a
vendor model, so these tests need no evidence checkout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.hardware import check_board_data, load_board
from zcad_core.hardware.electronics.board_import import (
    access_edge,
    find_pcb,
    import_step,
    load_solids,
    merge_boxes,
    pcb_outline,
    through_holes,
)

# The model sits well away from the origin, and its PCB is solid 1.
OFFSET = (100.0, 50.0, 5.0)


def box(
    size: tuple[float, float, float], centre: tuple[float, float, float]
) -> cq.Workplane:
    return cq.Workplane("XY").box(*size).translate(centre)


def pcb(*, corner_cut: bool = False) -> cq.Workplane:
    """A 30 x 40 x 1.6 mm board, z from 0 to 1.6, with four 2.7 mm holes and a
    1 mm via."""

    board = box((30, 40, 1.6), (0, 0, 0.8))
    board = (
        board.faces(">Z")
        .workplane()
        .pushPoints([(-12, -17), (12, -17), (-12, 17), (12, 17)])
        .hole(2.7)
    )
    board = board.faces(">Z").workplane().pushPoints([(0, 0)]).hole(1.0)

    if corner_cut:
        board = board.cut(box((24, 24, 3), (15, 20, 0.8)))

    return board


def model(path: Path, *, corner_cut: bool = False) -> Path:
    parts = [
        pcb(corner_cut=corner_cut),
        # A header on the board, 8.5 mm tall.
        box((10, 2.54, 8.5), (0, 8, 1.6 + 4.25)),
        # A connector hanging 1.5 mm over the +Y edge.
        box((8, 6, 3), (-5, 18.5, 1.6 + 1.5)),
        # A part under the board.
        box((6, 6, 2), (-8, -5, -1.0)),
        # A part through the board, split in two by the import.
        box((4, 4, 6), (9, 0, 1.0)),
        # A speck too low to matter.
        box((1, 1, 0.2), (5, 5, 1.7)),
    ]
    compound = cq.Compound.makeCompound([cast(cq.Shape, part.val()) for part in parts])
    shifted = compound.moved(cq.Location(cq.Vector(*OFFSET)))
    cq.exporters.export(cq.Workplane(obj=shifted), str(path))

    return path


@pytest.fixture(scope="module")
def step_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return model(tmp_path_factory.mktemp("model") / "demo board.step")


def test_the_pcb_is_the_thin_solid_with_the_largest_footprint(step_file: Path) -> None:
    solids = load_solids(step_file)

    assert find_pcb(solids) == 1


def test_a_model_with_no_thin_solid_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "block.step"
    cq.exporters.export(box((20, 20, 20), (0, 0, 10)), str(path))

    with pytest.raises(ValueError, match="No solid"):
        find_pcb(load_solids(path))


def test_through_holes_are_circular_voids_that_span_the_board(
    step_file: Path,
) -> None:
    holes = through_holes(load_solids(step_file)[0])
    wide = [hole for hole in holes if hole.diameter_mm > 2]

    assert len(wide) == 4
    assert {round(hole.diameter_mm, 2) for hole in wide} == {2.7}
    # Narrower holes are vias, pins, and the like, and are not mounting holes.
    assert [hole for hole in holes if hole.diameter_mm < 1.6] == []


def test_merging_keeps_parts_either_side_of_a_hole_apart() -> None:
    near = (0.0, 2.0, 0.0, 2.0, 0.0, 3.0)
    other = (3.0, 5.0, 0.0, 2.0, 0.0, 3.0)

    assert len(merge_boxes([near, other], True, [])) == 1
    assert len(merge_boxes([near, other], True, [(2.5, 1.0)])) == 2


def test_merging_never_joins_different_height_tiers() -> None:
    low = (0.0, 2.0, 0.0, 2.0, 0.0, 1.0)
    tall = (2.0, 4.0, 0.0, 2.0, 0.0, 9.0)

    assert len(merge_boxes([low, tall], True, [])) == 2
    assert len(merge_boxes([low, tall], False, [])) == 1


def test_an_overhang_names_its_edge() -> None:
    assert access_edge((-1, 1, 19, 22, 0, 3), 30, 40) == "positive_y"
    assert access_edge((-1, 1, 10, 12, 0, 3), 30, 40) is None


def test_an_import_reads_the_board_in_its_own_centred_frame(step_file: Path) -> None:
    imported = import_step(step_file)
    data = imported.data

    assert data["board"] == {"width_mm": 30.0, "length_mm": 40.0, "thickness_mm": 1.6}
    assert data["identifier"] == "DEMO_BOARD"
    assert data["mounting_holes"]["diameter_mm"] == 2.7
    assert sorted(map(tuple, data["mounting_holes"]["positions_mm"])) == [
        (-12.0, -17.0),
        (-12.0, 17.0),
        (12.0, -17.0),
        (12.0, 17.0),
    ]
    assert imported.report["pcb_chosen_by"] == "found"
    assert imported.report["model"]["sha256"] in data["source"]


def test_an_import_keeps_parts_that_matter_and_drops_specks(step_file: Path) -> None:
    components = import_step(step_file).data["components"]
    above = [c for c in components if c["bottom_offset_from_board_top_mm"] >= 0]
    below = [c for c in components if c["bottom_offset_from_board_top_mm"] < 0]

    assert len(above) == 3
    assert len(below) >= 1
    assert max(c["height_mm"] for c in components) == pytest.approx(8.5, abs=0.01)
    assert min(c["height_mm"] for c in above) > 0.5


def test_a_part_through_the_board_becomes_one_above_and_one_below(
    step_file: Path,
) -> None:
    components = import_step(step_file).data["components"]
    near = [c for c in components if abs(c["center_x_mm"] - 9) < 0.5]

    assert {c["bottom_offset_from_board_top_mm"] < 0 for c in near} == {True, False}


def test_the_connector_is_never_guessed(step_file: Path) -> None:
    imported = import_step(step_file)
    candidates = imported.report["cable_connector_candidates"]

    assert imported.data["needs_review"]
    assert [c["edge"] for c in candidates] == ["positive_y"]
    assert not check_board_data(imported.data).valid


def test_naming_the_connector_makes_the_file_usable(
    step_file: Path, tmp_path: Path
) -> None:
    name = import_step(step_file).report["cable_connector_candidates"][0]["identifier"]
    imported = import_step(step_file, cable_connector=name)
    connector = imported.data["cable_connector"]

    assert "needs_review" not in imported.data
    assert connector["edge"] == "positive_y"
    assert connector["width_mm"] == pytest.approx(8.0, abs=0.01)
    assert connector["height_mm"] == pytest.approx(3.0, abs=0.01)
    # Clipped to the outline: it stood 1.5 mm out past the edge.
    assert connector["depth_mm"] == pytest.approx(4.5, abs=0.01)
    assert connector["center_offset_mm"] == pytest.approx(-5.0, abs=0.01)
    assert name not in [c["identifier"] for c in imported.data["components"]]
    assert check_board_data(imported.data).valid

    path = tmp_path / "board.json"
    path.write_text(json.dumps(imported.data), encoding="utf-8")

    assert load_board(path).verified is False


def test_a_part_that_does_not_overhang_cannot_be_the_connector(
    step_file: Path,
) -> None:
    with pytest.raises(ValueError, match="not one of the parts"):
        import_step(step_file, cable_connector="top-02")


def test_a_pcb_solid_out_of_range_is_refused(step_file: Path) -> None:
    with pytest.raises(ValueError, match="--pcb-solid-index"):
        import_step(step_file, pcb_solid_index=99)


def test_a_named_pcb_solid_is_reported_as_named(step_file: Path) -> None:
    assert import_step(step_file, pcb_solid_index=1).report["pcb_chosen_by"] == "named"


def test_a_board_that_is_not_a_rectangle_gets_its_outline_as_a_polygon(
    tmp_path: Path,
) -> None:
    path = model(tmp_path / "cut.step", corner_cut=True)
    imported = import_step(path)
    outline = imported.data["outline"]

    assert outline["type"] == "polygon"
    # The cut is an L: six corners, in the board's centred frame.
    assert len(outline["points_mm"]) == 6
    assert any("not a plain rectangle" in note for note in imported.report["notes"])
    assert not [
        error for error in check_board_data(imported.data).errors if "outline" in error
    ]


def test_a_plain_rectangular_board_keeps_its_rectangle(step_file: Path) -> None:
    imported = import_step(step_file)

    assert imported.data["outline"] == "rectangle"
    assert imported.report["notes"] == []


def test_a_rounded_pcb_is_read_as_a_polygon_of_its_arcs(tmp_path: Path) -> None:
    rounded = cq.Workplane("XY").box(30, 40, 1.6, centered=(True, True, False))
    rounded = rounded.edges("|Z").fillet(3.0)
    path = tmp_path / "rounded.step"
    cq.exporters.export(rounded.translate((20, -10, 4)), str(path))

    points = pcb_outline(load_solids(path)[0])

    assert points is not None and len(points) > 20
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    assert (min(xs), max(xs)) == pytest.approx((-15, 15), abs=1e-3)
    assert (min(ys), max(ys)) == pytest.approx((-20, 20), abs=1e-3)
    area = (
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, [*points[1:], points[0]]))
        / 2
    )
    assert area == pytest.approx(30 * 40 - (4 - 3.14159265) * 9, rel=3e-3)


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(list(args))

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_command_writes_a_file_and_reports_what_to_review(
    capsys: pytest.CaptureFixture[str], step_file: Path, tmp_path: Path
) -> None:
    output = tmp_path / "board.json"
    exit_code, report = run(
        capsys, "board", "import", "--step", str(step_file), "--output", str(output)
    )

    assert exit_code == 0
    assert report["written"] == str(output)
    assert report["needs_review"]
    assert any("not reviewed" in error for error in report["errors"])
    assert report["cable_connector_candidates"][0]["edge"] == "positive_y"
    assert json.loads(output.read_text())["needs_review"]


def test_the_command_does_not_overwrite(
    capsys: pytest.CaptureFixture[str], step_file: Path, tmp_path: Path
) -> None:
    output = tmp_path / "board.json"
    output.write_text("{}")

    assert (
        main(["board", "import", "--step", str(step_file), "--output", str(output)])
        == 1
    )
    capsys.readouterr()


def test_the_second_import_with_a_connector_gives_a_valid_file(
    capsys: pytest.CaptureFixture[str], step_file: Path, tmp_path: Path
) -> None:
    output = tmp_path / "board.json"
    exit_code, report = run(
        capsys,
        "board",
        "import",
        "--step",
        str(step_file),
        "--cable-connector",
        "top-01",
        "--output",
        str(output),
    )
    _, check = run(capsys, "board", "check", str(output))

    assert exit_code == 0
    assert report["errors"] == []
    assert check["valid"] is True
