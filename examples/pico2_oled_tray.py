"""Design and export an enclosure tray for a Raspberry Pi Pico 2 and an OLED.

This walks the core engine end to end, without the Validation Lab:

1. Place catalogued hardware (a Pico 2 under a 128x64 OLED) in an assembly.
2. Check the assembly for interference and minimum clearances.
3. Derive the enclosure cavity and cable opening from the assembly.
4. Build a tray from that specification with feature helpers.
5. Export it through the validated pipeline: STEP, STL, and per-part
   metadata, published only if geometry validation passes.

Run from the repository root:

    python examples/pico2_oled_tray.py [output-directory]

The default output directory is ``exports/pico2-oled-tray`` (ignored by git).
The gate runs this example (``tests/test_examples.py``) so it stays current.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cadquery as cq

from zcad_core.assemblies import (
    EnclosureSpecification,
    Placement,
    analyze_board_display_assembly,
    build_board_display_assembly,
    derive_enclosure_specification,
)
from zcad_core.exporters import ExportRequest, ExportResult, export_parts
from zcad_core.features import ConnectorCutoutParameters, cut_connector_opening
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64
from zcad_core.profiles.loading import load_printer_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRINTER_PROFILE = REPOSITORY_ROOT / "profiles/printers/bambu-lab-a1-mini.json"

WALL_MM = 2.0
FLOOR_MM = 2.0
DISPLAY_HEIGHT_MM = 8.0
BOARD_DISPLAY_CLEARANCE_MM = 1.0
CONNECTOR_ACCESS_CLEARANCE_MM = 2.0


def enclosure_specification() -> EnclosureSpecification:
    """Place the hardware, check it, and derive the cavity it needs."""

    assembly = build_board_display_assembly(
        board=get_raspberry_pi_pico2(),
        display=get_reference_oled_128x64(),
        board_placement=Placement(),
        display_placement=Placement(z_mm=DISPLAY_HEIGHT_MM),
        board_display_clearance_mm=BOARD_DISPLAY_CLEARANCE_MM,
        connector_access_clearance_mm=CONNECTOR_ACCESS_CLEARANCE_MM,
    )

    report = analyze_board_display_assembly(
        assembly,
        minimum_board_display_clearance_mm=BOARD_DISPLAY_CLEARANCE_MM,
    )

    if report.has_findings:
        raise ValueError(f"Assembly has interference findings: {report.findings}")

    return derive_enclosure_specification(
        assembly,
        connector_identifier="board_connector",
    )


def build_shell(spec: EnclosureSpecification) -> cq.Workplane:
    """An open-top box around the cavity, walls and floor only."""

    outer = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm + 2 * WALL_MM,
            spec.inner_depth_mm + 2 * WALL_MM,
            spec.inner_height_mm + FLOOR_MM,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm - FLOOR_MM))
    )
    # The cavity runs past the rim so the top is open.
    cavity = (
        cq.Workplane("XY")
        .box(
            spec.inner_width_mm,
            spec.inner_depth_mm,
            spec.inner_height_mm + 1.0,
            centered=(True, True, False),
        )
        .translate((spec.center_x_mm, spec.center_y_mm, spec.bottom_z_mm))
    )

    return outer.cut(cavity)


def build_tray(spec: EnclosureSpecification) -> cq.Workplane:
    """The shell with the cable opening cut through its connector wall."""

    return cut_connector_opening(
        build_shell(spec),
        parameters=ConnectorCutoutParameters(
            edge=spec.cable_edge,
            center_offset_mm=spec.cable_center_offset_mm,
            bottom_z_mm=spec.cable_bottom_z_mm,
            width_mm=spec.cable_width_mm,
            height_mm=spec.cable_height_mm,
        ),
    )


def main(output_directory: Path) -> ExportResult:
    spec = enclosure_specification()

    return export_parts(
        ExportRequest(
            design_name="pico2-oled-tray",
            design_type="enclosure",
            parts={"tray": build_tray(spec)},
            output_directory=output_directory,
            repository_root=REPOSITORY_ROOT,
            printer_profile=load_printer_profile(PRINTER_PROFILE),
            parameters={"wall_mm": WALL_MM, "floor_mm": FLOOR_MM},
        )
    )


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPOSITORY_ROOT / "exports/pico2-oled-tray"
    )
    result = main(target)

    for part in result.parts:
        print(f"{part.step_path}\n{part.stl_path}\n{part.metadata_path}")
