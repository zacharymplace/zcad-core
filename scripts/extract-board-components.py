"""Extract a board's component envelopes from its vendor STEP model.

The catalog models a board as its PCB and one USB connector. This writes the
rest of it, as boxes an enclosure must clear, to
``src/zcad_core/hardware/data/board-components/<target>.json``, which the
board's catalog spec loads. For each vendor model it:

- keeps every part rising more than 0.5 mm above the board or reaching
  that far below it, and drops the part that is the catalogued USB connector;
- splits a part through the board into a box above it and one below it;
- merges parts of a similar height lying within 2 mm of each other, so a
  tall header does not swallow the low parts around it;
- marks a part that overhangs a board edge as needing access through that
  edge, like a barrel jack; and
- maps the result into the catalog spec's frame: centred on the board, the
  spec's width along X and length along Y.

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

import cadquery as cq

from zcad_core.hardware import BoardSpec, get_board

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIRECTORY = REPOSITORY_ROOT / "src/zcad_core/hardware/data/board-components"
MINIMUM_HEIGHT_MM = 0.5
MERGE_GAP_MM = 2.0
OVERHANG_MM = 0.3
# Parts are merged only with parts in the same height tier (mm above board).
HEIGHT_TIERS_MM = (1.5, 4.0)


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
    "seeed-xiao-esp32s3": Source(
        board="SEEED_XIAO_ESP32_S3",
        step="evidence/seeed-xiao-esp32s3/step/xiao_esp32s3_z_up.step",
        pcb_solid_index=37,
        quarter_turns=1,
    ),
}

Box = tuple[float, float, float, float, float, float]  # x0 x1 y0 y1 z0 z1


def _turn(box: Box, turns: int) -> Box:
    x0, x1, y0, y1, z0, z1 = box

    for _ in range(turns % 4):
        x0, x1, y0, y1 = -y1, -y0, x0, x1

    return x0, x1, y0, y1, z0, z1


def _tier(box: Box) -> int:
    return sum(box[5] > limit for limit in HEIGHT_TIERS_MM)


def _touching(a: Box, b: Box) -> bool:
    return (
        a[0] - MERGE_GAP_MM <= b[1]
        and b[0] - MERGE_GAP_MM <= a[1]
        and a[2] - MERGE_GAP_MM <= b[3]
        and b[2] - MERGE_GAP_MM <= a[3]
    )


def _merge(boxes: list[Box], same_tier: bool) -> list[Box]:
    merged = list(boxes)
    changed = True

    while changed:
        changed = False

        for i, a in enumerate(merged):
            for j in range(i + 1, len(merged)):
                b = merged[j]

                if _touching(a, b) and (not same_tier or _tier(a) == _tier(b)):
                    merged[i] = (
                        min(a[0], b[0]),
                        max(a[1], b[1]),
                        min(a[2], b[2]),
                        max(a[3], b[3]),
                        min(a[4], b[4]),
                        max(a[5], b[5]),
                    )
                    del merged[j]
                    changed = True
                    break

            if changed:
                break

    return sorted(merged)


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


def _access_edge(box: Box, board: BoardSpec) -> str | None:
    half_w, half_l = board.board_width_mm / 2, board.board_length_mm / 2
    overhangs = {
        "negative_x": -half_w - box[0],
        "positive_x": box[1] - half_w,
        "negative_y": -half_l - box[2],
        "positive_y": box[3] - half_l,
    }
    edge, overhang = max(overhangs.items(), key=lambda item: item[1])

    return edge if overhang > OVERHANG_MM else None


def extract(target: str) -> dict[str, Any]:
    source = SOURCES[target]
    board = get_board(source.board)
    step = REPOSITORY_ROOT / source.step
    solids = [
        solid
        for solid in cq.importers.importStep(str(step)).solids().vals()
        if isinstance(solid, cq.Shape)
    ]
    pcb = solids[source.pcb_solid_index - 1].BoundingBox()
    centre_x, centre_y = (pcb.xmin + pcb.xmax) / 2, (pcb.ymin + pcb.ymax) / 2
    above: list[Box] = []
    below: list[Box] = []

    for index, solid in enumerate(solids, start=1):
        if index == source.pcb_solid_index:
            continue

        b = solid.BoundingBox()
        # Heights above the model's board top; depths below its underside
        # re-based on the spec's thickness.
        x0, x1, y0, y1, _, _ = _turn(
            (
                b.xmin - centre_x,
                b.xmax - centre_x,
                b.ymin - centre_y,
                b.ymax - centre_y,
                0,
                0,
            ),
            source.quarter_turns,
        )
        top = b.zmax - pcb.zmax
        bottom = b.zmin - pcb.zmin

        if top > MINIMUM_HEIGHT_MM:
            above.append((x0, x1, y0, y1, max(b.zmin - pcb.zmax, 0.0), top))

        if bottom < -MINIMUM_HEIGHT_MM:
            thickness = board.board_thickness_mm
            below.append(
                (
                    x0,
                    x1,
                    y0,
                    y1,
                    bottom - thickness,
                    min(b.zmax - pcb.zmin, 0) - thickness,
                )
            )

    usb = [box for box in above if _is_usb(box, board)]

    if not usb:
        raise ValueError(f"{target}: no part matches the catalogued USB connector")

    above = [box for box in above if not _is_usb(box, board)]
    boxes = _merge(above, same_tier=True) + _merge(below, same_tier=False)
    components = []

    for number, (x0, x1, y0, y1, z0, z1) in enumerate(boxes, start=1):
        box = (x0, x1, y0, y1, z0, z1)
        components.append(
            {
                "identifier": f"{'top' if z0 >= 0 else 'bottom'}-{number:02d}",
                "center_x_mm": round((x0 + x1) / 2, 3),
                "center_y_mm": round((y0 + y1) / 2, 3),
                "width_mm": round(x1 - x0, 3),
                "depth_mm": round(y1 - y0, 3),
                "bottom_offset_from_board_top_mm": round(z0, 3),
                "height_mm": round(z1 - z0, 3),
                "access_edge": _access_edge(box, board),
            }
        )

    return {
        "schema_version": "1.0.0",
        "board": board.identifier,
        "source_model_path": source.step,
        "source_model_sha256": hashlib.sha256(step.read_bytes()).hexdigest(),
        "pcb_solid_index": source.pcb_solid_index,
        "generated_by": "scripts/extract-board-components.py",
        "components": components,
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
