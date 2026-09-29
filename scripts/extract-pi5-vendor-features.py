"""Extract the Pi 5's orientation anchors from Raspberry Pi's STEP model.

Writes ``tests/data/raspberry-pi-5-vendor-features.json``: the centre of the
Ethernet jack, the two USB stacks, the 40-pin header, the USB-C connector, and
the microSD slot, in the vendor model's own frame. The tests use them to check
that the Pi 5 spec and the enclosure envelope are not mirrored or turned: the
model shows the board from above, its components up, and only a proper
rotation takes it into the spec's frame.

The frame written is the model's: X along the 85 mm edge, Y along the 56 mm
edge, Z up, origin at the PCB centre, heights measured from the PCB top. The
source model's SHA-256 is recorded; re-run this after replacing the model.
Vendor models live in ``evidence/``, so this needs the evidence checkout.

Usage:
    python scripts/extract-pi5-vendor-features.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cadquery as cq

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STEP = "evidence/raspberry-pi-5/step/rpi-5b_no_graphics.step"
OUTPUT = REPOSITORY_ROOT / "tests/data/raspberry-pi-5-vendor-features.json"
BOARD_LENGTH_MM = 85.0
BOARD_THICKNESS_LIMIT_MM = 2.5
# A part is a tall connector above this height over the PCB; the Ethernet jack
# is the one whose footprint runs past ETHERNET_LENGTH_MM.
TALL_MM = 12.0
ETHERNET_LENGTH_MM = 20.0
# The GPIO header's pins are 0.64 mm square and rise above HEADER_TOP_MM; the
# board's second, 2x2 header sits within HEADER_ROW_MM of the centre line.
HEADER_PIN_MM = 1.0
HEADER_TOP_MM = 8.0
HEADER_ROW_MM = 20.0
# USB-C: a low shell about 9 x 7 mm near the edge.
USB_C_WIDTH_MM = (8.0, 10.0)
USB_C_DEPTH_MM = (6.0, 8.0)
USB_C_TOP_MM = (3.0, 3.6)
# The microSD slot hangs under the board and is over 8 mm wide.
BELOW_MM = -1.0
SD_MINIMUM_WIDTH_MM = 8.0


def _bounds(solids: list[cq.Shape]) -> list[cq.BoundBox]:
    return [solid.BoundingBox() for solid in solids]


def _union(boxes: list[cq.BoundBox]) -> tuple[float, float, float, float, float, float]:
    return (
        min(b.xmin for b in boxes),
        max(b.xmax for b in boxes),
        min(b.ymin for b in boxes),
        max(b.ymax for b in boxes),
        min(b.zmin for b in boxes),
        max(b.zmax for b in boxes),
    )


def _feature(
    name: str,
    boxes: list[cq.BoundBox],
    centre: tuple[float, float],
    pcb: cq.BoundBox,
) -> dict[str, Any]:
    if not boxes:
        raise ValueError(f"{name}: no matching part in the vendor model")

    x0, x1, y0, y1, z0, z1 = _union(boxes)
    overhang = max(0.0, pcb.xmin - x0, x1 - pcb.xmax, pcb.ymin - y0, y1 - pcb.ymax)

    return {
        "name": name,
        "x_mm": round((x0 + x1) / 2 - centre[0], 3),
        "y_mm": round((y0 + y1) / 2 - centre[1], 3),
        "top_mm": round(z1 - pcb.zmax, 3),
        "bottom_mm": round(z0 - pcb.zmin, 3),
        "edge_overhang_mm": round(overhang, 3),
        "parts": len(boxes),
    }


def extract(step: Path) -> dict[str, Any]:
    solids = [
        solid
        for solid in cq.importers.importStep(str(step)).solids().vals()
        if isinstance(solid, cq.Shape)
    ]
    boxes = _bounds(solids)
    boards = [
        i
        for i, b in enumerate(boxes)
        if abs(max(b.xlen, b.ylen) - BOARD_LENGTH_MM) < 1.5
        and min(b.xlen, b.ylen, b.zlen) < BOARD_THICKNESS_LIMIT_MM
    ]

    if len(boards) != 1:
        raise ValueError(f"Expected one PCB solid, found {len(boards)}")

    pcb = boxes[boards[0]]
    centre = ((pcb.xmin + pcb.xmax) / 2, (pcb.ymin + pcb.ymax) / 2)
    others = [b for i, b in enumerate(boxes) if i != boards[0]]

    def top(b: cq.BoundBox) -> float:
        return b.zmax - pcb.zmax

    def y_from_centre(b: cq.BoundBox) -> float:
        return (b.ymin + b.ymax) / 2 - centre[1]

    tall = [b for b in others if top(b) > TALL_MM]
    ethernet = [b for b in tall if max(b.xlen, b.ylen) > ETHERNET_LENGTH_MM]
    stacks = sorted(
        (b for b in tall if max(b.xlen, b.ylen) <= ETHERNET_LENGTH_MM),
        key=lambda b: (b.ymin + b.ymax) / 2,
    )

    if len(stacks) != 2:
        raise ValueError(f"Expected two USB stacks, found {len(stacks)}")

    header = [
        b
        for b in others
        if max(b.xlen, b.ylen) < HEADER_PIN_MM
        and top(b) > HEADER_TOP_MM
        and abs(y_from_centre(b)) > HEADER_ROW_MM
    ]
    usb_c = [
        b
        for b in others
        if USB_C_WIDTH_MM[0] < b.xlen < USB_C_WIDTH_MM[1]
        and USB_C_DEPTH_MM[0] < b.ylen < USB_C_DEPTH_MM[1]
        and USB_C_TOP_MM[0] < top(b) < USB_C_TOP_MM[1]
        and y_from_centre(b) < -HEADER_ROW_MM
    ]
    sd = [
        b
        for b in others
        if b.zmin - pcb.zmin < BELOW_MM and b.xlen > SD_MINIMUM_WIDTH_MM
    ]
    features = [
        _feature("ethernet", ethernet, centre, pcb),
        _feature("usb_stack_1", [stacks[0]], centre, pcb),
        _feature("usb_stack_2", [stacks[1]], centre, pcb),
        _feature("gpio_header", header, centre, pcb),
        _feature("usb_c", usb_c, centre, pcb),
        _feature("micro_sd", sd, centre, pcb),
    ]

    return {
        "schema_version": "1.0.0",
        "frame": (
            "vendor model, seen from above: X along the 85 mm edge, Y along the "
            "56 mm edge, Z up; origin at the PCB centre; heights from the PCB"
        ),
        "source_model_path": STEP,
        "source_model_sha256": hashlib.sha256(
            (REPOSITORY_ROOT / STEP).read_bytes()
        ).hexdigest(),
        "generated_by": "scripts/extract-pi5-vendor-features.py",
        "board_mm": [round(pcb.xlen, 3), round(pcb.ylen, 3), round(pcb.zlen, 3)],
        "features": features,
    }


def main() -> None:
    record = extract(REPOSITORY_ROOT / STEP)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"{OUTPUT.relative_to(REPOSITORY_ROOT)}: {len(record['features'])} features")


if __name__ == "__main__":
    main()
