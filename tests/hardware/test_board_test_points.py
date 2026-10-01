"""A board's test points, in its file."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.hardware import board_template, check_board_data, load_board


def template() -> dict[str, Any]:
    return copy.deepcopy(board_template())


def point(
    name: str, x: float, y: float, pad: float = 1.5, **more: Any
) -> dict[str, Any]:
    return {"identifier": name, "x_mm": x, "y_mm": y, "pad_diameter_mm": pad, **more}


def errors_of(data: dict[str, Any]) -> str:
    report = check_board_data(data)

    assert not report.valid

    return "\n".join(report.errors)


def test_the_template_carries_two_test_points_and_is_valid() -> None:
    data = template()
    report = check_board_data(data)

    assert [p["identifier"] for p in data["test_points"]] == ["TP1", "TP2"]
    assert report.valid
    assert report.warnings == ()


def test_a_board_without_test_points_has_none() -> None:
    data = template()
    del data["test_points"]

    assert check_board_data(data).valid


def test_a_loaded_board_carries_its_test_points(tmp_path: Path) -> None:
    path = tmp_path / "board.json"
    path.write_text(json.dumps(template()))
    board = load_board(path)

    assert [p.identifier for p in board.test_points] == ["TP1", "TP2"]
    assert board.test_points[0].position == (-8.0, 12.5)
    assert board.test_points[0].pad_diameter_mm == 3.0
    assert board.test_points[0].side == "top"
    assert board.test_points[0].net == "3V3"


def test_the_side_defaults_to_the_top_and_may_be_the_bottom(tmp_path: Path) -> None:
    data = template()
    data["test_points"] = [point("TP1", 0, 0), point("TP2", 5, 0, side="bottom")]
    path = tmp_path / "board.json"
    path.write_text(json.dumps(data))
    board = load_board(path)

    assert [p.side for p in board.test_points] == ["top", "bottom"]


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.update(test_points="all"), "test_points must be a list"),
        (lambda d: d.update(test_points=["TP1"]), "must be an object"),
        (lambda d: d["test_points"][0].pop("identifier"), "identifier"),
        (lambda d: d["test_points"][0].update(identifier="has space"), "identifier"),
        (lambda d: d["test_points"][0].pop("x_mm"), "x_mm is missing"),
        (lambda d: d["test_points"][0].update(y_mm="up"), "must be a number"),
        (lambda d: d["test_points"][0].update(pad_diameter_mm=0.2), "pad_diameter_mm"),
        (lambda d: d["test_points"][0].update(pad_diameter_mm=20), "pad_diameter_mm"),
        (lambda d: d["test_points"][0].update(side="left"), "side must be one of"),
        (lambda d: d["test_points"][0].update(net=3), "net must be text"),
        (
            lambda d: d["test_points"][1].update(identifier="TP1"),
            "identifiers must be unique",
        ),
        (lambda d: d["test_points"][0].update(x_mm=14.5), "not wholly on the board"),
        (lambda d: d["test_points"][0].update(y_mm=-22.4), "not wholly on the board"),
        (lambda d: d["test_points"][1].update(x_mm=-8.5), "overlap"),
    ],
)
def test_a_test_point_that_cannot_be_right_is_refused(change: Any, expect: str) -> None:
    data = template()
    change(data)

    assert expect in errors_of(data)


def test_pads_on_opposite_sides_may_share_a_place() -> None:
    data = template()
    data["test_points"] = [point("TP1", 0, 0), point("TP2", 0, 0, side="bottom")]

    assert check_board_data(data).valid


def test_a_pad_on_a_rounded_corner_is_judged_by_the_outline() -> None:
    data = template()
    data["outline"] = {"type": "rounded_rectangle", "radius_mm": 5.0}
    # (13.5, 21.0) is inside the 30 x 45 rectangle but off a 5 mm round corner.
    data["test_points"] = [point("TP1", 13.5, 21.0)]

    assert "not wholly on the board" in errors_of(data)

    data["test_points"] = [point("TP1", 0.0, 21.0)]

    assert check_board_data(data).valid


def test_the_command_counts_the_points_by_side(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    data = template()
    data["test_points"].append(point("TP3", 0, 0, side="bottom"))
    path = tmp_path / "board.json"
    path.write_text(json.dumps(data))
    exit_code = main(["board", "check", str(path)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["board"]["test_points"] == {"top": 2, "bottom": 1}
