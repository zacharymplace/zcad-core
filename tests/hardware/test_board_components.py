"""The board parts extracted from vendor models."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.hardware import (
    BoardComponentSpec,
    get_board,
    list_boards,
    load_board_components,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DATA = REPOSITORY_ROOT / "src/zcad_core/hardware/data/board-components"
PART = BoardComponentSpec(
    identifier="part",
    center_x_mm=0.0,
    center_y_mm=0.0,
    width_mm=2.0,
    depth_mm=2.0,
    bottom_offset_from_board_top_mm=0.0,
    height_mm=1.0,
)


@pytest.mark.parametrize("board_identifier", list_boards())
def test_every_board_has_parts_clear_of_its_pcb(board_identifier: str) -> None:
    board = get_board(board_identifier)
    components = board.components

    assert components
    for part in components:
        part.validate_against_board(board.board_thickness_mm)
        # Parts lie on the board, give or take an overhanging connector: the
        # Pi 5's Ethernet jack, LED windows and all, stands 3 mm proud.
        assert abs(part.center_x_mm) < board.board_width_mm / 2 + 3.5
        assert abs(part.center_y_mm) < board.board_length_mm / 2 + 3.5


@pytest.mark.parametrize(
    "path", sorted(DATA.glob("*.json")), ids=lambda path: path.stem
)
def test_data_matches_its_vendor_model(path: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    model = REPOSITORY_ROOT / record["source_model_path"]

    assert load_board_components(path.stem)
    if not model.is_file():
        pytest.skip("the vendor model is in the evidence checkout")
    assert (
        hashlib.sha256(model.read_bytes()).hexdigest() == record["source_model_sha256"]
    ), "re-run scripts/extract-board-components.py for the new model"


def test_uno_barrel_jack_needs_an_opening() -> None:
    uno = get_board("ARDUINO_UNO_R4_WIFI")

    jack = [
        part
        for part in uno.components
        if part.access_edge == "negative_x"
        and part.bottom_offset_from_board_top_mm >= 0
    ]

    assert len(jack) == 1
    assert jack[0].height_mm == pytest.approx(11.09, abs=0.01)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"identifier": " "}, "identifier must not be empty"),
        ({"height_mm": 0.0}, "height_mm must be greater than zero"),
        ({"access_edge": "up"}, "unsupported access edge"),
    ],
)
def test_component_rejects_invalid_values(
    change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(PART, **change).validate()  # type: ignore[arg-type]


def test_component_may_not_pass_through_the_board() -> None:
    below = replace(PART, bottom_offset_from_board_top_mm=-3.0, height_mm=1.4)
    through = replace(PART, bottom_offset_from_board_top_mm=-3.0, height_mm=2.5)

    below.validate_against_board(1.6)
    with pytest.raises(ValueError, match="wholly above or below"):
        through.validate_against_board(1.6)
