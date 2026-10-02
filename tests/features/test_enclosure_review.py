"""The enclosure review package."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    build_board_assembly,
    build_board_display_assembly,
)
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
    export_enclosure_review,
    recommended_screw_length_mm,
)
from zcad_core.features.enclosure_review import _motion_clear
from zcad_core.features.lid_hinge import swung_lid
from zcad_core.features.lid_slide import slid_lid
from zcad_core.hardware import (
    get_fastener,
    get_raspberry_pi_pico2,
    get_reference_oled_128x64,
)

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()


def pico2_oled_assembly() -> DeviceAssembly:
    return build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=8.0),
        board_display_clearance_mm=1.0,
        connector_access_clearance_mm=2.0,
    )


@pytest.fixture(scope="module")
def enclosure() -> Enclosure:
    return build_enclosure(pico2_oled_assembly(), board=BOARD, display=DISPLAY)


def test_package_writes_every_artifact_and_passes(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    review = export_enclosure_review(
        enclosure, pico2_oled_assembly(), output_directory=tmp_path / "review"
    )

    assert review.passed
    for path in (
        review.glb_path,
        review.step_path,
        review.report_path,
        *review.view_paths,
    ):
        assert path.is_file() and path.stat().st_size > 0
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report == review.report
    assert set(report["checks"]) == {
        "no_interference",
        "single_solid_parts",
        "screw_path_open",
        "plug_body_clears_floor",
        "only_expected_contact",
    }
    assert report["fasteners"]["recommended_screw_length_mm"] == 6
    assert report["side_clearance_mm"] == {"x": 2.0, "y": 10.0}


def test_clearances_cover_every_part_and_component(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    review = export_enclosure_review(
        enclosure, pico2_oled_assembly(), output_directory=tmp_path
    )
    rows = {(row["part"], row["hardware"]): row for row in review.report["clearances"]}

    assert set(rows) == {
        (part, component.identifier)
        for part in ("base", "lid")
        for component in pico2_oled_assembly().components
    }
    # The board rests on its standoffs and the display against the lid's
    # retainer pads; nothing else touches.
    assert rows["base", "board"]["contact"]
    assert rows["lid", "display"]["contact"]
    assert [key for key, row in rows.items() if row["contact"]] == [
        ("base", "board"),
        ("lid", "display"),
    ]


def test_refuses_to_overwrite_a_package(enclosure: Enclosure, tmp_path: Path) -> None:
    export_enclosure_review(enclosure, pico2_oled_assembly(), output_directory=tmp_path)

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        export_enclosure_review(
            enclosure, pico2_oled_assembly(), output_directory=tmp_path
        )


def test_fails_a_plug_that_would_hit_the_floor(tmp_path: Path) -> None:
    design = EnclosureDesign(bottom_clearance_mm=0.5, cable_plug_height_mm=9.0)
    enclosure = build_enclosure(
        pico2_oled_assembly(), board=BOARD, display=DISPLAY, design=design
    )

    review = export_enclosure_review(
        enclosure, pico2_oled_assembly(), output_directory=tmp_path
    )

    assert not review.passed
    assert not review.report["checks"]["plug_body_clears_floor"]["passed"]


def test_screw_length_fits_the_lid_and_insert(enclosure: Enclosure) -> None:
    m2 = replace(enclosure, fastener=get_fastener("M2"))
    thick_lid = replace(enclosure, design=replace(enclosure.design, lid_mm=3.0))

    assert recommended_screw_length_mm(enclosure) == 6
    assert recommended_screw_length_mm(m2) == 5
    assert recommended_screw_length_mm(thick_lid) == 8


# --- a lid that swings or slides ------------------------------------------------------------------


def plain_assembly() -> DeviceAssembly:
    return build_board_assembly(
        board=BOARD, board_placement=Placement(), connector_access_clearance_mm=2.0
    )


@pytest.fixture(scope="module")
def hinged() -> Enclosure:
    return build_enclosure(
        pico2_oled_assembly(),
        board=BOARD,
        display=DISPLAY,
        design=EnclosureDesign(lid_attachment="hinge", bottom_clearance_mm=6.0),
    )


@pytest.fixture(scope="module")
def slid() -> Enclosure:
    return build_enclosure(
        plain_assembly(), board=BOARD, design=EnclosureDesign(lid_attachment="slide")
    )


def solid(model: cq.Workplane) -> cq.Shape:
    return cq.Compound.makeCompound(
        [
            part
            for item in model.vals()
            if isinstance(item, cq.Shape)
            for part in item.Solids()
        ]
    )


def test_a_hinged_lid_is_reviewed_open_on_its_pin(
    hinged: Enclosure, tmp_path: Path
) -> None:
    review = export_enclosure_review(
        hinged, pico2_oled_assembly(), output_directory=tmp_path / "review"
    )
    report = review.report

    assert review.passed
    assert report["lid_pose"] == "open 100 degrees on its pin"
    assert report["checks"]["lid_motion_clear"]["passed"] is True
    assert report["fasteners"]["lid"] == "hinged"


def test_the_open_lid_turns_about_the_pin_and_rises_clear_of_the_base(
    hinged: Enclosure,
) -> None:
    assert hinged.hinge is not None
    lid = solid(hinged.lid)
    opened = swung_lid(lid, hinged.hinge, hinged.hinge.swing_degrees)
    axis = cq.Vector(*hinged.hinge.axis_point)

    # A point on the pin does not move, and the free edge lifts well above the
    # closed lid.
    pin = cq.Solid.makeCylinder(
        0.5, 4.0, pnt=axis, dir=cq.Vector(*hinged.hinge.axis_direction)
    )
    centre = pin.Center()

    assert swung_lid(pin, hinged.hinge, 100.0).Center().sub(centre).Length < 1e-6
    assert opened.BoundingBox().zmax > lid.BoundingBox().zmax + 20.0


def test_a_sliding_lid_is_reviewed_pushed_out_over_its_entry(
    slid: Enclosure, tmp_path: Path
) -> None:
    review = export_enclosure_review(
        slid, plain_assembly(), output_directory=tmp_path / "review"
    )

    assert slid.slide is not None
    assert review.passed
    assert review.report["lid_pose"].startswith("slid ")
    assert slid.slide.entry_edge in review.report["lid_pose"]
    assert review.report["checks"]["lid_motion_clear"]["passed"] is True


def test_the_slid_lid_moves_its_travel_toward_the_entry(slid: Enclosure) -> None:
    assert slid.slide is not None
    lid = solid(slid.lid)
    out = slid_lid(lid, slid.slide, slid.slide.travel_mm)
    dx, dy, dz = slid.slide.direction

    assert abs(dx) + abs(dy) == pytest.approx(1.0) and dz == 0.0
    moved = out.Center().sub(lid.Center())

    assert moved.x == pytest.approx(dx * slid.slide.travel_mm, abs=1e-6)
    assert moved.y == pytest.approx(dy * slid.slide.travel_mm, abs=1e-6)


def test_a_screwed_lid_is_still_shown_lifted(
    enclosure: Enclosure, tmp_path: Path
) -> None:
    review = export_enclosure_review(
        enclosure, pico2_oled_assembly(), output_directory=tmp_path / "review"
    )

    assert review.report["lid_pose"] == "lifted"
    assert "lid_motion_clear" not in review.report["checks"]


def test_a_part_in_the_lids_path_fails_the_motion_check(hinged: Enclosure) -> None:
    lid = solid(hinged.lid)
    box = lid.BoundingBox()
    # A block standing above the lid, where the opening lid must pass.
    blocker = (
        cq.Workplane("XY")
        .box(10, 10, 10)
        .translate((box.center.x, box.center.y, box.zmax + 15.0))
    )
    hardware = {"BLOCKER": (cast(cq.Shape, blocker.val()), "connector")}
    result = _motion_clear(hinged, lid, hardware)

    assert result is not None and result["passed"] is False
    assert "BLOCKER" in result["detail"]
