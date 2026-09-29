"""Design and export a screw-together enclosure for a Pico 2 and an OLED.

This walks the core engine end to end, without the Validation Lab:

1. Place catalogued hardware (a Pico 2 under a 128x64 OLED) in an assembly.
2. Check the assembly for interference and minimum clearances.
3. Build the enclosure from it: a base with board standoffs, heat-set insert
   bosses, and a cable opening, and a lid with screw holes, a display
   window, and a retainer that holds the display. The builder picks the
   side clearance that keeps the bosses clear, and refuses features that
   would hit any part.
4. Export both parts through the validated pipeline: STEP, STL, and per-part
   metadata, published only if geometry validation passes.
5. Write a review package beside them: an exploded GLB, SVG views, and a
   report of clearances, checks, and the screws to buy.

Run from the repository root:

    python examples/pico2_oled_enclosure.py [output-directory]

The same enclosure comes from the command line with::

    zcad-validation enclosure build --board raspberry_pi_pico_2 \
      --display reference_oled_128x64 --bottom-clearance-mm 3 \
      --top-clearance-mm 1 --output-directory exports/pico2-oled-enclosure --review

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
from zcad_core.features import (
    Enclosure,
    EnclosureDesign,
    EnclosureReview,
    build_enclosure,
    export_enclosure_review,
)
from zcad_core.hardware import get_raspberry_pi_pico2, get_reference_oled_128x64
from zcad_core.profiles import load_printer_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRINTER_PROFILE = REPOSITORY_ROOT / "profiles/printers/bambu-lab-a1-mini.json"

BOARD = get_raspberry_pi_pico2()
DISPLAY = get_reference_oled_128x64()
DISPLAY_HEIGHT_MM = 8.0
BOARD_DISPLAY_CLEARANCE_MM = 1.0
CONNECTOR_ACCESS_CLEARANCE_MM = 2.0
# The board sits on 3 mm standoffs, with the display 1 mm under the lid.
# The side clearance is left automatic: the builder widens the long axis
# until the M3 corner bosses clear the board and display.
DESIGN = EnclosureDesign(
    fastener="M3",
    bottom_clearance_mm=3.0,
    top_clearance_mm=1.0,
)


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


def main(output_directory: Path) -> tuple[ExportResult, EnclosureReview]:
    placed = assembly()
    parts = build_enclosure(placed, board=BOARD, display=DISPLAY, design=DESIGN)

    result = export_parts(
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
    review = export_enclosure_review(
        parts, placed, output_directory=output_directory / "review"
    )

    return result, review


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPOSITORY_ROOT / "exports/pico2-oled-enclosure"
    )
    result, review = main(target)

    for part in result.parts:
        print(f"{part.step_path}\n{part.stl_path}\n{part.metadata_path}")
    print(f"review {'passed' if review.passed else 'FAILED'}: {review.report_path}")
