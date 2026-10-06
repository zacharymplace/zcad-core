"""Reading a KiCad PCB's test points into a board file.

As in ``test_kicad_import``, the boards are written by hand to the format's
documented tokens. A test pad away from its footprint's origin in a turned or
bottom-side footprint pins what the reader assumes of KiCad, so the import
marks it for review.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.hardware import check_board_data
from zcad_core.hardware.electronics.kicad_import import import_kicad

# The board is 30 x 40 mm, its top left corner at (100, 50) in KiCad's frame,
# where Y points down; the centre (115, 70) is the board file's origin.
X0, Y0, X1, Y1 = 100.0, 50.0, 130.0, 90.0
CONNECTOR = {
    "identifier": "USB_C",
    "edge": "negative_y",
    "width_mm": 9.0,
    "height_mm": 3.3,
    "depth_mm": 7.5,
    "center_offset_mm": 0.0,
    "bottom_offset_from_board_top_mm": 0.0,
}


def line(x0: float, y0: float, x1: float, y1: float) -> str:
    return (
        f'(gr_line (start {x0} {y0}) (end {x1} {y1}) (layer "Edge.Cuts") '
        "(stroke (width 0.05) (type default)))"
    )


OUTLINE = "\n".join(
    [line(X0, Y0, X1, Y0), line(X1, Y0, X1, Y1), line(X1, Y1, X0, Y1)]
    + [line(X0, Y1, X0, Y0)]
)


def pad(
    *,
    shape: str = "circle",
    size: tuple[float, float] = (1.5, 1.5),
    offset: tuple[float, float] = (0, 0),
    net: str = '(net 3 "3V3")',
    layer: str = "F.Cu",
) -> str:
    return (
        f'(pad "1" smd {shape} (at {offset[0]} {offset[1]}) '
        f'(size {size[0]} {size[1]}) (layers "{layer}" "{layer[0]}.Mask") {net})'
    )


def footprint(
    reference: str,
    x: float,
    y: float,
    *pads: str,
    name: str = "TestPoint:TestPoint_Pad_D1.5mm",
    layer: str = "F.Cu",
    angle: float = 0,
) -> str:
    at = f"{x} {y}" + (f" {angle}" if angle else "")

    return (
        f'(footprint "{name}" (layer "{layer}") (at {at}) '
        f'(property "Reference" "{reference}") {" ".join(pads or (pad(),))})'
    )


def read(tmp_path: Path, body: str, **options: Any) -> Any:
    path = tmp_path / "board.kicad_pcb"
    path.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew") '
        f"(general (thickness 1.6))\n{OUTLINE}\n{body}\n)\n",
        encoding="utf-8",
    )

    return import_kicad(path, **options)


def settled(data: dict[str, Any]) -> dict[str, Any]:
    """The file once its cable connector is set by hand."""

    done = {key: value for key, value in data.items() if key != "needs_review"}
    done["cable_connector"] = CONNECTOR

    return done


def test_a_test_pad_is_a_test_point_with_its_side_and_net(tmp_path: Path) -> None:
    # 10 mm left of and 10 mm above the centre in KiCad, where Y points down.
    imported = read(tmp_path, footprint("TP1", 105, 60))

    assert imported.data["test_points"] == [
        {
            "identifier": "TP1",
            "x_mm": -10.0,
            "y_mm": 10.0,
            "pad_diameter_mm": 1.5,
            "side": "top",
            "net": "3V3",
        }
    ]
    assert imported.report["test_points"] == {"top": 1, "bottom": 0, "not_read": []}
    assert "components" not in imported.data

    result = check_board_data(settled(imported.data))

    assert result.valid, result.errors


def test_a_back_side_test_point_is_on_the_bottom(tmp_path: Path) -> None:
    imported = read(
        tmp_path,
        footprint("TP2", 120, 80, pad(layer="B.Cu"), layer="B.Cu"),
    )
    (point,) = imported.data["test_points"]

    assert (point["side"], point["x_mm"], point["y_mm"]) == ("bottom", 5.0, -10.0)
    # A pad at its footprint's origin does not depend on the mirror.
    assert imported.report["unverified_transforms"] == []


def test_a_pad_off_its_turned_footprints_origin_needs_review(tmp_path: Path) -> None:
    imported = read(tmp_path, footprint("TP3", 115, 70, pad(offset=(2, 0)), angle=90))
    (point,) = imported.data["test_points"]

    # Counter-clockwise on screen, as phase 1 assumes: +X turns to KiCad's -Y,
    # which is the board file's +Y.
    assert (point["x_mm"], point["y_mm"]) == pytest.approx((0.0, 2.0))
    assert imported.report["unverified_transforms"] == [
        "TP3: a test pad at (2, 0) in a footprint at angle 90"
    ]
    assert any(
        item.startswith("footprint_transforms")
        for item in imported.data["needs_review"]
    )


def test_a_pad_not_round_is_its_smaller_side_with_a_warning(tmp_path: Path) -> None:
    imported = read(
        tmp_path, footprint("TP4", 115, 70, pad(shape="rect", size=(1.0, 2.0)))
    )

    assert imported.data["test_points"][0]["pad_diameter_mm"] == 1.0
    assert any(
        "TP4 has a rect 1 x 2 mm pad" in note for note in imported.report["notes"]
    )


@pytest.mark.parametrize(
    ("net", "name"),
    [('(net 3 "3V3")', "3V3"), ('(net "GND")', "GND"), ("", "")],
)
def test_the_net_is_read_in_either_form_or_left_empty(
    tmp_path: Path, net: str, name: str
) -> None:
    imported = read(tmp_path, footprint("TP5", 115, 70, pad(net=net)))

    assert imported.data["test_points"][0]["net"] == name


def test_a_tp_reference_or_a_named_footprint_is_a_test_point_not_a_part(
    tmp_path: Path,
) -> None:
    body = footprint("TP6", 105, 60, name="Connector_Pin:Pin_D1.0mm") + footprint(
        "J5", 125, 80, name="Connector_Pin:Pin_D1.3mm"
    )
    imported = read(
        tmp_path,
        body,
        test_points=["J5"],
        default_height_mm=2.0,
        default_height_source="measured",
    )

    assert [point["identifier"] for point in imported.data["test_points"]] == [
        "TP6",
        "J5",
    ]
    assert imported.report["parts"] is None

    unnamed = read(
        tmp_path, body, default_height_mm=2.0, default_height_source="measured"
    )

    assert [box["identifier"] for box in unnamed.data["components"]] == ["J5"]


def test_naming_a_reference_the_file_does_not_have_is_refused(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="names TP99, which the file does not"):
        read(tmp_path, footprint("TP1", 105, 60), test_points=["TP99"])


def test_a_test_point_of_two_pads_is_listed_not_read(tmp_path: Path) -> None:
    imported = read(
        tmp_path,
        footprint("TP7", 115, 70, pad(offset=(-1, 0)), pad(offset=(1, 0))),
    )

    assert "test_points" not in imported.data
    assert imported.report["test_points"]["not_read"] == [
        {"reference": "TP7", "why": "2 copper pads, not one: give it by hand"}
    ]


def test_the_board_file_check_refuses_what_a_fixture_cannot_probe(
    tmp_path: Path,
) -> None:
    body = (
        footprint("TP1", 115, 70, pad(size=(0.4, 0.4)))
        + footprint("TP2", 120, 60)
        + footprint("TP3", 121, 60)
        + footprint("TP4", 100.2, 70)
    )
    errors = " ".join(check_board_data(settled(read(tmp_path, body).data)).errors)

    assert "pad_diameter_mm is 0.4, outside 0.5" in errors
    assert "Test points TP2 and TP3 overlap" in errors
    assert "Test point TP4" in errors
    assert "not wholly on the board" in errors


def test_the_command_reads_named_test_points(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "board.kicad_pcb"
    source.write_text(
        '(kicad_pcb (version 20240108) (generator "pcbnew") '
        f"(general (thickness 1.6))\n{OUTLINE}\n"
        + footprint("TP1", 105, 60)
        + footprint("J5", 125, 80, name="Connector_Pin:Pin_D1.3mm")
        + "\n)\n",
        encoding="utf-8",
    )
    output = tmp_path / "board.json"
    code = main(
        [
            "board",
            "import",
            "--kicad",
            str(source),
            "--output",
            str(output),
            "--test-points",
            "J5, ",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["test_points"]["top"] == 2
    assert [p["identifier"] for p in json.loads(output.read_text())["test_points"]] == [
        "TP1",
        "J5",
    ]


def test_a_step_import_refuses_test_points(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code = main(
        [
            "board",
            "import",
            "--step",
            str(tmp_path / "x.step"),
            "--output",
            str(tmp_path / "c.json"),
            "--test-points",
            "TP1",
        ]
    )

    assert code == 1
    assert "--test-points is for a KiCad file" in capsys.readouterr().err
