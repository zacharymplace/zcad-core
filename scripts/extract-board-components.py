"""Extract a board's component envelopes from its vendor STEP model.

The catalog models a board as its PCB and one USB connector. This writes the
rest of it, as boxes an enclosure must clear, to
``src/zcad_core/hardware/data/board-components/<target>.json``, which the
board's catalog spec loads. The extraction itself is
``zcad_core.hardware.electronics.board_import``, shared with
``zcad-validation board import``; see it for the rules. This adds what a
catalogued board knows and an import cannot:

- the part that is the catalogued USB connector is dropped;
- the spec's thickness and edge overhangs are used; and
- the result is mapped into the spec's frame (centred on the board, the spec's
  width along X and length along Y) by a quarter turn set by hand.

The source model's SHA-256 is recorded; re-run this after replacing a model.
Vendor models live in ``evidence/``, so this needs the evidence checkout.

Usage:
    python scripts/extract-board-components.py [target-id ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zcad_core.features.pcb_mounts import board_hole_pattern
from zcad_core.hardware import BoardSpec, get_board
from zcad_core.hardware.electronics.board_import import (
    Box,
    component_records,
    load_solids,
    merge_boxes,
    part_boxes,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "src/zcad_core/hardware/data/board-components"


@dataclass(frozen=True)
class Source:
    """Where a board's vendor model is, and how it sits in the spec frame."""

    board: str
    step: str
    pcb_solid_index: int
    # Quarter turns (counter-clockwise, seen from above) that take the
    # model's PCB frame to the spec's.
    quarter_turns: int


SOURCES = {
    "adafruit-feather-rp2040": Source(
        board="ADAFRUIT_FEATHER_RP2040",
        step="evidence/adafruit-feather-rp2040/4884 Feather RP2040.step",
        pcb_solid_index=1,
        quarter_turns=1,
    ),
    "arduino-uno-r4-wifi": Source(
        board="ARDUINO_UNO_R4_WIFI",
        step="evidence/arduino-uno-r4-wifi/step/UNO_R4_WIFI.step",
        pcb_solid_index=1,
        quarter_turns=0,
    ),
    "raspberry-pi-pico-2": Source(
        board="RASPBERRY_PI_PICO_2",
        step="evidence/raspberry-pi-pico-2/step/rpi_pico2.step",
        pcb_solid_index=373,
        quarter_turns=2,
    ),
    "raspberry-pi-5": Source(
        board="RASPBERRY_PI_5",
        step="evidence/raspberry-pi-5/step/rpi-5b_no_graphics.step",
        pcb_solid_index=2689,
        quarter_turns=1,
    ),
    "seeed-xiao-esp32s3": Source(
        board="SEEED_XIAO_ESP32_S3",
        step="evidence/seeed-xiao-esp32s3/step/xiao_esp32s3_z_up.step",
        pcb_solid_index=37,
        quarter_turns=1,
    ),
}


def _is_usb(box: Box, board: BoardSpec) -> bool:
    """Whether a box's centre lies in the catalogued USB connector's footprint."""

    connector = board.usb_connector
    half_w, half_l = board.board_width_mm / 2, board.board_length_mm / 2
    cx, cy = (box[0] + box[1]) / 2, (box[2] + box[3]) / 2

    if connector.board_edge in ("negative_y", "positive_y"):
        along, across = cx - connector.center_offset_mm, cy
        edge = half_l
    else:
        along, across = cy - connector.center_offset_mm, cx
        edge = half_w

    toward = across if connector.board_edge.startswith("positive") else -across

    return abs(along) <= connector.width_mm / 2 and toward >= edge - connector.depth_mm


def extract(target: str) -> dict[str, Any]:
    source = SOURCES[target]
    board = get_board(source.board)
    step = REPOSITORY_ROOT / source.step
    above, below = part_boxes(
        load_solids(step),
        source.pcb_solid_index,
        board.board_thickness_mm,
        source.quarter_turns,
    )

    usb = [box for box in above if _is_usb(box, board)]

    if not usb:
        raise ValueError(f"{target}: no part matches the catalogued USB connector")

    above = [box for box in above if not _is_usb(box, board)]
    pattern = board_hole_pattern(board)
    holes = pattern.positions if pattern is not None else ()
    diameter = pattern.hole_diameter_mm if pattern is not None else 0.0
    boxes = merge_boxes(above, True, holes, hole_diameter_mm=diameter) + merge_boxes(
        below, False, holes, hole_diameter_mm=diameter
    )

    return {
        "schema_version": "1.0.0",
        "board": board.identifier,
        "source_model_path": source.step,
        "source_model_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
        "pcb_solid_index": source.pcb_solid_index,
        "generated_by": "scripts/extract-board-components.py",
        "components": component_records(
            boxes, board.board_width_mm, board.board_length_mm
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", metavar="target-id")
    args = parser.parse_args()
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    unknown = sorted(set(args.targets) - set(SOURCES))

    if unknown:
        parser.error(
            f"unknown target: {', '.join(unknown)}; known: {', '.join(SOURCES)}"
        )

    for target in args.targets or SOURCES:
        record = extract(target)
        path = OUTPUT_DIRECTORY / f"{target}.json"
        path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"{path.relative_to(REPOSITORY_ROOT)}: {len(record['components'])} parts")


if __name__ == "__main__":
    main()
