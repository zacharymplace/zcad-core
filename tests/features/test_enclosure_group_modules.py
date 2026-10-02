"""A group enclosure's bays as modules: a Pi 5 as before, and a board from a board
file standing in the row."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.cli.enclosure_group import _bay
from zcad_core.features.enclosure_group import Bay, GroupDesign, build_group_enclosure
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.features.enclosure_group_modules import (
    board_module,
    default_rotation,
    pi_module,
    turn_point,
)
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import (
    board_template,
    get_raspberry_pi5,
    load_board,
)
from zcad_core.hardware.electronics.board_file import BoardFileSpec

PI = get_raspberry_pi5()
PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def write_board(directory: Path, **changes: Any) -> Path:
    """A 30 x 45 board with four 2.7 mm holes, a USB-C connector on its front
    edge, and a 3 mm part, changed by ``changes`` (a key set to ``None`` goes)."""

    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = [
        {
            "identifier": "CHIP",
            "center_x_mm": 0.0,
            "center_y_mm": 5.0,
            "width_mm": 8.0,
            "depth_mm": 8.0,
            "height_mm": 3.0,
            "bottom_offset_from_board_top_mm": 0.0,
        }
    ]

    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value

    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


@pytest.fixture(scope="module")
def board(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(write_board(tmp_path_factory.mktemp("board")))


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, model.val()).isInside(cq.Vector(x, y, z)))


# --- the modules ------------------------------------------------------------------------


def test_a_pi_is_a_module_with_its_own_holes_and_standoff_floor() -> None:
    module = pi_module(PI)

    assert module.is_pi
    assert (module.width_mm, module.depth_mm) == (PI.board_width_mm, PI.board_length_mm)
    assert module.holes == PI.mounting_hole_positions_mm
    assert module.standoff_screw == "M2.5"
    assert module.minimum_standoff_mm == pytest.approx(
        PI.sd_card_depth_below_board_mm + 0.4
    )
    assert module.openings == ()


def test_a_board_is_turned_so_its_longer_side_runs_front_to_back(
    board: BoardFileSpec, tmp_path: Path
) -> None:
    assert default_rotation(board) == 0
    module = board_module(board)

    assert (module.width_mm, module.depth_mm) == (30.0, 45.0)

    # With its connector on the left edge, a quarter turn faces it to the front.
    sideways = load_board(
        write_board(
            tmp_path,
            cable_connector={
                "identifier": "USB_C",
                "edge": "negative_x",
                "width_mm": 9.0,
                "height_mm": 3.3,
                "depth_mm": 7.5,
                "center_offset_mm": 0.0,
                "bottom_offset_from_board_top_mm": 0.0,
            },
        )
    )
    wide = board_module(sideways, rotate=90)

    assert (wide.width_mm, wide.depth_mm) == (45.0, 30.0)
    # A quarter turn takes the hole at (-12, -19) to (19, -12).
    assert wide.holes[0] == pytest.approx((19.0, -12.0))
    assert [o.wall for o in wide.openings] == ["negative_y"]


@pytest.mark.parametrize(
    ("rotate", "point", "expected"),
    [
        (0, (3.0, 4.0), (3.0, 4.0)),
        (90, (3.0, 4.0), (-4.0, 3.0)),
        (180, (3.0, 4.0), (-3.0, -4.0)),
        (270, (3.0, 4.0), (4.0, -3.0)),
    ],
)
def test_a_turn_is_counterclockwise_seen_from_above(
    rotate: int, point: tuple[float, float], expected: tuple[float, float]
) -> None:
    assert turn_point(point, rotate) == expected


def test_a_board_that_is_wider_than_it_is_long_is_turned_by_default(
    tmp_path: Path,
) -> None:
    wide = load_board(
        write_board(
            tmp_path,
            board={"width_mm": 60.0, "length_mm": 30.0, "thickness_mm": 1.6},
            mounting_holes={
                "diameter_mm": 2.7,
                "positions_mm": [[-25.0, -10.0], [25.0, -10.0], [-25.0, 10.0]],
            },
            cable_connector={
                "identifier": "USB_C",
                "edge": "positive_x",
                "width_mm": 9.0,
                "height_mm": 3.3,
                "depth_mm": 7.5,
                "center_offset_mm": 0.0,
                "bottom_offset_from_board_top_mm": 0.0,
            },
            components=[],
        )
    )

    assert default_rotation(wide) == 90
    module = board_module(wide)

    assert (module.width_mm, module.depth_mm) == (30.0, 60.0)
    # Turned a quarter, its +X edge is the back wall.
    assert [o.wall for o in module.openings] == ["positive_y"]


def test_the_standoff_screw_is_the_largest_the_holes_pass(
    board: BoardFileSpec, tmp_path: Path
) -> None:
    assert board_module(board).standoff_screw == "M2.5"

    big = load_board(
        write_board(
            tmp_path,
            mounting_holes={
                "diameter_mm": 3.2,
                "positions_mm": [[-12.0, -19.0], [12.0, -19.0]],
            },
        )
    )

    assert board_module(big).standoff_screw == "M3"
    assert board_module(big, screw="M2").standoff_screw == "M2"

    with pytest.raises(ValueError, match="wider than the board's"):
        board_module(board, screw="M4")

    with pytest.raises(ValueError, match="screw must be one of"):
        board_module(board, screw="M9")


def test_a_turn_takes_the_connector_to_the_wall_or_the_side_it_then_faces(
    board: BoardFileSpec,
) -> None:
    # The USB-C is on the front edge.
    assert [o.wall for o in board_module(board).openings] == ["negative_y"]
    assert [o.wall for o in board_module(board, rotate=180).openings] == ["positive_y"]
    assert board_module(board, rotate=90).openings == ()
    assert board_module(board, rotate=270).openings == ()


def test_a_part_marked_as_reached_through_an_edge_gets_an_opening(
    tmp_path: Path,
) -> None:
    jack = load_board(
        write_board(
            tmp_path,
            components=[
                {
                    "identifier": "JACK",
                    "center_x_mm": -8.0,
                    "center_y_mm": 18.0,
                    "width_mm": 9.0,
                    "depth_mm": 12.0,
                    "height_mm": 11.0,
                    "bottom_offset_from_board_top_mm": 0.0,
                    "access_edge": "positive_y",
                }
            ],
        )
    )
    module = board_module(jack)
    ports = {o.label: o for o in module.openings}

    assert ports["JACK"].wall == "positive_y"
    assert ports["JACK"].along_mm == pytest.approx(-8.0)
    assert ports["JACK"].width_mm == 9.0 and ports["JACK"].height_mm == 11.0
    assert module.tallest_mm == 11.0


def test_parts_under_the_board_set_a_floor_for_its_standoffs(tmp_path: Path) -> None:
    under = load_board(
        write_board(
            tmp_path,
            components=[
                {
                    "identifier": "CARD",
                    "center_x_mm": 0.0,
                    "center_y_mm": 0.0,
                    "width_mm": 10.0,
                    "depth_mm": 10.0,
                    "height_mm": 2.0,
                    "bottom_offset_from_board_top_mm": -4.6,
                }
            ],
        )
    )

    # The card's underside is 3.0 mm below the board's (4.6 less its 1.6 mm).
    assert board_module(under).minimum_standoff_mm == pytest.approx(3.4)


# --- the row ---------------------------------------------------------------------------


def test_a_board_bay_builds_and_passes_its_checks(board: BoardFileSpec) -> None:
    group = build_group_enclosure((Bay("board", board=board),))

    assert group.passed, group.checks
    assert not group.part_collisions
    assert set(group.hardware) == {"bay-0"}
    # The board's standoff height is the board file's own recommendation.
    assert group.bays[0].standoff_height_mm == board.recommended_standoff_height_mm


def test_a_board_stands_on_standoffs_at_its_mounting_holes(
    board: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=board),))
    layout = group.bays[0]
    wall = group.design.wall_mm
    height = layout.board_bottom_z_mm - 0.5

    for hx, hy in board.mounting_hole_positions_mm or ():
        # Two millimetres off the hole's axis, in the standoff's wall: the screw's
        # pilot hole is empty.
        assert inside(
            group.base,
            wall + layout.center_x_mm + hx + 2.0,
            layout.center_y_mm + hy,
            height,
        )
        assert not inside(
            group.base, wall + layout.center_x_mm + hx, layout.center_y_mm + hy, height
        )

    # And not under the middle of the board.
    assert not inside(group.base, wall + layout.center_x_mm, layout.center_y_mm, height)


def test_a_board_bay_is_as_deep_as_its_board_and_a_row_as_deep_as_its_deepest(
    board: BoardFileSpec,
) -> None:
    alone = build_group_enclosure((Bay("board", board=board),))
    design = alone.design

    assert alone.inner_size_mm[1] == pytest.approx(
        design.front_clearance_mm + 45.0 + design.back_clearance_mm
    )

    mixed = build_group_enclosure(("pi5", Bay("board", board=board, align="front")))

    assert mixed.inner_size_mm[1] == pytest.approx(
        design.front_clearance_mm + PI.board_length_mm + design.back_clearance_mm
    )


def test_a_shallow_board_sits_where_it_is_aligned(board: BoardFileSpec) -> None:
    front = build_group_enclosure(("pi5", Bay("board", board=board, align="front")))
    design = front.design

    # The Pi is the deepest, so it fills the row; the board is against the front
    # wall.
    assert front.bays[1].center_y_mm == pytest.approx(
        design.wall_mm + design.front_clearance_mm + 45.0 / 2
    )
    assert front.pi_center_y_mm == pytest.approx(front.bays[0].center_y_mm)


def test_the_deepest_board_is_in_the_same_place_however_it_is_aligned(
    board: BoardFileSpec,
) -> None:
    places = {
        align: build_group_enclosure((Bay("board", board=board, align=align),))
        .bays[0]
        .center_y_mm
        for align in ("front", "center", "back")
    }

    assert places["front"] == pytest.approx(places["center"])
    assert places["center"] == pytest.approx(places["back"])


def test_a_connector_too_far_from_its_wall_is_refused(board: BoardFileSpec) -> None:
    # Against the back wall, the front-edge connector is 40 mm from the front.
    with pytest.raises(ValueError, match=r"USB_C is at the front edge.*align="):
        build_group_enclosure(("pi5", Bay("board", board=board)))


def test_the_connectors_opening_is_cut_through_its_wall(board: BoardFileSpec) -> None:
    group = build_group_enclosure(("pi5", Bay("board", board=board, align="front")))
    layout = group.bays[1]
    x = group.design.wall_mm + layout.center_x_mm

    # The USB-C opening in the front wall, and wall either side of it.
    assert not inside(group.base, x, 1.0, layout.board_top_z_mm + 1.0)
    assert inside(group.base, x + 12.0, 1.0, layout.board_top_z_mm + 1.0)


def test_the_boards_envelope_is_the_hardware_the_checks_clear(
    board: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=board),))
    envelope = group.hardware["bay-0"]
    box = envelope.BoundingBox()
    layout = group.bays[0]

    assert box.zmax == pytest.approx(layout.board_top_z_mm + 3.0)
    assert box.zmin == pytest.approx(layout.board_bottom_z_mm)
    assert intersection_volume(envelope, cast(cq.Shape, group.base.val())) < 1e-6


def test_a_board_part_taller_than_the_headroom_is_refused(tmp_path: Path) -> None:
    tall = load_board(
        write_board(
            tmp_path,
            components=[
                {
                    "identifier": "TOWER",
                    "center_x_mm": 0.0,
                    "center_y_mm": 5.0,
                    "width_mm": 6.0,
                    "depth_mm": 6.0,
                    "height_mm": 20.0,
                    "bottom_offset_from_board_top_mm": 0.0,
                }
            ],
        )
    )

    with pytest.raises(
        ValueError, match="headroom_mm is 18 mm but the board's tallest"
    ):
        build_group_enclosure((Bay("board", board=tall),))

    group = build_group_enclosure((Bay("board", board=tall, headroom_mm=21.0),))

    assert group.passed


def test_a_standoff_too_low_for_what_is_under_the_board_is_refused(
    tmp_path: Path,
) -> None:
    under = load_board(
        write_board(
            tmp_path,
            components=[
                {
                    "identifier": "CARD",
                    "center_x_mm": 0.0,
                    "center_y_mm": 0.0,
                    "width_mm": 10.0,
                    "depth_mm": 10.0,
                    "height_mm": 2.0,
                    "bottom_offset_from_board_top_mm": -4.6,
                }
            ],
        )
    )

    with pytest.raises(
        ValueError, match="at least 3.4 mm so the parts under the board"
    ):
        build_group_enclosure((Bay("board", board=under, standoff_height_mm=3.0),))

    assert build_group_enclosure(
        (Bay("board", board=under, standoff_height_mm=4.0),)
    ).passed


def test_a_divider_beside_a_board_bay_notches_at_its_centre(
    board: BoardFileSpec,
) -> None:
    group = build_group_enclosure(
        ("pi5", Bay("board", board=board, align="front", divider=Divider(notch=True)))
    )
    layout = group.bays[1]
    x = group.design.wall_mm + layout.divider_start_mm + 1.0

    # The notch is centred on the board bay's own centre, rising from its board.
    assert not inside(group.base, x, layout.center_y_mm, layout.board_top_z_mm + 3.0)
    assert inside(group.base, x, layout.center_y_mm + 20.0, layout.board_top_z_mm + 3.0)


def test_a_lid_that_hinges_sweeps_a_board_bays_envelope(board: BoardFileSpec) -> None:
    group = build_group_enclosure(
        (Bay("board", board=board), Bay("board", board=board, rotate=180)),
        design=GroupDesign(lid_attachment="hinge", headroom_mm=20.0),
    )

    assert group.passed and group.hinge is not None


# --- what a bay may be ---------------------------------------------------------------


def test_a_board_bay_needs_a_board_and_no_other_bay_takes_one(
    board: BoardFileSpec,
) -> None:
    with pytest.raises(ValueError, match="needs a board file"):
        build_group_enclosure((Bay("board"),))

    with pytest.raises(ValueError, match="takes no board, rotate or screw"):
        build_group_enclosure((Bay("pi5", board=board),))

    with pytest.raises(ValueError, match="takes no board, rotate or screw"):
        build_group_enclosure((Bay("open", rotate=90),))

    with pytest.raises(ValueError, match="rotate must be one of"):
        build_group_enclosure((Bay("board", board=board, rotate=45),))

    with pytest.raises(ValueError, match="align must be one of"):
        build_group_enclosure((Bay("board", board=board, align="left"),))


# --- the command line -------------------------------------------------------------------


def test_a_board_bay_is_written_as_a_board_file_and_its_settings(
    tmp_path: Path,
) -> None:
    path = write_board(tmp_path)
    bay = _bay(f"board:file={path}:rotate=180:align=front:screw=M2.5:headroom=12")

    assert bay.kind == "board" and bay.board is not None
    assert bay.rotate == 180 and bay.align == "front" and bay.screw == "M2.5"
    assert bay.headroom_mm == 12.0

    with pytest.raises(ValueError, match="rotate must be 0, 90, 180 or 270"):
        _bay(f"board:file={path}:rotate=ninety")

    with pytest.raises(ValueError, match="bay option must be"):
        _bay("board:colour=red")


def test_the_command_builds_a_row_with_a_board_in_it(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = write_board(tmp_path)
    exit_code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            f"pi5,board:file={path}:align=front",
            "--output-directory",
            str(tmp_path / "out"),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["validation_status"] == "PASS"
    assert output["bays"] == ["pi5", "board"]
    assert any("counts only the Pi bays" in w for w in output["warnings"])
    assert Path(output["review_step"]).is_file()


# --- service spaces for connectors on the sides ------------------------------------------


def connector(edge: str) -> dict[str, Any]:
    return {
        "identifier": "USB_C",
        "edge": edge,
        "width_mm": 9.0,
        "height_mm": 3.3,
        "depth_mm": 7.5,
        "center_offset_mm": 0.0,
        "bottom_offset_from_board_top_mm": 0.0,
    }


@pytest.fixture(scope="module")
def right_facing(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(
        write_board(
            tmp_path_factory.mktemp("right"), cable_connector=connector("positive_x")
        )
    )


@pytest.fixture(scope="module")
def left_facing(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(
        write_board(
            tmp_path_factory.mktemp("left"), cable_connector=connector("negative_x")
        )
    )


def test_a_connector_on_a_side_is_a_service_space_not_a_wall_opening(
    board: BoardFileSpec, right_facing: BoardFileSpec, left_facing: BoardFileSpec
) -> None:
    right, left = board_module(right_facing), board_module(left_facing)

    assert right.faces_right and not right.faces_left
    assert left.faces_left and not left.faces_right
    assert right.openings == () and left.openings == ()
    assert [p.label for p in right.side_ports] == ["USB_C"]
    # A quarter turn takes the front-edge connector to the right.
    assert board_module(board, rotate=90).faces_right
    assert board_module(board, rotate=270).faces_left


def test_a_right_facing_connector_takes_the_service_gap_a_pi_takes(
    right_facing: BoardFileSpec, board: BoardFileSpec
) -> None:
    group = build_group_enclosure((Bay("board", board=right_facing),))
    plain = build_group_enclosure((Bay("board", board=board, align="front"),))
    layout = group.bays[0]

    assert group.passed, group.checks
    assert layout.gap_end_mm - layout.gap_start_mm == group.design.service_gap_mm
    assert plain.bays[0].gap_end_mm - plain.bays[0].gap_start_mm == (
        group.design.board_gap_mm
    )


def test_the_cable_leaves_by_an_opening_in_the_front_wall_at_the_gaps_end(
    right_facing: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=right_facing),))
    layout = group.bays[0]
    wall = group.design.wall_mm
    z = layout.board_top_z_mm + 1.0
    middle = wall + (layout.gap_start_mm + layout.gap_end_mm) / 2

    assert not inside(group.base, middle, 1.0, z)
    # The wall stands in front of the slot.
    assert inside(group.base, wall + layout.center_x_mm, 1.0, z)


def test_a_left_facing_connector_takes_a_service_space_before_its_slot(
    left_facing: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=left_facing),))
    layout = group.bays[0]
    design = group.design

    assert group.passed, group.checks
    assert layout.left_space_mm == design.service_gap_mm
    # The first bay: the end margin, then the space, then the slot.
    assert layout.slot_start_mm == pytest.approx(
        design.end_margin_mm + design.service_gap_mm
    )

    wall = design.wall_mm
    middle = wall + layout.slot_start_mm - layout.left_space_mm / 2

    assert not inside(group.base, middle, 1.0, layout.board_top_z_mm + 1.0)


def test_a_row_of_boards_facing_each_other_builds(
    right_facing: BoardFileSpec, left_facing: BoardFileSpec
) -> None:
    group = build_group_enclosure(
        (
            Bay("board", board=right_facing),
            Bay("board", board=left_facing, divider=Divider(notch=True)),
        )
    )
    first, second = group.bays

    assert group.passed, group.checks
    # Their spaces are separate: the first's gap, a divider, then the second's own.
    assert second.left_space_mm == group.design.service_gap_mm
    assert second.slot_start_mm - second.left_space_mm >= first.gap_end_mm


def test_a_service_space_too_small_for_the_cable_is_refused(
    right_facing: BoardFileSpec,
) -> None:
    with pytest.raises(ValueError, match="service space leaves"):
        build_group_enclosure(
            (Bay("board", board=right_facing),), design=GroupDesign(service_gap_mm=14.0)
        )


# --- lid vents over a board's parts ------------------------------------------------------


@pytest.fixture(scope="module")
def vented(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(
        write_board(
            tmp_path_factory.mktemp("vented"),
            components=[
                {
                    "identifier": "SOC",
                    "center_x_mm": 4.0,
                    "center_y_mm": -3.0,
                    "width_mm": 10.0,
                    "depth_mm": 10.0,
                    "height_mm": 3.0,
                    "bottom_offset_from_board_top_mm": 0.0,
                    "lid_vent": True,
                }
            ],
        )
    )


def test_a_part_that_draws_air_from_above_gets_slots_in_the_lid(
    vented: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=vented, align="front"),))
    layout = group.bays[0]
    x = group.design.wall_mm + layout.center_x_mm + 4.0
    y = layout.center_y_mm - 3.0
    z = group.cavity_top_z_mm + group.design.lid_mm / 2

    # The middle slot is open over the part, and the lid is solid beside it.
    assert not inside(group.lid, x, y, z)
    assert inside(group.lid, x, y + 2.5, z)

    closed = build_group_enclosure(
        (Bay("board", board=vented, align="front"),), design=GroupDesign(vents=False)
    )

    assert inside(closed.lid, x, y, z)


# --- a cradle for a board with no mounting holes ----------------------------------------


@pytest.fixture(scope="module")
def holeless(tmp_path_factory: pytest.TempPathFactory) -> BoardFileSpec:
    return load_board(
        write_board(tmp_path_factory.mktemp("holeless"), mounting_holes=None)
    )


def test_a_board_with_no_holes_stands_in_a_cradle(holeless: BoardFileSpec) -> None:
    module = board_module(holeless)

    assert module.support == "cradle"
    assert module.holes == () and module.standoff_screw == ""
    assert module.connector_wall == "negative_y"


def test_a_cradle_bay_builds_with_a_ledge_under_the_boards_edge(
    holeless: BoardFileSpec,
) -> None:
    group = build_group_enclosure((Bay("board", board=holeless, align="front"),))
    layout = group.bays[0]
    x = group.design.wall_mm + layout.center_x_mm
    z = layout.board_bottom_z_mm - 0.3

    assert group.passed, group.checks
    assert not group.part_collisions
    # The ledge runs 1 mm in under each side edge, and the middle is open.
    # (off the middle of the side, where the snap clip's slot is)
    assert inside(group.base, x + 14.5, layout.center_y_mm + 8.0, z)
    assert not inside(group.base, x + 13.0, layout.center_y_mm + 8.0, z)
    assert not inside(group.base, x, layout.center_y_mm, z)


def test_a_cradle_follows_a_rounded_outline(tmp_path: Path) -> None:
    rounded = load_board(
        write_board(
            tmp_path,
            mounting_holes=None,
            outline={"type": "rounded_rectangle", "radius_mm": 5.0},
        )
    )
    module = board_module(rounded)

    assert module.outline is not None and len(module.outline) > 4
    assert build_group_enclosure((Bay("board", board=rounded, align="front"),)).passed


def test_a_cradle_bay_takes_no_divider_and_no_screw(holeless: BoardFileSpec) -> None:
    with pytest.raises(ValueError, match="side clips would meet its divider"):
        build_group_enclosure(
            ("pi5", Bay("board", board=holeless, align="front", divider=Divider()))
        )

    with pytest.raises(ValueError, match="stands in a cradle, which takes no screw"):
        board_module(holeless, screw="M2.5")


def test_a_board_with_no_parts_listed_builds(tmp_path: Path) -> None:
    bare = load_board(write_board(tmp_path, components=[]))
    group = build_group_enclosure((Bay("board", board=bare, align="front"),))

    assert group.passed and not group.part_collisions
