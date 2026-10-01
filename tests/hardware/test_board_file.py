"""Board files: checks, loading, and what a loaded board gives the builders."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.hardware import board_template, check_board_data, load_board
from zcad_core.hardware.electronics.board_file import (
    ENVELOPE_IDENTIFIER,
    BoardOrigin,
    board_from_data,
)


def template() -> dict[str, Any]:
    return copy.deepcopy(board_template())


def write(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")

    return path


def errors_of(data: Any) -> str:
    report = check_board_data(data)

    assert not report.valid

    return "\n".join(report.errors)


def from_data(data: dict[str, Any]) -> Any:
    return board_from_data(data, BoardOrigin(path="x.json", sha256="0" * 64))


def test_the_template_is_valid_and_clean() -> None:
    report = check_board_data(template())

    assert report.valid
    assert report.errors == ()
    assert report.warnings == ()


def test_a_non_object_is_refused() -> None:
    assert not check_board_data([1, 2]).valid


def test_every_problem_is_reported_at_once() -> None:
    data = template()
    data["units"] = "inch"
    data["outline"] = "circle"
    data["bogus"] = 1

    assert len(check_board_data(data).errors) >= 3


def _no_spacing(data: dict[str, Any]) -> None:
    data["mounting_holes"].pop("spacing_mm", None)
    data["mounting_holes"].pop("positions_mm", None)


def _both_hole_forms(data: dict[str, Any]) -> None:
    data["mounting_holes"]["positions_mm"] = [[0, 0]]
    data["mounting_holes"]["spacing_mm"] = [10, 10]


def _add_component(data: dict[str, Any]) -> None:
    data["components"] = [
        {
            "identifier": "X",
            "center_x_mm": 0,
            "center_y_mm": 0,
            "width_mm": 2,
            "depth_mm": 2,
            "height_mm": 2,
            "bottom_offset_from_board_top_mm": 0,
        }
    ]


@pytest.mark.parametrize(
    ("change", "expect"),
    [
        (lambda d: d.update(schema_version="9.0.0"), "schema_version"),
        (lambda d: d.update(units="inch"), "units must be 'mm'"),
        (lambda d: d.update(outline="circle"), "outline must be 'rectangle'"),
        (lambda d: d.update(identifier="has space"), "identifier"),
        (lambda d: d.update(needs_review="check holes"), "not reviewed"),
        (lambda d: d.update(bogus=1), "Unknown field"),
        (lambda d: d["cable_connector"].update(edge="up"), "edge must be one of"),
        (lambda d: d["envelope"].update(bottom_mm=3.0), "only top_mm"),
        (_no_spacing, "exactly one"),
        (_both_hole_forms, "exactly one"),
        (_add_component, "not both"),
        (lambda d: d["power"].pop("source"), "power.source"),
        (lambda d: d["power"].update(peak_w=0.1), "peak_w"),
    ],
)
def test_what_cannot_be_right_is_refused(
    change: Callable[[dict[str, Any]], object], expect: str
) -> None:
    data = template()
    change(data)

    assert expect in errors_of(data)


def test_a_board_in_the_wrong_unit_is_warned_of() -> None:
    data = template()
    data["board"].update(width_mm=300, length_mm=400)

    report = check_board_data(data)

    assert report.valid
    assert any("millimetres" in warning for warning in report.warnings)


def test_no_mounting_holes_warns_of_a_cradle() -> None:
    data = template()
    del data["mounting_holes"]

    report = check_board_data(data)

    assert report.valid
    assert any("cradle" in warning for warning in report.warnings)
    assert from_data(data).mounting_hole_diameter_mm is None


def test_a_loaded_board_carries_its_file_and_is_never_verified(
    tmp_path: Path,
) -> None:
    path = write(tmp_path / "board.json", template())
    board = load_board(path)

    assert board.identifier == "EXAMPLE_BOARD"
    assert board.verified is False
    assert Path(board.origin.path) == path.resolve()
    assert len(board.origin.sha256) == 64
    assert board.provenance()["kind"] == "file"
    assert board.provenance()["sha256"] == board.origin.sha256


def test_the_hash_follows_the_file(tmp_path: Path) -> None:
    first = load_board(write(tmp_path / "a.json", template())).origin.sha256
    changed = template()
    changed["board"]["width_mm"] = 31
    second = load_board(write(tmp_path / "a.json", changed)).origin.sha256

    assert first != second


def test_an_unusable_file_is_not_loaded(tmp_path: Path) -> None:
    data = template()
    data["units"] = "inch"

    with pytest.raises(ValueError, match="units"):
        load_board(write(tmp_path / "bad.json", data))


def test_an_unparsable_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError):
        load_board(path)


def test_an_envelope_becomes_one_box_above_the_board() -> None:
    board = from_data(template())

    assert [part.identifier for part in board.components] == [ENVELOPE_IDENTIFIER]
    assert board.power_figure is not None
    assert board.power_figure.source.kind == "user"


def test_a_board_file_builds_an_enclosure_with_its_own_power(
    tmp_path: Path,
) -> None:
    board = load_board(write(tmp_path / "board.json", template()))
    assembly = build_board_assembly(
        board=board, board_placement=Placement(), connector_access_clearance_mm=2.0
    )
    enclosure = build_enclosure(assembly, board=board, design=EnclosureDesign())

    assert enclosure.thermal is not None
    assert enclosure.thermal.typical_w == pytest.approx(0.5)
    assert "user" in str(enclosure.thermal.sources)


def test_a_components_file_loads_its_parts_and_warns_of_an_unmarked_overhang() -> None:
    data = template()
    del data["envelope"]
    data["components"] = [
        {
            "identifier": "JACK",
            "center_x_mm": 0,
            "center_y_mm": 20,
            "width_mm": 9,
            "depth_mm": 14,
            "height_mm": 11,
            "bottom_offset_from_board_top_mm": 0,
        }
    ]

    report = check_board_data(data)

    assert report.valid
    assert any("access_edge" in warning for warning in report.warnings)
    assert [part.identifier for part in from_data(data).components] == ["JACK"]

    data["components"][0]["access_edge"] = "positive_y"

    assert check_board_data(data).warnings == ()
