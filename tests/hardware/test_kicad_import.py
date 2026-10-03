"""Reading a board's outline, thickness and holes from a KiCad PCB.

The boards here are written by hand to the file format's documented tokens, not
exported from KiCad: KiCad's Y direction, footprint rotation sign and bottom-side
mirror are the conventions an import depends on, and these tests pin what the
reader assumes of them, not what KiCad does. A real board is the check on that.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from zcad_core.cli import main
from zcad_core.hardware import check_board_data
from zcad_core.hardware.electronics.kicad_import import Placement, import_kicad

# The board is 30 x 40 mm, its top left corner at (100, 50) in KiCad's frame, where
# Y points down; the centre is (115, 70).
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


def line(x0: float, y0: float, x1: float, y1: float, layer: str = "Edge.Cuts") -> str:
    return (
        f'(gr_line (start {x0} {y0}) (end {x1} {y1}) (layer "{layer}") '
        "(stroke (width 0.05) (type default)))"
    )


def rectangle(x0: float = X0, y0: float = Y0, x1: float = X1, y1: float = Y1) -> str:
    return "\n".join(
        [line(x0, y0, x1, y0), line(x1, y0, x1, y1), line(x1, y1, x0, y1)]
        + [line(x0, y1, x0, y0)]
    )


def arc(cx: float, cy: float, r: float, a0: float, a1: float) -> str:
    """An arc about a centre from one angle to another, as start, mid, end."""

    def at(degrees: float) -> str:
        return f"{cx + r * math.cos(math.radians(degrees))} " + (
            f"{cy + r * math.sin(math.radians(degrees))}"
        )

    return (
        f"(gr_arc (start {at(a0)}) (mid {at((a0 + a1) / 2)}) (end {at(a1)}) "
        '(layer "Edge.Cuts") (stroke (width 0.05) (type default)))'
    )


def hole(
    reference: str,
    x: float,
    y: float,
    diameter: float,
    *,
    angle: float = 0,
    layer: str = "F.Cu",
    offset: tuple[float, float] = (0, 0),
    kind: str = "np_thru_hole",
    name: str = "MountingHole:MountingHole_2.7mm_M3",
    drill: str | None = None,
) -> str:
    at = f"{x} {y}" + (f" {angle}" if angle else "")

    return (
        f'(footprint "{name}" (layer "{layer}") (at {at}) '
        f'(property "Reference" "{reference}") '
        f'(pad "" {kind} circle (at {offset[0]} {offset[1]}) '
        f"(size {diameter} {diameter}) (drill {drill or diameter}) "
        '(layers "*.Cu" "*.Mask")))'
    )


def corners(inset: float = 3.0, diameter: float = 2.7) -> str:
    return "\n".join(
        hole(f"H{n}", x, y, diameter)
        for n, (x, y) in enumerate(
            [
                (X0 + inset, Y0 + inset),
                (X1 - inset, Y0 + inset),
                (X0 + inset, Y1 - inset),
                (X1 - inset, Y1 - inset),
            ]
        )
    )


def pcb(
    body: str,
    *,
    version: str = "20240108",
    thickness: str | None = "1.6",
    header: str = '(generator "pcbnew") (generator_version "8.0")',
) -> str:
    general = f"(general (thickness {thickness}))" if thickness is not None else ""

    return f"(kicad_pcb (version {version}) {header} {general}\n{body}\n)\n"


def write(tmp_path: Path, text: str, name: str = "board.kicad_pcb") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")

    return path


def read(tmp_path: Path, body: str, **kwargs: Any) -> Any:
    options = {
        key: kwargs.pop(key)
        for key in ("identifier", "default_height_mm", "default_height_source")
        if key in kwargs
    }

    return import_kicad(write(tmp_path, pcb(body, **kwargs)), **options)


def test_a_rectangle_with_four_holes_gives_a_checked_file(tmp_path: Path) -> None:
    imported = read(
        tmp_path,
        rectangle() + corners(),
        default_height_mm=6.0,
        default_height_source="tallest part, measured",
    )
    data = imported.data

    assert data["outline"] == "rectangle"
    assert data["board"] == {"width_mm": 30.0, "length_mm": 40.0, "thickness_mm": 1.6}
    assert data["mounting_holes"]["diameter_mm"] == 2.7
    assert sorted(map(tuple, data["mounting_holes"]["positions_mm"])) == [
        (-12.0, -17.0),
        (-12.0, 17.0),
        (12.0, -17.0),
        (12.0, 17.0),
    ]
    assert data["envelope"] == {"top_mm": 6.0}
    assert "tallest part, measured" in data["source"]
    assert "SHA-256" in data["source"]
    assert [item.split(":")[0] for item in data["needs_review"]] == ["cable_connector"]
    assert not check_board_data(data).valid

    settled = {k: v for k, v in data.items() if k != "needs_review"}
    settled["cable_connector"] = CONNECTOR
    result = check_board_data(settled)

    assert result.valid, result.errors


def test_y_is_flipped_so_a_hole_low_in_kicad_is_low_in_the_file(
    tmp_path: Path,
) -> None:
    body = (
        rectangle() + hole("H1", X0 + 5, Y0 + 5, 2.7) + hole("H2", X0 + 5, Y1 - 10, 2.7)
    )
    positions = read(tmp_path, body).data["mounting_holes"]["positions_mm"]

    # KiCad y 55 is 15 mm above the centre (y 70), near the top edge, and the
    # file's +Y is the top; y 80 is 10 mm below the centre.
    assert [-10.0, 15.0] in positions
    assert [-10.0, -10.0] in positions


def test_a_board_centred_anywhere_in_kicad_is_centred_on_the_origin(
    tmp_path: Path,
) -> None:
    far = read(tmp_path, rectangle(-300, -200, -270, -160)).data

    assert far["board"]["width_mm"] == 30.0
    assert far["board"]["length_mm"] == 40.0
    assert far["outline"] == "rectangle"


def test_four_equal_round_corners_give_a_rounded_rectangle(tmp_path: Path) -> None:
    r = 3.0
    body = "\n".join(
        [
            line(X0 + r, Y0, X1 - r, Y0),
            line(X1, Y0 + r, X1, Y1 - r),
            line(X1 - r, Y1, X0 + r, Y1),
            line(X0, Y1 - r, X0, Y0 + r),
            arc(X1 - r, Y0 + r, r, -90, 0),
            arc(X1 - r, Y1 - r, r, 0, 90),
            arc(X0 + r, Y1 - r, r, 90, 180),
            arc(X0 + r, Y0 + r, r, 180, 270),
        ]
    )
    data = read(tmp_path, body).data

    assert data["outline"] == {"type": "rounded_rectangle", "radius_mm": 3.0}
    assert data["board"]["width_mm"] == 30.0
    assert data["board"]["length_mm"] == 40.0


def test_unequal_corners_are_a_polygon_not_a_rounded_rectangle(
    tmp_path: Path,
) -> None:
    body = "\n".join(
        [
            line(X0 + 3, Y0, X1 - 6, Y0),
            line(X1, Y0 + 6, X1, Y1 - 3),
            line(X1 - 3, Y1, X0 + 3, Y1),
            line(X0, Y1 - 3, X0, Y0 + 3),
            arc(X1 - 6, Y0 + 6, 6, -90, 0),
            arc(X1 - 3, Y1 - 3, 3, 0, 90),
            arc(X0 + 3, Y1 - 3, 3, 90, 180),
            arc(X0 + 3, Y0 + 3, 3, 180, 270),
        ]
    )
    data = read(tmp_path, body).data

    assert data["outline"]["type"] == "polygon"
    assert len(data["outline"]["points_mm"]) <= 500


def test_a_cut_corner_is_a_polygon_inside_its_bounding_box(tmp_path: Path) -> None:
    body = "\n".join(
        [
            line(X0, Y0, X1, Y0),
            line(X1, Y0, X1, Y1 - 10),
            line(X1, Y1 - 10, X1 - 10, Y1),
            line(X1 - 10, Y1, X0, Y1),
            line(X0, Y1, X0, Y0),
        ]
    )
    imported = read(tmp_path, body)
    points = imported.data["outline"]["points_mm"]

    assert imported.data["outline"]["type"] == "polygon"
    assert len(points) == 5
    # The cut is at the bottom right of KiCad's view: file -X? no, +X; and -Y.
    assert [15.0, -10.0] in points
    assert [5.0, -20.0] in points
    assert imported.report["outline"]["kind"] == "polygon"
    assert check_board_data(
        {
            **{k: v for k, v in imported.data.items() if k != "needs_review"},
            "cable_connector": CONNECTOR,
            "envelope": {"top_mm": 5.0},
        }
    ).valid


def test_a_round_board_is_a_polygon_of_its_circle(tmp_path: Path) -> None:
    body = '(gr_circle (center 120 80) (end 140 80) (layer "Edge.Cuts"))'
    data = read(tmp_path, body).data

    assert data["outline"]["type"] == "polygon"
    assert data["board"]["width_mm"] == pytest.approx(40.0, abs=0.05)
    assert data["board"]["length_mm"] == pytest.approx(40.0, abs=0.05)


def test_items_on_other_layers_are_not_the_outline(tmp_path: Path) -> None:
    body = rectangle() + line(0, 0, 500, 500, layer="F.SilkS")

    assert read(tmp_path, body).data["board"]["width_mm"] == 30.0


def test_a_footprint_may_carry_part_of_the_outline(tmp_path: Path) -> None:
    edge = '(layer "Edge.Cuts") (stroke (width 0.05) (type default))'
    notch = (
        f'(footprint "Lib:Edge" (layer "F.Cu") (at {X0} {Y0}) '
        f"(fp_line (start 0 0) (end 30 0) {edge}))"
    )
    body = "\n".join(
        [line(X1, Y0, X1, Y1), line(X1, Y1, X0, Y1), line(X0, Y1, X0, Y0), notch]
    )
    data = read(tmp_path, body).data

    assert data["board"]["length_mm"] == 40.0
    assert data["outline"] == "rectangle"


def test_ends_that_do_not_meet_are_refused_with_the_gap(tmp_path: Path) -> None:
    body = "\n".join(
        [
            line(X0, Y0, X1, Y0),
            line(X1, Y0, X1, Y1),
            line(X1, Y1, X0, Y1),
            line(X0, Y1, X0, Y0 + 0.5),
        ]
    )

    with pytest.raises(ValueError, match=r"0\.500 mm apart"):
        read(tmp_path, body)


def test_ends_within_a_hundredth_of_a_millimetre_join(tmp_path: Path) -> None:
    body = "\n".join(
        [
            line(X0, Y0, X1, Y0),
            line(X1, Y0, X1, Y1),
            line(X1, Y1, X0, Y1),
            line(X0, Y1, X0, Y0 + 0.005),
        ]
    )

    assert read(tmp_path, body).data["board"]["length_mm"] == 40.0


def test_two_boards_are_a_panel_and_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="2 separate outlines"):
        read(tmp_path, rectangle() + rectangle(200, 50, 230, 90))


def test_no_outline_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no board outline"):
        read(tmp_path, corners())


def test_a_hole_sized_circle_in_the_outline_is_a_hole(tmp_path: Path) -> None:
    body = rectangle() + (
        '(gr_circle (center 103 53) (end 104.35 53) (layer "Edge.Cuts"))'
    )
    imported = read(tmp_path, body)

    assert imported.data["mounting_holes"]["diameter_mm"] == pytest.approx(
        2.7, abs=0.01
    )
    assert imported.data["mounting_holes"]["positions_mm"] == [[-12.0, 17.0]]
    assert imported.report["cutouts_not_modelled"] == []


def test_other_cutouts_are_listed_and_not_modelled(tmp_path: Path) -> None:
    body = rectangle() + rectangle(110, 60, 120, 65) + corners()
    cutouts = read(tmp_path, body).report["cutouts_not_modelled"]

    assert cutouts == [
        {"kind": "cutout", "centre_mm": [0.0, 7.5], "size_mm": [10.0, 5.0]}
    ]


def test_a_large_circle_cutout_is_listed_as_a_circle(tmp_path: Path) -> None:
    body = rectangle() + (
        '(gr_circle (center 115 70) (end 120 70) (layer "Edge.Cuts"))'
    )
    imported = read(tmp_path, body)

    assert imported.report["cutouts_not_modelled"][0]["kind"] == "circle"
    assert "mounting_holes" not in imported.data


def test_the_commonest_size_is_the_mounting_size_and_the_rest_are_listed(
    tmp_path: Path,
) -> None:
    body = (
        rectangle()
        + corners()
        + hole("H5", X0 + 15, Y0 + 5, 3.2)
        + hole("H6", X0 + 15, Y1 - 5, 3.2)
        + hole("TOOL1", X0 + 8, Y0 + 20, 1.0)
    )
    imported = read(tmp_path, body)

    assert imported.report["mounting_holes"] == {"diameter_mm": 2.7, "count": 4}
    sizes = {
        h["diameter_mm"]: h["positions_mm"] for h in imported.report["other_holes"]
    }

    assert sorted(sizes) == [1.0, 3.2]
    assert sizes[1.0] == [[-7.0, 0.0]]


def test_a_hole_too_wide_for_a_board_file_is_listed_not_mounting(
    tmp_path: Path,
) -> None:
    body = rectangle() + hole("W1", X0 + 15, Y0 + 20, 12.0)
    imported = read(tmp_path, body)

    assert "mounting_holes" not in imported.data
    assert imported.report["other_holes"][0]["diameter_mm"] == 12.0


def test_a_tie_goes_to_the_smaller_hole(tmp_path: Path) -> None:
    body = (
        rectangle()
        + hole("A", X0 + 5, Y0 + 5, 2.7)
        + hole("B", X1 - 5, Y0 + 5, 2.7)
        + hole("C", X0 + 5, Y1 - 5, 3.2)
        + hole("D", X1 - 5, Y1 - 5, 3.2)
    )

    assert read(tmp_path, body).data["mounting_holes"]["diameter_mm"] == 2.7


def test_a_plated_drill_counts_only_in_a_mounting_hole_footprint(
    tmp_path: Path,
) -> None:
    plated = hole(
        "H1",
        X0 + 5,
        Y0 + 5,
        3.2,
        kind="thru_hole",
        name="MountingHole:MountingHole_3.2mm_M3_Pad",
    )
    part = hole(
        "J1", X1 - 5, Y0 + 5, 3.2, kind="thru_hole", name="Connector:Header_1x02"
    )
    data = read(tmp_path, rectangle() + plated + part).data

    assert data["mounting_holes"]["positions_mm"] == [[-10.0, 15.0]]


def test_an_oval_drill_is_a_slot_listed_not_a_hole(tmp_path: Path) -> None:
    slot = hole("S1", X0 + 8, Y0 + 8, 2.0, drill="oval 2.0 4.0")
    imported = read(tmp_path, rectangle() + slot)

    assert "mounting_holes" not in imported.data
    assert imported.report["slots_not_modelled"] == [[-7.0, 12.0]]


def test_a_footprint_turned_with_an_offset_drill_needs_review(
    tmp_path: Path,
) -> None:
    turned = hole("H1", X0 + 15, Y0 + 20, 2.7, angle=90, offset=(5, 0))
    imported = read(tmp_path, rectangle() + turned)

    assert imported.report["unverified_transforms"]
    assert any(
        item.startswith("footprint_transforms")
        for item in imported.data["needs_review"]
    )


def test_a_turned_footprint_with_a_centred_drill_is_not_in_doubt(
    tmp_path: Path,
) -> None:
    turned = hole("H1", X0 + 15, Y0 + 20, 2.7, angle=90, layer="B.Cu")
    imported = read(tmp_path, rectangle() + turned)

    assert imported.report["unverified_transforms"] == []
    assert imported.data["mounting_holes"]["positions_mm"] == [[0.0, 0.0]]


def test_the_footprint_turn_assumed_is_counter_clockwise_on_screen() -> None:
    # A point to the right of a footprint, turned 90 degrees counter-clockwise
    # as seen on screen, ends up above it; the file's Y points down, so that is
    # a smaller Y.
    x, y = Placement(10.0, 20.0, 90.0).apply((1.0, 0.0))

    assert (round(x, 9), round(y, 9)) == (10.0, 19.0)

    x, y = Placement(10.0, 20.0, 0.0, bottom=True).apply((1.0, 0.0))

    assert (round(x, 9), round(y, 9)) == (9.0, 20.0)


def test_the_thickness_comes_from_the_file(tmp_path: Path) -> None:
    imported = read(tmp_path, rectangle(), thickness="1.2")

    assert imported.data["board"]["thickness_mm"] == 1.2
    assert imported.report["thickness"]["from"] == "file"
    assert not any(
        item.startswith("thickness") for item in imported.data["needs_review"]
    )


def test_a_missing_thickness_is_a_placeholder_needing_review(tmp_path: Path) -> None:
    imported = read(tmp_path, rectangle(), thickness=None)

    assert imported.report["thickness"]["from"].startswith("placeholder")
    assert any(item.startswith("thickness") for item in imported.data["needs_review"])


def test_heights_are_open_unless_a_default_with_its_source_is_given(
    tmp_path: Path,
) -> None:
    imported = read(tmp_path, rectangle())

    assert "envelope" not in imported.data
    assert any(item.startswith("heights") for item in imported.data["needs_review"])

    with pytest.raises(ValueError, match="go together"):
        read(tmp_path, rectangle(), default_height_mm=5.0)

    with pytest.raises(ValueError, match="go together"):
        read(tmp_path, rectangle(), default_height_source="measured")

    with pytest.raises(ValueError, match="go together"):
        read(tmp_path, rectangle(), default_height_mm=5.0, default_height_source=" ")


def test_the_file_version_and_generator_are_recorded(tmp_path: Path) -> None:
    imported = read(tmp_path, rectangle())

    assert imported.report["file"]["kicad_file_version"] == "20240108"
    assert imported.report["file"]["generator"] == "pcbnew"
    assert imported.report["file"]["generator_version"] == "8.0"
    assert "KiCad file version 20240108" in imported.data["source"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (pcb(rectangle(), version="20171130"), "older than KiCad 6"),
        ("(kicad_pcb (generator pcbnew))", "older than KiCad 6"),
        ("(module Lib:Name)", "not a KiCad PCB"),
        (
            "(kicad_pcb (version 20240108) (module Lib:Name (layer F.Cu)))",
            "KiCad 5's module form",
        ),
        ("(something_else (version 20240108))", "not a KiCad PCB"),
    ],
)
def test_files_the_reader_cannot_use_are_refused(
    tmp_path: Path, text: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        import_kicad(write(tmp_path, text))


def test_an_unknown_token_is_skipped(tmp_path: Path) -> None:
    body = rectangle() + "(zone (net 0) (name x) (future_token 1 2 3))"

    assert read(tmp_path, body).data["board"]["width_mm"] == 30.0


def test_the_same_file_gives_the_same_data(tmp_path: Path) -> None:
    path = write(tmp_path, pcb(rectangle() + corners()))

    assert import_kicad(path).data == import_kicad(path).data


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any]:
    exit_code = main(list(args))
    out = capsys.readouterr().out

    return exit_code, json.loads(out) if out else None


def test_the_command_writes_a_file_and_reports(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = write(tmp_path, pcb(rectangle() + corners()))
    output = tmp_path / "board.json"
    exit_code, report = run(
        capsys,
        "board",
        "import",
        "--kicad",
        str(source),
        "--output",
        str(output),
        "--default-height",
        "6",
        "--default-height-source",
        "tallest part, measured",
    )

    assert exit_code == 0
    assert report["written"] == str(output)
    assert report["mounting_holes"] == {"diameter_mm": 2.7, "count": 4}
    assert report["outline"] == {"kind": "rectangle", "size_mm": [30.0, 40.0]}
    assert report["file"]["kicad_file_version"] == "20240108"
    assert any("not reviewed" in error for error in report["errors"])
    assert json.loads(output.read_text())["envelope"] == {"top_mm": 6.0}


def test_the_command_does_not_overwrite_and_refuses_what_does_not_apply(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = write(tmp_path, pcb(rectangle()))
    output = tmp_path / "board.json"
    output.write_text("{}")

    assert (
        main(["board", "import", "--kicad", str(source), "--output", str(output)]) == 1
    )

    fresh = tmp_path / "fresh.json"

    for extra in (["--cable-connector", "top-01"], ["--pcb-solid-index", "1"]):
        code = main(
            ["board", "import", "--kicad", str(source), "--output", str(fresh), *extra]
        )

        assert code == 1

    assert not fresh.exists()
    capsys.readouterr()


def test_step_and_kicad_are_exclusive_and_one_is_required(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    source = write(tmp_path, pcb(rectangle()))

    with pytest.raises(SystemExit):
        main(["board", "import", "--output", str(tmp_path / "a.json")])

    with pytest.raises(SystemExit):
        main(
            [
                "board",
                "import",
                "--kicad",
                str(source),
                "--step",
                str(source),
                "--output",
                str(tmp_path / "b.json"),
            ]
        )

    capsys.readouterr()


def test_a_step_import_refuses_the_kicad_height_options(
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
            "--default-height",
            "5",
        ]
    )

    assert code == 1
    capsys.readouterr()
