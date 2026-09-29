"""The enclosure review package."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    build_board_display_assembly,
)
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    build_enclosure,
    export_enclosure_review,
    recommended_screw_length_mm,
)
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
