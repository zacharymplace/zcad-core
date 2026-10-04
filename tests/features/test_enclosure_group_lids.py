"""A group enclosure's hinged and sliding lids."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.cli.enclosure_group_review import _review_lid, _write_review
from zcad_core.features.enclosure_group import (
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.features.enclosure_group_model import Bay
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.geometry.intersection import intersection_volume
from zcad_core.hardware import get_raspberry_pi5

PRINTER_PROFILE = (
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def has_material(model: cq.Workplane, x: float, y: float, z: float) -> bool:
    probe = cq.Solid.makeBox(0.4, 0.4, 0.4, pnt=cq.Vector(x - 0.2, y - 0.2, z - 0.2))
    (solid,) = model.solids().vals()
    assert isinstance(solid, cq.Shape)

    return intersection_volume(solid, probe) > 0.01


@pytest.fixture(scope="module")
def hinged() -> GroupEnclosure:
    return build_group_enclosure(
        ("pi5", "pi5"),
        design=GroupDesign(lid_attachment="hinge", headroom_mm=20.0),
    )


@pytest.fixture(scope="module")
def slid() -> GroupEnclosure:
    return build_group_enclosure(
        ("pi5", "pi5"), design=GroupDesign(lid_attachment="slide")
    )


# --- the design ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"lid_attachment": "glue"}, "lid_attachment must be one of"),
        ({"lid_attachment": "slide", "slide_entry": "up"}, "slide_entry must be"),
        (
            {"lid_attachment": "slide", "slide_clearance_mm": 0.0},
            "slide_clearance_mm",
        ),
    ],
)
def test_the_design_refuses_a_lid_that_cannot_be_right(
    change: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        GroupDesign(**change).validate()


# --- the hinge ----------------------------------------------------------------


def test_a_hinged_lid_hinges_on_the_back_wall_and_catches_on_the_front(
    hinged: GroupEnclosure,
) -> None:
    assert hinged.passed
    assert hinged.slide is None
    assert hinged.hinge is not None
    assert hinged.hinge.hinge_edge == "positive_y"
    assert hinged.hinge.closure_edge == "negative_y"
    assert hinged.hinge.knuckles == 5


def test_the_long_hinge_takes_a_threaded_rod(hinged: GroupEnclosure) -> None:
    assert hinged.hinge is not None
    assert hinged.hinge.pin_is_rod
    assert hinged.hinge.pin_length_mm % 5 == 0
    assert hinged.hinge.pin_length_mm >= hinged.hinge.span_mm + 2 * 2.4
    assert "threaded rod" in hinged.hinge.pin_description
    assert "nut at each end" in hinged.hinge.pin_description


def test_a_hinged_lid_has_no_screws_or_bosses(hinged: GroupEnclosure) -> None:
    assert hinged.recommended_lid_screw_mm is None
    assert hinged.lid_boss_positions == ()


def test_the_catch_stands_clear_of_the_front_wall_openings(
    hinged: GroupEnclosure,
) -> None:
    """The catch's hook and bump sit on the wall, so it goes between openings."""

    assert hinged.hinge is not None
    pi = get_raspberry_pi5()
    wall = hinged.design.wall_mm
    catch = hinged.hinge.catch_center_mm
    half = 16.0 / 2

    for layout in hinged.bays:
        sd = wall + layout.center_x_mm

        assert abs(catch - sd) > half + pi.sd_card_width_mm / 2


def test_the_hinge_stands_behind_the_back_wall(hinged: GroupEnclosure) -> None:
    depth = hinged.outer_size_mm[1]
    top = hinged.base.val().BoundingBox()  # type: ignore[union-attr]

    assert top.ymax > depth + 5.0


def test_a_back_opening_that_reaches_the_knuckles_is_refused() -> None:
    with pytest.raises(ValueError, match="raise headroom_mm by at least"):
        build_group_enclosure(
            ("pi5", "pi5"), design=GroupDesign(lid_attachment="hinge")
        )


def test_a_hinged_lid_swings_with_dividers_and_an_open_bay() -> None:
    group = build_group_enclosure(
        ("pi5", Bay("pi5", divider=Divider(vents=True, notch=True))),
        design=GroupDesign(lid_attachment="hinge", headroom_mm=20.0),
    )

    assert group.passed


# --- the slide ----------------------------------------------------------------


def test_a_sliding_lid_slides_along_the_row_and_out_of_the_right_end(
    slid: GroupEnclosure,
) -> None:
    assert slid.passed
    assert slid.hinge is None
    assert slid.slide is not None
    assert slid.slide.entry_edge == "positive_x"
    assert slid.slide.lid_length_mm == pytest.approx(slid.outer_size_mm[0], abs=3.5)
    assert slid.recommended_lid_screw_mm is None
    assert slid.lid_boss_positions == ()


def test_the_entry_end_can_be_the_left() -> None:
    group = build_group_enclosure(
        ("pi5", "pi5"),
        design=GroupDesign(lid_attachment="slide", slide_entry="negative_x"),
    )

    assert group.slide is not None
    assert group.slide.entry_edge == "negative_x"
    assert group.passed


def test_a_lone_bay_is_deeper_than_it_is_wide_and_cannot_slide() -> None:
    with pytest.raises(ValueError, match="at least as wide as it is deep"):
        build_group_enclosure(("pi5",), design=GroupDesign(lid_attachment="slide"))


def test_a_back_wall_opening_stays_open_under_the_slides_thickening(
    slid: GroupEnclosure,
) -> None:
    """The thickening starts 3 mm below the wall's top and used to fill the
    top of the Ethernet and USB opening, which the Pi's plugs then hit."""

    pi = get_raspberry_pi5()
    port = next(p for p in pi.ports if p.edge == "positive_y")
    layout = slid.bays[0]
    x = slid.design.wall_mm + layout.center_x_mm + port.center_mm
    y = slid.outer_size_mm[1] - slid.design.wall_mm / 2
    z = slid.cavity_top_z_mm - 2.7

    assert z > slid.cavity_top_z_mm - 3.0
    assert not has_material(slid.base, x, y, z)


def test_a_divider_stops_short_of_a_sliding_lid() -> None:
    group = build_group_enclosure(
        ("pi5", Bay("pi5", divider=Divider())),
        design=GroupDesign(lid_attachment="slide", headroom_mm=20.0),
    )
    layout = group.bays[1]
    x = group.design.wall_mm + layout.divider_start_mm + group.design.divider_mm / 2
    y = group.design.wall_mm + 10.0
    top = group.cavity_top_z_mm

    assert has_material(group.base, x, y, top - 1.0)
    assert not has_material(group.base, x, y, top - 0.15)


def test_a_screwed_lid_is_unchanged() -> None:
    group = build_group_enclosure(("pi5", "pi5"))

    assert group.hinge is None and group.slide is None
    assert group.recommended_lid_screw_mm is not None
    assert len(group.lid_boss_positions) == 6


# --- the command ----------------------------------------------------------------


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    exit_code = main(["enclosure-group", "build", "--bays", "pi5,pi5", *args])

    return exit_code, json.loads(capsys.readouterr().out)


def test_the_command_builds_a_hinged_group(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = run(
        capsys,
        "--lid",
        "hinge",
        "--headroom-mm",
        "20",
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--output-directory",
        str(tmp_path),
    )

    assert exit_code == 0
    assert output["lid"] == "hinge"
    assert output["hinge"]["hinge_wall"] == "positive_y"
    assert output["slide"] is None
    assert output["screws"]["lid"] is None
    assert "threaded rod" in output["screws"]["hinge_pin"]
    assert output["validation_status"] == "PASS"


def test_the_command_builds_a_sliding_group(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    exit_code, output = run(
        capsys,
        "--lid",
        "slide",
        "--slide-entry",
        "negative_x",
        "--printer-profile",
        str(PRINTER_PROFILE),
        "--output-directory",
        str(tmp_path),
    )

    assert exit_code == 0
    assert output["slide"]["entry_wall"] == "negative_x"
    assert output["hinge"] is None
    assert output["screws"]["lid"] is None
    assert output["validation_status"] == "PASS"


# --- the review ---------------------------------------------------------------


def test_a_hinged_group_is_reviewed_with_its_lid_open(
    hinged: GroupEnclosure, tmp_path: Path
) -> None:
    lid, pose = _review_lid(hinged)

    assert hinged.hinge is not None
    assert pose == "open 100 degrees on its pin"
    # The free edge is well above the closed lid.
    assert lid.BoundingBox().zmax > workplane_shape(hinged.lid).BoundingBox().zmax + 50
    path, written = _write_review(hinged, tmp_path / "review", "row")

    assert written == pose and path.is_file()


def test_a_sliding_group_is_reviewed_with_its_lid_pushed_out(
    slid: GroupEnclosure,
) -> None:
    lid, pose = _review_lid(slid)
    closed = workplane_shape(slid.lid).BoundingBox()
    out = lid.BoundingBox()

    assert slid.slide is not None
    assert pose.startswith("slid ") and slid.slide.entry_edge in pose
    assert abs(out.xmin - closed.xmin) == pytest.approx(slid.slide.travel_mm, abs=1e-3)


def test_a_screwed_group_is_reviewed_with_its_lid_lifted() -> None:
    plain = build_group_enclosure(("pi5", "pi5"))

    assert _review_lid(plain)[1] == "lifted"
