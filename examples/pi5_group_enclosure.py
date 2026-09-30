"""Design and export one enclosure for a row of Raspberry Pi 5 boards.

This walks the group enclosure builder end to end, from Python:

1. Describe the row as bays, left to right. Here the first bay holds a Pi 5
   now, and the second keeps a place for one, so a second Pi drops in later
   with no reprint. A divider stands between them, with vents, a notch for a
   header ribbon, and slots for zip ties.
2. Build the base and lid. The builder refuses a row whose features would cut
   or run into one another, and returns fit checks: the base and lid do not
   touch, each Pi's envelope clears both, and each part is one solid.
3. Export both parts through the validated pipeline: STEP, STL, and per-part
   metadata, published only if geometry validation passes.
4. Write the data and page for the interactive 3D viewer beside them.

Run from the repository root:

    python examples/pi5_group_enclosure.py [output-directory]

The same enclosure, and its print, come from the command line with::

    zcad-validation enclosure-group build \\
      --bays "pi5,reserved:divider=vents+notch+ties" --slice \\
      --output-directory exports/pi5-group-example

The default output directory is ``exports/pi5-group-example`` (ignored by
git). The gate runs this example (``tests/test_examples.py``) so it stays
current.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from zcad_core.exporters import ExportRequest, ExportResult, export_parts
from zcad_core.features.enclosure_group import (
    Bay,
    BayLike,
    GroupDesign,
    GroupEnclosure,
    build_group_enclosure,
)
from zcad_core.features.enclosure_group_dividers import Divider
from zcad_core.features.enclosure_group_viewer import (
    DATA_FILE,
    PAGE_FILE,
    ViewerConfig,
    viewer_data,
    viewer_page,
)
from zcad_core.profiles import load_printer_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PRINTER_PROFILE = REPOSITORY_ROOT / "profiles/printers/bambu-lab-a1-mini.json"

# The command-line spelling of BAYS, so the two cannot drift apart.
BAYS_SPEC = "pi5,reserved:divider=vents+notch+ties"
BAYS: tuple[BayLike, ...] = (
    "pi5",
    Bay("reserved", divider=Divider(vents=True, notch=True, tie_slots=True)),
)
# Everything else is the builder's default: M3 lid screws into heat-set
# inserts, 4 mm standoffs, and 18 mm above the board, which clears an Active
# Cooler and the USB stack. Raise headroom_mm, or give a bay its own, for a HAT.
DESIGN = GroupDesign()


def enclosure() -> GroupEnclosure:
    """Build the enclosure and refuse it if a fit check fails."""

    group = build_group_enclosure(BAYS, design=DESIGN)

    if not group.passed:
        failed = sorted(name for name, ok in group.checks.items() if not ok)
        raise ValueError(f"The enclosure fails its checks: {failed}")

    return group


def main(output_directory: Path) -> tuple[ExportResult, GroupEnclosure, Path]:
    group = enclosure()
    result = export_parts(
        ExportRequest(
            design_name="pi5-group-example",
            design_type="enclosure",
            parts={"base": group.base, "lid": group.lid},
            output_directory=output_directory,
            repository_root=REPOSITORY_ROOT,
            printer_profile=load_printer_profile(PRINTER_PROFILE),
            parameters={
                "bays": BAYS_SPEC,
                "wall": DESIGN.wall_mm,
                "headroom": DESIGN.headroom_mm,
            },
        )
    )

    viewer = output_directory / "viewer"
    viewer.mkdir()
    configs = (ViewerConfig("example", "This row", "Built by the example.", BAYS),)
    (viewer / DATA_FILE).write_text(
        json.dumps(viewer_data(configs), separators=(",", ":")), encoding="utf-8"
    )
    (viewer / PAGE_FILE).write_text(viewer_page(standalone=True), encoding="utf-8")

    return result, group, viewer


if __name__ == "__main__":
    target = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else REPOSITORY_ROOT / "exports/pi5-group-example"
    )
    result, group, viewer = main(target)
    width, depth, height = group.outer_size_mm

    for part in result.parts:
        print(f"{part.step_path}\n{part.stl_path}\n{part.metadata_path}")
    print(f"{width:g} x {depth:g} x {height:g} mm, checks {group.checks}")
    print(f"view it: python3 -m http.server --directory {viewer}")
