"""Fan bays in a group enclosure, and the heat a row's boards and fans give."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, cast

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.cli.enclosure_group_bays import _bay
from zcad_core.features.enclosure_group import Bay, GroupDesign, build_group_enclosure
from zcad_core.hardware import board_template, get_fan
from zcad_core.hardware.thermal import get_power_figure

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)
FAN = "NOCTUA_NF_A4X10_5V"
BIG_FAN = "NOCTUA_NF_A6X25_5V"


def fan_bay(**more: Any) -> Bay:
    return Bay("fan", fan=FAN, **more)


def inside(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    return bool(cast(cq.Solid, model.val()).isInside(cq.Vector(x, y, z)))


@pytest.fixture(scope="module")
def row() -> Any:
    return build_group_enclosure(("pi5", fan_bay(fan_direction="out"), "pi5"))


# --- the bay --------------------------------------------------------------------------------


def test_a_fan_bay_is_as_wide_as_the_fan_and_a_margin(row: Any) -> None:
    layout = row.bays[1]
    fan = get_fan(FAN)

    assert layout.kind == "fan" and not layout.holds_board
    assert layout.slot_end_mm - layout.slot_start_mm == pytest.approx(fan.size_mm + 6.0)
    assert row.passed, row.checks


def test_the_fan_is_screwed_to_the_lid_over_the_bays_middle(row: Any) -> None:
    layout = row.bays[1]
    fan = get_fan(FAN)
    x = row.design.wall_mm + layout.center_x_mm
    y = layout.center_y_mm
    z = row.cavity_top_z_mm + row.design.lid_mm / 2
    half = fan.hole_spacing_mm / 2

    # A clearance hole through the lid at each of the frame's four holes.
    for dx in (-half, half):
        for dy in (-half, half):
            assert not inside(row.lid, x + dx, y + dy, z)

    # The frame is flat against the lid's inside, as thick as the fan.
    box = row.hardware["bay-1"].BoundingBox()

    assert box.zmax == pytest.approx(row.cavity_top_z_mm)
    assert box.zlen == pytest.approx(fan.thickness_mm)
    assert row.lid_carried == ("bay-1",)


def test_the_fan_report_carries_the_makers_figures_and_their_status(row: Any) -> None:
    (report,) = row.fans

    assert report.direction == "out"
    assert report.power_typical_w == pytest.approx(0.044 * 5.0)
    # The catalog's figures for this fan were read from the maker's page; only
    # the screw is still assumed, and the note says so.
    assert report.datasheet_read is True
    assert "not read from the maker's own page" not in report.to_dict()["note"]
    assert "screw not from a document that was read" in report.to_dict()["note"]


def test_a_hinged_lid_carries_the_fan_with_it() -> None:
    group = build_group_enclosure(
        ("pi5", fan_bay(), "pi5"),
        design=GroupDesign(lid_attachment="hinge", headroom_mm=20.0),
    )

    assert group.passed and group.hinge is not None
    assert group.lid_carried == ("bay-1",)


def test_a_sliding_lid_cannot_carry_a_fan() -> None:
    with pytest.raises(ValueError, match="a fan on the lid needs a hinged or screwed"):
        build_group_enclosure(
            ("pi5", fan_bay(), "pi5"), design=GroupDesign(lid_attachment="slide")
        )


def test_a_row_with_no_fan_bay_has_no_fans(row: Any) -> None:
    plain = build_group_enclosure(("pi5", "pi5"))

    assert plain.fans == () and plain.lid_carried == ()
    assert len(row.fans) == 1


# --- what a fan bay may be ------------------------------------------------------------------


def test_a_fan_bay_needs_a_catalogued_fan_and_a_direction() -> None:
    with pytest.raises(ValueError, match="needs a fan"):
        build_group_enclosure((Bay("fan"),))

    with pytest.raises(ValueError, match="fan must be one of"):
        build_group_enclosure((Bay("fan", fan="NOPE"),))

    with pytest.raises(ValueError, match="fan direction must be one of"):
        build_group_enclosure((fan_bay(fan_direction="sideways"),))

    with pytest.raises(ValueError, match="takes no fan: only a fan bay does"):
        build_group_enclosure((Bay("pi5", fan=FAN),))


def test_a_fan_bay_has_no_board_to_stand_off() -> None:
    with pytest.raises(ValueError, match="a fan bay has no board to stand off"):
        build_group_enclosure((fan_bay(standoff_height_mm=4.0),))


def test_a_fan_thicker_than_the_headroom_is_refused() -> None:
    with pytest.raises(ValueError, match="the fan is 25 mm thick"):
        build_group_enclosure((Bay("fan", fan=BIG_FAN),))

    assert build_group_enclosure((Bay("fan", fan=BIG_FAN, headroom_mm=27.0),)).passed


def test_a_fan_bay_is_written_as_a_fan_and_a_direction() -> None:
    bay = _bay(f"fan:fan={FAN}:direction=out")

    assert bay.kind == "fan" and bay.fan == FAN and bay.fan_direction == "out"


# --- the heat ---------------------------------------------------------------------------------


def write_board(directory: Path, *, power: bool) -> Path:
    data = copy.deepcopy(board_template())
    del data["envelope"]
    data["components"] = []

    if not power:
        del data["power"]

    path = directory / "board.json"
    path.write_text(json.dumps(data))

    return path


def build(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, bays: str
) -> dict[str, Any]:
    capsys.readouterr()
    code = main(
        [
            "enclosure-group",
            "build",
            "--bays",
            bays,
            "--output-directory",
            str(tmp_path / "out"),
            "--printer-profile",
            str(PRINTER_PROFILE),
        ]
    )

    assert code == 0

    return cast(dict[str, Any], json.loads(capsys.readouterr().out))


def test_the_estimate_counts_a_boards_power_and_a_fans(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path, power=True)
    output = build(capsys, tmp_path, f"board:file={board}:align=front,fan:fan={FAN}")
    thermal = output["thermal"]

    # The template board's 0.5 W and the fan's 0.044 A at 5 V.
    assert thermal["typical_w"] == pytest.approx(0.5 + 0.22, abs=0.002)
    assert thermal["complete"] is True
    assert thermal["missing"] == []
    # A fan moves air, so the box is not closed.
    assert thermal["closed"] is False
    assert [f["model"] for f in output["fans"]] == ["Noctua NF-A4x10 5V"]
    # Its figures were read from the maker's page, so no warning about them.
    assert not any(
        "not read from the maker's own page" in w for w in output["warnings"]
    )


def test_a_pi_and_a_fan_are_both_counted(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    output = build(capsys, tmp_path, f"pi5,fan:fan={FAN}")
    pi = get_power_figure("RASPBERRY_PI_5")

    assert pi is not None
    assert output["thermal"]["typical_w"] == pytest.approx(
        pi.typical_w + 0.22, abs=0.002
    )


def test_a_board_with_no_power_section_is_counted_as_unknown(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path, power=False)
    output = build(capsys, tmp_path, f"pi5,board:file={board}:align=front")

    assert output["thermal"]["complete"] is False
    assert output["thermal"]["missing"] == [
        "RASPBERRY_PI_5:active-cooler-fan",
        "EXAMPLE_BOARD",
    ]
    assert output["thermal"]["status"] == "lower_bound"


def test_a_row_of_one_board_with_nothing_to_move_air_is_closed(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    board = write_board(tmp_path, power=True)
    closed = build(capsys, tmp_path, f"board:file={board}")

    assert closed["thermal"]["closed"] is True
