"""Design and export a screw-together enclosure for a Pico 2 and an OLED.

This walks the core engine end to end, without the Validation Lab:

1. Place catalogued hardware (a Pico 2 under a 128x64 OLED) in an assembly.
2. Check the assembly for interference and minimum clearances.
3. Build the enclosure from it: a base with board standoffs, heat-set insert
   bosses, and a cable opening, and a lid with screw holes and a display
   window. The builder refuses features that would hit any part.
4. Export both parts through the validated pipeline: STEP, STL, and per-part
   metadata, published only if geometry validation passes.

Run from the repository root:

    python examples/pico2_oled_enclosure.py [output-directory]

The default output directory is ``exports/pico2-oled-enclosure`` (ignored by
git). The gate runs this example (``tests/test_examples.py``) so it stays
current.
"""

from __future__ import annotations

import sys
from pathlib import Path

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    analyze_board_display_assembly,
    build_board_display_assembly,
)
from zcad_core.exporters import ExportRequest, ExportResult, export_parts
from zcad_core.features import Enclosure, EnclosureDesign, build_enclosure
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64
from zcad_core.profiles import load_printer_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRINTER_PROFILE = REPOSITORY_ROOT / "profiles/printers/bambu-lab-a1-mini.json"

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
DISPLAY_HEIGHT_MM = 8.0
BOARD_DISPLAY_CLEARANCE_MM = 1.0
CONNECTOR_ACCESS_CLEARANCE_MM = 2.0
# 5 mm keeps the M3 corner bosses clear of the board; at the 2 mm default
# the builder refuses, naming the board as the part they would hit.
DESIGN = EnclosureDesign(internal_clearance_mm=5.0, fastener="M3")


def assembly() -> DeviceAssembly:
    """Place the hardware and check it for interference."""

    placed = build_board_display_assembly(
        board=BOARD,
        display=DISPLAY,
        board_placement=Placement(),
        display_placement=Placement(z_mm=DISPLAY_HEIGHT_MM),
        board_display_clearance_mm=BOARD_DISPLAY_CLEARANCE_MM,
        connector_access_clearance_mm=CONNECTOR_ACCESS_CLEARANCE_MM,
    )
    report = analyze_board_display_assembly(
        placed,
        minimum_board_display_clearance_mm=BOARD_DISPLAY_CLEARANCE_MM,
    )

    if report.has_findings:
        raise ValueError(f"Assembly has interference findings: {report.findings}")

    return placed


def enclosure() -> Enclosure:
    return build_enclosure(assembly(), board=BOARD, display=DISPLAY, design=DESIGN)


def main(output_directory: Path) -> ExportResult:
    parts = enclosure()

    return export_parts(
        ExportRequest(
            design_name="pico2-oled-enclosure",
            design_type="enclosure",
            parts={"base": parts.base, "lid": parts.lid},
            output_directory=output_directory,
            repository_root=REPOSITORY_ROOT,
            printer_profile=load_printer_profile(PRINTER_PROFILE),
            parameters={"wall": DESIGN.wall_mm, "floor": DESIGN.floor_mm},
        )
    )


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPOSITORY_ROOT / "exports/pico2-oled-enclosure"
    )
    result = main(target)

    for part in result.parts:
        print(f"{part.step_path}\n{part.stl_path}\n{part.metadata_path}")
