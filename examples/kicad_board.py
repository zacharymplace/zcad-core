"""From a KiCad board to an enclosure and a test fixture for it.

This walks the KiCad import end to end, on the sample board beside it
(``examples/kicad/sensor-board.kicad_pcb``, a 50 x 40 mm board written by hand,
not exported from KiCad):

1. Import the board: its outline, thickness and M3 mounting holes; its
   footprints as part boxes from their courtyards, with heights from
   ``examples/kicad/heights.json``; the USB-C connector J1 as the cable
   connector; and its four test pads as test points, with their nets.
2. Check the board file it writes, as ``board check`` would.
3. Build the enclosure for the board, and export it through the validated
   pipeline: STEP, STL and per-part metadata.
4. Write a fixture file for the board's top-side test points, check it, build
   the fixture's nest and pin plate, and export them the same way.

The heights in ``heights.json`` and the fixture's pin are marked EXAMPLE ONLY:
for a real board, take each height from the part's datasheet or a measurement
(or use ``--models`` with the board's STEP models), and the pin's figures from
its maker's datasheet.

Run from the repository root:

    python examples/kicad_board.py [output-directory]

The same steps from the command line::

    zcad-validation board import --kicad examples/kicad/sensor-board.kicad_pcb \
      --identifier SENSOR_BOARD --heights examples/kicad/heights.json \
      --cable-connector J1 --output exports/kicad-board/board.json
    zcad-validation enclosure build --board-file exports/kicad-board/board.json \
      --output-directory exports/kicad-board/enclosure
    zcad-validation fixture template --board-file exports/kicad-board/board.json \
      --output exports/kicad-board/fixture.json
    zcad-validation fixture build --fixture-file exports/kicad-board/fixture.json \
      --output-directory exports/kicad-board/fixture

The default output directory is ``exports/kicad-board`` (ignored by git). The
gate runs this example (``tests/test_examples.py``) so it stays current.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from zcad_core.assemblies import Placement, build_board_assembly
from zcad_core.exporters import ExportRequest, ExportResult, export_parts
from zcad_core.features import EnclosureDesign, build_enclosure
from zcad_core.features.pcb_fixture import (
    PcbFixture,
    build_fixture,
    print_oriented,
    require_fits_bed,
)
from zcad_core.features.pcb_fixture_file import (
    check_fixture_file,
    fixture_template,
    load_fixture,
    load_fixture_board,
    probed_points,
)
from zcad_core.hardware import check_board_file, load_board
from zcad_core.hardware.electronics.kicad_import import import_kicad
from zcad_core.profiles import load_printer_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
KICAD = REPOSITORY_ROOT / "examples/kicad"
PRINTER_PROFILE = REPOSITORY_ROOT / "profiles/printers/bambu-lab-a1-mini.json"
CONNECTOR_ACCESS_CLEARANCE_MM = 2.0
# The board sits on 3 mm standoffs, with 2 mm over its tallest part.
DESIGN = EnclosureDesign(
    fastener="M3",
    bottom_clearance_mm=3.0,
    top_clearance_mm=2.0,
)


def import_board(output_directory: Path) -> Path:
    """Import the KiCad board into a board file, refused if it is not valid."""

    imported = import_kicad(
        KICAD / "sensor-board.kicad_pcb",
        identifier="SENSOR_BOARD",
        heights_file=KICAD / "heights.json",
        cable_connector="J1",
    )
    board_file = output_directory / "board.json"
    board_file.write_text(json.dumps(imported.data, indent=2) + "\n", encoding="utf-8")
    report, _ = check_board_file(board_file)

    if not report.valid or imported.data.get("needs_review"):
        raise ValueError(
            f"The imported board is not ready: {list(report.errors)}, "
            f"{imported.data.get('needs_review')}"
        )

    return board_file


def export_enclosure(board_file: Path, output_directory: Path) -> ExportResult:
    board = load_board(board_file)
    assembly = build_board_assembly(
        board=board,
        board_placement=Placement(),
        connector_access_clearance_mm=CONNECTOR_ACCESS_CLEARANCE_MM,
    )
    parts = build_enclosure(assembly, board=board, design=DESIGN)

    return export_parts(
        ExportRequest(
            design_name="sensor-board-enclosure",
            design_type="enclosure",
            parts={"base": parts.base, "lid": parts.lid},
            output_directory=output_directory,
            repository_root=REPOSITORY_ROOT,
            printer_profile=load_printer_profile(PRINTER_PROFILE),
            parameters={"board": board.identifier, "wall": DESIGN.wall_mm},
        )
    )


def fixture_file(board_file: Path, output_directory: Path) -> Path:
    """A fixture file probing every top-side test point, from the template."""

    data: dict[str, Any] = fixture_template(board_file)
    data["identifier"] = "SENSOR_BOARD_FIXTURE"
    data["name"] = "Sensor board test fixture (example)"
    data["source"] = "EXAMPLE ONLY: the KiCad example's sample board"
    path = output_directory / "fixture.json"
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    return path


def export_fixture(
    path: Path, output_directory: Path
) -> tuple[PcbFixture, ExportResult]:
    profile = load_printer_profile(PRINTER_PROFILE)
    report = check_fixture_file(path, profile)

    if not report.valid:
        raise ValueError(f"The fixture cannot be built: {list(report.errors)}")

    spec = load_fixture(path)
    board = load_fixture_board(spec)
    fixture = build_fixture(spec, board, probed_points(spec, board), profile)
    require_fits_bed(fixture, profile)
    result = export_parts(
        ExportRequest(
            design_name="sensor-board-fixture",
            design_type="fixture",
            parts=print_oriented(fixture),
            output_directory=output_directory,
            repository_root=REPOSITORY_ROOT,
            printer_profile=profile,
            parameters={"pins": len(fixture.plan.points)},
        )
    )

    return fixture, result


def main(
    output_directory: Path,
) -> tuple[Path, ExportResult, PcbFixture, ExportResult]:
    output_directory.mkdir(parents=True, exist_ok=True)
    board_file = import_board(output_directory)
    enclosure = export_enclosure(board_file, output_directory / "enclosure")
    fixture, exported = export_fixture(
        fixture_file(board_file, output_directory), output_directory / "fixture"
    )

    return board_file, enclosure, fixture, exported


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPOSITORY_ROOT / "exports/kicad-board"
    )
    board_file, enclosure, fixture, exported = main(target)

    print(f"board file {board_file}")
    for part in (*enclosure.parts, *exported.parts):
        print(f"{part.step_path}\n{part.stl_path}")
    print(
        f"fixture {'passed' if fixture.passed else 'FAILED'} its checks, "
        f"{len(fixture.plan.points)} pins"
    )
