"""Board files with a rounded or polygon outline: what the check refuses and
what the loaded board gives the builders."""

from __future__ import annotations

import copy
import re
from typing import Any

import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.hardware import board_template, check_board_data
from zcad_core.hardware.electronics.board_file import BoardOrigin, board_from_data

ROUNDED = {"type": "rounded_rectangle", "radius_mm": 4.0}
# 30 x 45 with the top right corner cut and a notch in the far edge.
NOTCHED = {
    "type": "polygon",
    "points_mm": [
        [-15, -22.5],
        [15, -22.5],
        [15, 18],
        [11, 22.5],
        [2, 22.5],
        [2, 17],
        [-2, 17],
        [-2, 22.5],
        [-15, 22.5],
    ],
}


def template(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(board_template())
    data.update(changes)

    return data


def from_data(data: dict[str, Any]) -> Any:
    return board_from_data(data, BoardOrigin(path="x.json", sha256="0" * 64))


def errors_of(data: dict[str, Any]) -> str:
    report = check_board_data(data)

    assert not report.valid

    return "\n".join(report.errors)


def test_a_rounded_rectangle_is_valid_and_becomes_points() -> None:
    data = template(outline=ROUNDED)

    assert check_board_data(data).valid

    points = from_data(data).outline_points_mm

    assert points is not None and len(points) > 20
    assert min(x for x, _ in points) == pytest.approx(-15)
    assert max(y for _, y in points) == pytest.approx(22.5)


def test_a_rectangle_has_no_points() -> None:
    assert from_data(template()).outline_points_mm is None
    assert from_data(template(outline="rectangle")).outline_points_mm is None


def test_a_polygon_is_valid_and_comes_out_counter_clockwise() -> None:
    clockwise = {"type": "polygon", "points_mm": NOTCHED["points_mm"][::-1]}
    points = from_data(template(outline=clockwise)).outline_points_mm

    assert points is not None and len(points) == 9
    assert (
        sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, [*points[1:], points[0]]))
        > 0
    )


def _points(*points: Any) -> dict[str, Any]:
    return {"type": "polygon", "points_mm": list(points)}


@pytest.mark.parametrize(
    ("outline", "expect"),
    [
        ("circle", "outline must be 'rectangle'"),
        ({"type": "blob"}, "outline must be 'rectangle'"),
        ({"type": "rounded_rectangle", "radius_mm": 20.0}, "more than half"),
        ({"type": "rounded_rectangle"}, "radius_mm"),
        (_points([0, 0], [1, 1]), "3 to 500"),
        (_points([-15, -22.5], [15, -22.5], "x"), "pair of numbers"),
        (
            _points([-15, -22.5], [15, 22.5], [15, -22.5], [-15, 22.5]),
            "cross or touch themselves",
        ),
        (_points([0, 0], [1, 0], [2, 0]), "enclose no area"),
        (
            _points([-10, -22.5], [10, -22.5], [10, 22.5], [-10, 22.5]),
            "must fill that rectangle",
        ),
    ],
)
def test_an_outline_that_cannot_be_right_is_refused(outline: Any, expect: str) -> None:
    assert re.search(expect, errors_of(template(outline=outline)))


def test_a_hole_off_the_outline_is_refused_though_inside_the_rectangle() -> None:
    # (14, 21) is inside the 30 x 45 rectangle but outside a 4 mm round corner.
    data = template(outline=ROUNDED)
    data["mounting_holes"]["positions_mm"] = [[14, 21], [-12, -19]]

    assert "not inside" in errors_of(data)


def test_a_hole_near_a_rounded_edge_is_warned_of() -> None:
    data = template(outline=ROUNDED)
    data["mounting_holes"]["positions_mm"] = [[12, 19], [-12, -19], [12, -19]]
    report = check_board_data(data)

    assert report.valid
    assert report.warnings == ()

    data["mounting_holes"]["positions_mm"][0] = [12.5, 20.0]

    assert any("near the edge" in w for w in check_board_data(data).warnings)


def test_a_connector_hanging_off_a_rounded_corner_is_refused() -> None:
    data = template(outline={"type": "rounded_rectangle", "radius_mm": 12.0})
    data["cable_connector"]["center_offset_mm"] = 10.0

    assert "hangs off the board's outline" in errors_of(data)


def test_a_connector_clear_of_the_corners_is_accepted() -> None:
    assert check_board_data(template(outline=ROUNDED)).valid


def test_a_connector_off_the_edge_is_judged_by_the_edge_it_is_on() -> None:
    # The negative_y edge runs along X, the board's 30 mm width: 10 + 6 > 15.
    data = template()
    data["cable_connector"].update(center_offset_mm=10.0, width_mm=12.0)

    assert "runs off its negative_y edge" in errors_of(data)

    data["cable_connector"]["edge"] = "negative_x"

    # That edge runs along Y, 45 mm: 10 + 6 < 22.5.
    assert check_board_data(data).valid


def test_a_sparse_outline_is_warned_of() -> None:
    sparse = _points(
        [-15, -22.5], [15, -22.5], [15, -18], [-10, -18], [-10, 22.5], [-15, 22.5]
    )
    data = _without_holes(template(outline=sparse))
    del data["envelope"]
    # The template's test points lie off this sliver of a board.
    del data["test_points"]
    data["cable_connector"].update(width_mm=1.0, depth_mm=1.0, center_offset_mm=0.0)
    report = check_board_data(data)

    assert report.valid, report.errors
    assert any("fills only" in w for w in report.warnings)


# --- the envelope stands clear of a cradle --------------------------------


def _without_holes(data: dict[str, Any]) -> dict[str, Any]:
    del data["mounting_holes"]

    return data


def test_an_envelope_over_a_board_on_standoffs_covers_the_board() -> None:
    part = from_data(template()).components[0]

    assert (part.width_mm, part.depth_mm) == (30.0, 45.0)


def test_an_envelope_over_a_board_in_a_cradle_stands_clear_of_the_clips() -> None:
    part = from_data(_without_holes(template())).components[0]

    assert (part.width_mm, part.depth_mm) == (28.0, 43.0)


def test_an_envelope_follows_a_notch_by_standing_clear_of_it() -> None:
    data = _without_holes(template(outline=NOTCHED))
    part = from_data(data).components[0]

    # The notch is 5.5 mm deep: the envelope stops short of it, with room.
    assert part.depth_mm <= 45.0 - 2 * 6.0
    assert part.width_mm < 30.0


def test_an_envelope_that_cannot_clear_a_deep_notch_is_refused() -> None:
    deep = {
        "type": "polygon",
        "points_mm": [
            [-15, -22.5],
            [15, -22.5],
            [15, 22.5],
            [2, 22.5],
            [2, -10],
            [-2, -10],
            [-2, 22.5],
            [-15, 22.5],
        ],
    }
    data = _without_holes(template(outline=deep))

    assert "cannot stand clear" in errors_of(data)


# --- the PCB solid and the enclosure ---------------------------------------


def _pcb_volume(data: dict[str, Any]) -> float:
    board = from_data(data)
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    shape = assembly.get("board").transformed_geometry().val()

    return float(shape.Volume())  # type: ignore[union-attr]


def test_the_pcb_solid_follows_the_outline() -> None:
    plain = _pcb_volume(template())
    rounded = _pcb_volume(template(outline=ROUNDED))
    notched = _pcb_volume(template(outline=NOTCHED))

    assert plain == pytest.approx(30 * 45 * 1.6, rel=1e-6)
    assert rounded == pytest.approx((30 * 45 - (4 - 3.14159265) * 16) * 1.6, rel=3e-3)
    assert notched < rounded


@pytest.mark.parametrize("outline", [ROUNDED, NOTCHED])
def test_a_board_with_an_outline_builds_on_standoffs(outline: Any) -> None:
    board = from_data(template(outline=outline))
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    enclosure = build_enclosure(assembly, board=board, design=EnclosureDesign())

    assert enclosure.board_support == "standoffs"


@pytest.mark.parametrize("outline", [ROUNDED, NOTCHED])
def test_a_board_with_an_outline_builds_in_a_cradle(outline: Any) -> None:
    board = from_data(_without_holes(template(outline=outline)))
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    enclosure = build_enclosure(assembly, board=board, design=EnclosureDesign())

    assert enclosure.board_support == "cradle"


def test_a_rectangular_board_with_no_holes_now_builds_in_a_cradle() -> None:
    """The envelope used to touch the clips' lips, so this build was refused."""

    board = from_data(_without_holes(template()))
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )

    assert build_enclosure(assembly, board=board, design=EnclosureDesign())


def test_a_wall_opening_is_judged_by_the_edge_it_is_on() -> None:
    opening = {
        "identifier": "JACK",
        "edge": "negative_y",
        "width_mm": 12.0,
        "height_mm": 6.0,
        "center_offset_mm": 10.0,
        "bottom_offset_from_board_top_mm": 0.0,
    }
    data = template(wall_openings=[opening])

    # The negative_y edge is the board's 30 mm width: 10 + 6 runs off it.
    assert "runs off its negative_y edge" in errors_of(data)

    opening["edge"] = "negative_x"

    assert check_board_data(data).valid
