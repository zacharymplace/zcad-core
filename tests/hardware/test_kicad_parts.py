"""Reading a KiCad PCB's footprints as a board file's parts.

As in ``test_kicad_import``, the boards are written by hand to the format's
documented tokens. A turned or bottom-side footprint's place pins what the
reader assumes of KiCad, not what KiCad does, so the import marks it for review.
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
SOURCE = "datasheet, p. 4"


def line(x0: float, y0: float, x1: float, y1: float) -> str:
    return (
        f'(gr_line (start {x0} {y0}) (end {x1} {y1}) (layer "Edge.Cuts") '
        "(stroke (width 0.05) (type default)))"
    )


OUTLINE = "\n".join(
    [line(X0, Y0, X1, Y0), line(X1, Y0, X1, Y1), line(X1, Y1, X0, Y1)]
    + [line(X0, Y1, X0, Y0)]
)


def part(
    reference: str,
    x: float,
    y: float,
    *,
    size: tuple[float, float] | None = (3.0, 1.5),
    angle: float = 0,
    layer: str = "F.Cu",
    name: str = "Resistor_SMD:R_0603_1608Metric",
    attr: str = "smd",
) -> str:
    """A footprint with a courtyard of ``size`` about its origin, and two pads."""

    at = f"{x} {y}" + (f" {angle}" if angle else "")
    side = "B" if layer == "B.Cu" else "F"
    courtyard = ""

    if size is not None:
        w, d = size[0] / 2, size[1] / 2
        courtyard = (
            f'(fp_rect (start {-w} {-d}) (end {w} {d}) (layer "{side}.CrtYd") '
            "(stroke (width 0.05) (type default)))"
        )

    return (
        f'(footprint "{name}" (layer "{layer}") (at {at}) (attr {attr}) '
        f'(property "Reference" "{reference}") {courtyard} '
        f'(pad "1" smd rect (at -0.8 0) (size 0.8 0.9) (layers "{side}.Cu")) '
        f'(pad "2" smd rect (at 0.8 0) (size 0.8 0.9) (layers "{side}.Cu")))'
    )


def mounting_hole(reference: str, x: float, y: float) -> str:
    return (
        f'(footprint "MountingHole:MountingHole_2.7mm_M3" (layer "F.Cu") '
        f'(at {x} {y}) (property "Reference" "{reference}") '
        '(pad "" np_thru_hole circle (at 0 0) (size 2.7 2.7) (drill 2.7) '
        '(layers "*.Cu" "*.Mask")))'
    )


def pcb(body: str) -> str:
    return (
        '(kicad_pcb (version 20240108) (generator "pcbnew") '
        f"(general (thickness 1.6))\n{OUTLINE}\n{body}\n)\n"
    )


def write_heights(tmp_path: Path, heights: dict[str, Any]) -> Path:
    path = tmp_path / "heights.json"
    path.write_text(json.dumps(heights), encoding="utf-8")

    return path


def read(
    tmp_path: Path,
    body: str,
    heights: dict[str, Any] | None = None,
    **options: Any,
) -> Any:
    path = tmp_path / "board.kicad_pcb"
    path.write_text(pcb(body), encoding="utf-8")

    if heights is not None:
        options["heights_file"] = write_heights(tmp_path, heights)

    return import_kicad(path, **options)


def height(mm: float, source: str = SOURCE) -> dict[str, Any]:
    return {"height_mm": mm, "source": source}


def review(imported: Any) -> list[str]:
    return [item.split(":")[0] for item in imported.data.get("needs_review", [])]


def test_a_front_part_is_a_box_on_the_board_from_its_courtyard(
    tmp_path: Path,
) -> None:
    # 10 mm left of and 10 mm above the centre in KiCad, where Y points down.
    imported = read(tmp_path, part("R1", 105, 60), {"R1": height(0.6)})

    assert imported.data["components"] == [
        {
            "identifier": "R1",
            "center_x_mm": -10.0,
            "center_y_mm": 10.0,
            "width_mm": 3.0,
            "depth_mm": 1.5,
            "bottom_offset_from_board_top_mm": 0.0,
            "height_mm": 0.6,
            "access_edge": None,
        }
    ]
    assert "envelope" not in imported.data
    assert review(imported) == ["cable_connector"]
    assert imported.report["parts"]["heights"] == [
        {
            "reference": "R1",
            "height_mm": 0.6,
            "source": SOURCE,
            "given_by": "R1",
        }
    ]
    assert imported.report["unverified_transforms"] == []
    assert "1 from heights.json" in imported.data["source"]


def test_a_back_part_hangs_below_the_board_and_needs_review(tmp_path: Path) -> None:
    imported = read(tmp_path, part("U1", 115, 70, layer="B.Cu"), {"U1": height(2.0)})
    (box,) = imported.data["components"]

    assert box["bottom_offset_from_board_top_mm"] == -3.6
    assert box["height_mm"] == 2.0
    assert "footprint_transforms" in review(imported)
    assert imported.report["unverified_transforms"] == [
        "U1: its courtyard placed through angle 0 on the bottom side"
    ]


def test_a_turned_part_turns_its_courtyard_and_needs_review(tmp_path: Path) -> None:
    imported = read(tmp_path, part("R1", 115, 70, angle=90), {"R1": height(0.6)})
    (box,) = imported.data["components"]

    assert (box["width_mm"], box["depth_mm"]) == (1.5, 3.0)
    assert "footprint_transforms" in review(imported)


def test_a_part_with_no_courtyard_is_its_pads_with_a_warning(tmp_path: Path) -> None:
    imported = read(tmp_path, part("R1", 115, 70, size=None), {"R1": height(0.6)})
    (box,) = imported.data["components"]
    # Each 0.8 x 0.9 pad is taken as the square round its circle, 1.204 mm across.
    reach = (0.8**2 + 0.9**2) ** 0.5 / 2

    assert box["width_mm"] == round(1.6 + 2 * reach, 3)
    assert box["depth_mm"] == round(2 * reach, 3)
    assert imported.report["parts"]["plans_from_pads"] == ["R1"]
    assert any("R1 has no courtyard" in note for note in imported.report["notes"])


def test_mounting_holes_fiducials_test_points_and_logos_are_not_parts(
    tmp_path: Path,
) -> None:
    body = "\n".join(
        [
            mounting_hole("H1", 103, 53),
            part("FID1", 110, 60, name="Fiducial:Fiducial_1mm_Mask2mm"),
            part("TP1", 112, 60, name="TestPoint:TestPoint_Pad_D1.0mm"),
            part("TP2", 114, 60, name="Connector_Pin:Pin_D1.0mm"),
            part("LOGO1", 116, 60, name="Symbol:OSHW-Logo2_7.3x6mm_SilkScreen"),
            part("NT1", 118, 60, name="NetTie:NetTie-2_SMD", attr="smd board_only"),
            part("R1", 120, 80),
        ]
    )
    imported = read(tmp_path, body, {"R1": height(0.6)})
    excluded = {
        item["reference"]: item["why"] for item in imported.report["parts"]["excluded"]
    }

    assert [box["identifier"] for box in imported.data["components"]] == ["R1"]
    assert excluded == {
        "H1": "a mounting hole",
        "FID1": "a fiducial",
        "TP1": "a test point",
        "TP2": "a test point",
        "LOGO1": "a logo",
        "NT1": "board only: not placed as a part",
    }
    assert imported.data["mounting_holes"]["diameter_mm"] == 2.7


def test_a_reference_beats_a_library_name_which_beats_a_pattern(
    tmp_path: Path,
) -> None:
    body = "\n".join(
        [
            part("R1", 105, 55),
            part("R2", 115, 55),
            part("R3", 125, 55, name="Resistor_SMD:R_1206_3216Metric"),
            part("C1", 105, 85, name="Capacitor_SMD:C_0805_2012Metric"),
            part("U1", 125, 85, name="Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"),
        ]
    )
    heights = {
        "R*": height(0.5, "resistors, measured"),
        "Capacitor_SMD:*": height(1.4, "capacitors, datasheet"),
        "Resistor_SMD:R_1206_3216Metric": height(0.7, "1206, datasheet"),
        "R2": height(0.9, "R2, measured"),
        "Q*": height(9.0, "no Q on this board"),
    }
    imported = read(
        tmp_path,
        body,
        heights,
        default_height_mm=1.75,
        default_height_source="SOIC-8, datasheet",
    )
    given = {
        item["reference"]: (item["height_mm"], item["given_by"])
        for item in imported.report["parts"]["heights"]
    }

    assert given == {
        "R1": (0.5, "R*"),
        "R2": (0.9, "R2"),
        "R3": (0.7, "Resistor_SMD:R_1206_3216Metric"),
        "C1": (1.4, "Capacitor_SMD:*"),
        "U1": (1.75, "--default-height"),
    }
    assert imported.report["parts"]["heights_file_unused"] == ["Q*"]
    assert "4 from heights.json" in imported.data["source"]
    assert (
        "1 one default of 1.75 mm, source: SOIC-8, datasheet"
        in (imported.data["source"])
    )
    assert "heights" not in review(imported)


def test_a_part_with_no_height_is_left_out_and_named_for_review(
    tmp_path: Path,
) -> None:
    body = part("R1", 105, 60) + part("U7", 120, 80)
    imported = read(tmp_path, body, {"R1": height(0.6)})

    assert [box["identifier"] for box in imported.data["components"]] == ["R1"]
    assert imported.report["parts"]["without_height"] == ["U7"]
    (heights,) = [
        item for item in imported.data["needs_review"] if item.startswith("heights")
    ]
    assert "(U7)" in heights
    assert "1 none" in imported.data["source"]

    bare = read(tmp_path, body)

    assert bare.data["components"] == []
    assert "envelope" not in bare.data
    assert "heights" in review(bare)


def test_a_default_height_sizes_every_part_and_writes_no_envelope(
    tmp_path: Path,
) -> None:
    imported = read(
        tmp_path,
        part("R1", 105, 60) + part("U7", 120, 80),
        default_height_mm=3.0,
        default_height_source="tallest part, measured",
    )

    assert "envelope" not in imported.data
    assert {box["height_mm"] for box in imported.data["components"]} == {3.0}
    assert "2 one default of 3 mm" in imported.data["source"]


@pytest.mark.parametrize(
    ("heights", "message"),
    [
        ({"R1": {"height_mm": 0.6}}, "needs a source"),
        ({"R1": {"height_mm": 0.6, "source": " "}}, "needs a source"),
        ({"R1": {"height_mm": "tall", "source": SOURCE}}, "needs height_mm"),
        ({"R1": {"height_mm": 0, "source": SOURCE}}, "0.05 to 200"),
        ({"R1": {"height_mm": 0.6, "source": SOURCE, "max": 1}}, "has no max"),
        ({"R1": 0.6}, "must be an object"),
        ({}, "must be a JSON object"),
    ],
)
def test_a_heights_file_must_give_a_height_and_its_source(
    tmp_path: Path, heights: dict[str, Any], message: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=message):
        read(tmp_path, part("R1", 105, 60), heights)


def test_a_heights_file_that_is_not_json_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "heights.json"
    path.write_text("R1: 0.6", encoding="utf-8")
    board = tmp_path / "board.kicad_pcb"
    board.write_text(pcb(part("R1", 105, 60)), encoding="utf-8")

    with pytest.raises(ValueError, match="is not JSON"):
        import_kicad(board, heights_file=path)


def test_a_heights_file_for_a_board_with_no_parts_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="nothing to size"):
        read(tmp_path, mounting_hole("H1", 103, 53), {"R1": height(0.6)})


def test_neighbours_of_a_height_merge_into_one_box_named_by_its_parts(
    tmp_path: Path,
) -> None:
    # Five resistors 1 mm apart in a row, and a tall part beside them.
    body = "".join(part(f"R{n}", 104 + 4 * n, 60) for n in range(1, 6))
    body += part("U1", 116, 63, size=(5.0, 3.0))
    imported = read(tmp_path, body, {"R*": height(0.6), "U1": height(6.0)})
    boxes = {box["identifier"]: box for box in imported.data["components"]}

    assert sorted(boxes) == ["R1_and_4_more", "U1"]
    assert boxes["R1_and_4_more"]["width_mm"] == 19.0
    assert boxes["U1"]["height_mm"] == 6.0
    assert imported.report["parts"] == {
        **imported.report["parts"],
        "read": 6,
        "boxes": 2,
    }


def test_a_mounting_hole_keeps_parts_either_side_of_it_apart(tmp_path: Path) -> None:
    body = mounting_hole("H1", 115, 70) + part("R1", 112, 70) + part("R2", 118, 70)
    imported = read(tmp_path, body, {"R*": height(0.6)})

    assert sorted(box["identifier"] for box in imported.data["components"]) == [
        "R1",
        "R2",
    ]


def test_a_part_past_an_edge_is_a_candidate_and_can_be_named(tmp_path: Path) -> None:
    # A 9 x 7.5 mm connector whose courtyard reaches 2.75 mm past the bottom
    # edge in KiCad, the negative_y edge of the board file.
    body = part("J1", 115, 89, size=(9.0, 7.5)) + part("R1", 105, 60)
    heights = {"J1": height(3.3), "R1": height(0.6)}
    first = read(tmp_path, body, heights)
    (candidate,) = first.report["cable_connector_candidates"]

    assert candidate == {
        "identifier": "J1",
        "edge": "negative_y",
        "past_edge_mm": 2.75,
        "side": "top",
        "size_mm": [9.0, 7.5, 3.3],
    }
    assert first.data["cable_connector"]["edge"] == "negative_y"
    assert {
        box["identifier"]: box["access_edge"] for box in first.data["components"]
    } == {
        "J1": "negative_y",
        "R1": None,
    }

    named = read(tmp_path, body, heights, cable_connector="J1")

    assert named.data["cable_connector"] == {
        "identifier": "J1",
        "edge": "negative_y",
        "width_mm": 9.0,
        "height_mm": 3.3,
        "depth_mm": 4.75,
        "center_offset_mm": 0.0,
        "bottom_offset_from_board_top_mm": 0.0,
    }
    assert [box["identifier"] for box in named.data["components"]] == ["R1"]
    assert "needs_review" not in named.data

    result = check_board_data(named.data)

    assert result.valid, result.errors


def test_a_part_just_inside_an_edge_is_a_candidate_with_no_access_edge(
    tmp_path: Path,
) -> None:
    # The courtyard stops 0.5 mm short of the right-hand edge.
    imported = read(tmp_path, part("J2", 128, 70), {"J2": height(3.0)})
    (candidate,) = imported.report["cable_connector_candidates"]

    assert (candidate["edge"], candidate["past_edge_mm"]) == ("positive_x", -0.5)
    assert imported.data["components"][0]["access_edge"] is None


def test_a_connector_must_be_at_an_edge_and_have_a_height(tmp_path: Path) -> None:
    body = part("J1", 115, 89, size=(9.0, 7.5)) + part("R1", 105, 60)

    with pytest.raises(ValueError, match="R1 is not one of the parts at an edge: J1"):
        read(tmp_path, body, {"R1": height(0.6)}, cable_connector="R1")

    with pytest.raises(ValueError, match="J1 has no height"):
        read(tmp_path, body, {"R1": height(0.6)}, cable_connector="J1")

    with pytest.raises(ValueError, match="no parts"):
        read(tmp_path, mounting_hole("H1", 103, 53), cable_connector="J1")


def test_the_same_file_gives_the_same_data(tmp_path: Path) -> None:
    body = "".join(part(f"R{n}", 104 + 4 * n, 60) for n in range(1, 6))
    heights = {"R*": height(0.6)}

    assert read(tmp_path, body, heights).data == read(tmp_path, body, heights).data


def test_the_command_reads_heights_and_names_the_connector(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = tmp_path / "board.kicad_pcb"
    source.write_text(
        pcb(part("J1", 115, 89, size=(9.0, 7.5)) + part("R1", 105, 60)),
        encoding="utf-8",
    )
    heights = write_heights(tmp_path, {"J1": height(3.3), "R1": height(0.6)})
    output = tmp_path / "board.json"
    code = main(
        [
            "board",
            "import",
            "--kicad",
            str(source),
            "--output",
            str(output),
            "--heights",
            str(heights),
            "--cable-connector",
            "J1",
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["errors"] == []
    assert report["needs_review"] == []
    assert report["parts"]["read"] == 2
    assert json.loads(output.read_text())["cable_connector"]["identifier"] == "J1"


def test_a_step_import_refuses_a_heights_file(
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
            "--heights",
            str(tmp_path / "heights.json"),
        ]
    )

    assert code == 1
    assert "--heights is for a KiCad file" in capsys.readouterr().err
