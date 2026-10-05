"""The arithmetic of a PCB test fixture: heights, anchors, props, and the budget
of clearances that can move a pin off its pad."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest

from zcad_core.features.pcb_fixture_plan import (
    Anchor,
    Budget,
    _plate_play,
    bore_diameter,
    plan_fixture,
)
from zcad_core.hardware import PogoSource, PogoSpec, board_template, load_board
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
PIN = PogoSpec(
    identifier="USER-P",
    maker="m",
    model="P",
    barrel_diameter_mm=1.0,
    tip_diameter_mm=0.6,
    free_length_mm=14.0,
    travel_mm=4.0,
    force_n=1.0,
    force_at_travel_mm=2.0,
    source=PogoSource(kind="user", title="t", url="", detail="d", read=False),
)


def part(
    name: str, x: float, y: float, w: float, d: float, h: float, z: float = 0.0
) -> dict[str, Any]:
    return {
        "identifier": name,
        "center_x_mm": x,
        "center_y_mm": y,
        "width_mm": w,
        "depth_mm": d,
        "height_mm": h,
        "bottom_offset_from_board_top_mm": z,
    }


def make_board(tmp_path: Path, **changes: Any) -> Any:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = [part("HEADER", 0, -5, 20, 3, 8.5)]
    data["test_points"] = [
        {"identifier": "TP1", "x_mm": -8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
        {"identifier": "TP2", "x_mm": 8.0, "y_mm": 14.0, "pad_diameter_mm": 3.0},
    ]
    data.update(changes)
    path = tmp_path / "board.json"
    path.write_text(json.dumps(data))

    return load_board(path)


def plan(board: Any, **changes: Any) -> Any:
    options: dict[str, Any] = {
        "board": board,
        "points": board.test_points,
        "pin": PIN,
        "working_travel_mm": 2.0,
        "locating": "outline",
        "profile": PROFILE,
    }
    options.update(changes)

    return plan_fixture(**options)


# --- heights -----------------------------------------------------------------------


def test_the_plate_stands_the_free_length_less_the_travel_above_the_board(
    tmp_path: Path,
) -> None:
    p = plan(make_board(tmp_path))

    assert p.errors == ()
    assert p.plate_top_mm == 12.0
    # A bore of two barrel diameters, within the room above the 8.5 mm part.
    assert p.plate_thickness_mm == 2.0
    assert p.plate_underside_mm == 10.0
    assert p.tallest_part_mm == 8.5
    assert p.plate_underside_mm >= p.tallest_part_mm + 0.5


def test_the_bore_is_the_barrel_pressed_in(tmp_path: Path) -> None:
    p = plan(make_board(tmp_path))

    # 1.0 + 2 x 0.05 press fit + 0.2 for a printer that prints holes small.
    assert p.bore_diameter_mm == pytest.approx(1.3)
    assert (
        bore_diameter(PIN, {"press_fit_clearance_per_side": 0.0, "hole_oversize": 0.0})
        == 1.0
    )


def test_the_plate_takes_what_room_it_has(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("HEADER", 0, -5, 20, 3, 10.5)])
    p = plan(board)

    # 12 mm top, a 10.5 mm part and 0.5 clearance: 1.0 mm is free, under the 1.5
    # a plate needs.
    assert any("pin is too short" in e for e in p.errors)


def test_a_taller_part_refuses_a_short_pin_and_says_how_short(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("HEADER", 0, -5, 20, 3, 12.0)])
    p = plan(board)

    assert any("tallest part is 12.0 mm, leaving 0.0 mm" in e for e in p.errors)


def test_a_thickness_the_file_gives_must_fit_the_room(tmp_path: Path) -> None:
    board = make_board(tmp_path)

    assert any(
        "only 3.0 mm is free" in e for e in plan(board, plate_thickness_mm=4.0).errors
    )
    assert any(
        "under the printer's" in e for e in plan(board, plate_thickness_mm=1.2).errors
    )
    assert plan(board, plate_thickness_mm=3.0).errors == ()


def test_more_travel_lowers_the_plate(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("HEADER", 0, -5, 20, 3, 6.0)])

    assert plan(board, working_travel_mm=1.0).plate_top_mm == 13.0
    assert plan(board, working_travel_mm=3.0).plate_top_mm == 11.0


def test_a_part_under_the_board_sets_the_nests_depth(tmp_path: Path) -> None:
    under = part("BATTERY", 0, 5, 14, 10, 3.0, z=-4.8)
    p = plan(make_board(tmp_path, components=[under]))

    # It hangs 4.8 mm below the board's top: 3.2 mm under the 1.6 mm board, and a
    # millimetre of room.
    assert p.under_depth_mm == pytest.approx(4.2)


# --- the pins and the parts ---------------------------------------------------------


def test_a_pin_that_lands_on_a_part_is_refused(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("CHIP", -8.0, 14.0, 6, 6, 1.5)])
    p = plan(board)

    assert any("TP1 would land on CHIP" in e for e in p.errors)
    assert not any("TP2" in e for e in p.errors)


def test_a_pin_beside_a_part_is_clear(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("CHIP", -8.0, 14.0, 4, 4, 1.5)])

    # The pad's centre is 2 mm from the chip's centre: inside it. Move the chip.
    assert any("land on CHIP" in e for e in plan(board).errors)

    moved = make_board(tmp_path, components=[part("CHIP", -8.0, 8.0, 4, 4, 1.5)])

    assert plan(moved).errors == ()


def test_a_flat_part_does_not_count(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("PAD", -8.0, 14.0, 6, 6, 0.05)])

    assert plan(board).errors == ()


def test_a_board_described_by_an_envelope_cannot_say_which_pin_lands_on_what(
    tmp_path: Path,
) -> None:
    data = copy.deepcopy(board_template())
    data["test_points"][0]["pad_diameter_mm"] = 3.0
    path = tmp_path / "board.json"
    path.write_text(json.dumps(data))
    board = load_board(path)
    p = plan(board)

    assert p.errors == ()
    assert any("one envelope over the whole board" in w for w in p.warnings)


# --- locating ----------------------------------------------------------------------------


def test_dowels_go_on_ears_at_the_ends_of_the_longer_side(tmp_path: Path) -> None:
    p = plan(make_board(tmp_path))
    first, second = p.anchors

    # The board is 45 mm long (Y): the dowels stand beyond its ends, on the axis.
    assert (first.x_mm, second.x_mm) == (0.0, 0.0)
    assert first.y_mm == pytest.approx(-(22.5 + 0.2 + 2.4 + 2.0))
    assert second.y_mm == pytest.approx(22.5 + 0.2 + 2.4 + 2.0)
    assert first.post_diameter_mm == 3.0
    assert first.socket_diameter_mm == pytest.approx(3.0 + 0.4 + 0.2)
    assert p.anchor_spacing_mm == pytest.approx(2 * 27.1)
    assert {a.kind for a in p.anchors} == {"dowel"}


def test_locating_by_holes_takes_the_farthest_pair(tmp_path: Path) -> None:
    p = plan(make_board(tmp_path), locating="holes")
    first, second = p.anchors

    # Holes at (+-12, +-19): the corners across a diagonal are farthest apart.
    assert math.dist(
        (first.x_mm, first.y_mm), (second.x_mm, second.y_mm)
    ) == pytest.approx(math.hypot(24, 38))
    # A 2.7 mm hole less 0.2 mm each side.
    assert first.post_diameter_mm == pytest.approx(2.3)
    assert {a.kind for a in p.anchors} == {"post"}


def test_holes_too_small_for_a_post_are_refused(tmp_path: Path) -> None:
    board = make_board(tmp_path)
    data = json.loads((tmp_path / "board.json").read_text())
    data["mounting_holes"]["diameter_mm"] = 1.8
    (tmp_path / "board.json").write_text(json.dumps(data))
    p = plan(load_board(tmp_path / "board.json"), locating="holes")

    assert board is not None
    assert any("a post through one would be 1.40 mm" in e for e in p.errors)


def test_a_post_that_would_meet_a_part_under_the_board_is_refused(
    tmp_path: Path,
) -> None:
    under = part("BATTERY", 12.0, 19.0, 6, 6, 3.0, z=-4.8)
    p = plan(make_board(tmp_path, components=[under]), locating="holes")

    assert any("would meet BATTERY under the board" in e for e in p.errors)


def test_locating_by_holes_needs_two(tmp_path: Path) -> None:
    board = make_board(tmp_path)
    data = json.loads((tmp_path / "board.json").read_text())
    del data["mounting_holes"]
    (tmp_path / "board.json").write_text(json.dumps(data))
    p = plan(load_board(tmp_path / "board.json"), locating="holes")

    assert board is not None
    assert any("needs at least two of them" in e for e in p.errors)
    assert p.budgets == {}


# --- the props ---------------------------------------------------------------------------


def test_each_point_is_propped_unless_a_part_sits_under_it(tmp_path: Path) -> None:
    under = part("BATTERY", 8.0, 14.0, 6, 6, 3.0, z=-4.8)
    p = plan(make_board(tmp_path, components=[under]))

    assert p.supports == ((-8.0, 14.0),)
    assert p.unsupported == ("TP2",)
    assert any("not propped under TP2" in w for w in p.warnings)


# --- the budget ----------------------------------------------------------------------------


def test_the_plate_plays_by_a_clearance_between_its_dowels(tmp_path: Path) -> None:
    first = Anchor(0, -27, 3, 3.6, "dowel")
    second = Anchor(0, 27, 3, 3.6, "dowel")

    # On the line between the dowels: one clearance, and no turn to swing it.
    play, spacing = _plate_play((0, 0), (first, second), 0.2)

    assert play == pytest.approx(0.2)
    assert spacing == 54.0

    # Ten millimetres off the line, the turn the two dowels can make adds
    # 2 x 0.2 x 10 / 54.
    off, _ = _plate_play((10, 0), (first, second), 0.2)

    assert off == pytest.approx(0.2 + 2 * 0.2 * 10 / 54)

    # Beyond a dowel, the lever grows: (|1 - t| + |t|) clearances at t = 1.5.
    beyond, _ = _plate_play((0, 54), (first, second), 0.2)

    assert beyond == pytest.approx((abs(1 - 1.5) + 1.5) * 0.2)


def test_the_budget_adds_the_links_and_tilt_follows_the_bore(tmp_path: Path) -> None:
    p = plan(make_board(tmp_path))
    worst = p.worst

    assert worst is not None
    assert worst.board_play_mm == pytest.approx(0.2)
    assert worst.bore_play_mm == pytest.approx(0.05)
    # Turned by two press-fit clearances over a 2 mm bore, over the 10 mm from the
    # plate's underside to the tip; the bore's own play is its offset there, counted once.
    assert worst.tilt_mm == pytest.approx((2 * 0.05 / 2.0) * (12.0 - 2.0))
    assert worst.total_mm == pytest.approx(
        worst.board_play_mm + worst.plate_play_mm + worst.bore_play_mm + worst.tilt_mm
    )
    assert p.worst_point in {"TP1", "TP2"}


def test_a_thicker_plate_tilts_the_pin_less(tmp_path: Path) -> None:
    board = make_board(tmp_path, components=[part("HEADER", 0, -5, 20, 3, 4.0)])
    thin = plan(board, plate_thickness_mm=1.5)
    thick = plan(board, plate_thickness_mm=4.0)

    assert thin.worst is not None and thick.worst is not None
    assert thick.worst.tilt_mm < thin.worst.tilt_mm


def test_a_pad_the_chain_can_miss_is_refused_and_the_largest_link_named(
    tmp_path: Path,
) -> None:
    board = make_board(tmp_path)
    data = json.loads((tmp_path / "board.json").read_text())

    for entry in data["test_points"]:
        entry["pad_diameter_mm"] = 1.5

    (tmp_path / "board.json").write_text(json.dumps(data))
    p = plan(load_board(tmp_path / "board.json"))

    assert board is not None
    assert any("TP1" in e and "can move the tip" in e for e in p.errors)
    assert any("The largest link is the pin tilting in its bore" in e for e in p.errors)
    assert any("pad leaves 0.45 mm" in e for e in p.errors)


def test_the_budget_names_its_largest_link() -> None:
    assert Budget(0.2, 0.3, 0.05, 0.1).largest() == ("the plate on its dowels", 0.3)
    assert Budget(0.5, 0.3, 0.05, 0.1).largest()[0] == "the board in its nest"


def test_the_plan_reports_itself_for_the_record(tmp_path: Path) -> None:
    data = plan(make_board(tmp_path)).to_dict()

    assert data["plate"]["top_mm"] == 12.0
    assert data["misalignment"]["note"].startswith("A worst case")
    assert set(data["per_point_total_mm"]) == {"TP1", "TP2"}
    assert [a["kind"] for a in data["anchors"]] == ["dowel", "dowel"]
