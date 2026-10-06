"""zcad-validation capture template and check: a caliper capture of a device or an object.

``capture`` is the name; ``wearable``, the name it had while only wearable housings used captures,
is kept as an alias so scripts and notes that use it still work.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.hardware.wearables import (
    CUSTOM,
    DEVICES,
    capture_template,
    check_capture,
    load_capture,
)


def _wearable_check(args: argparse.Namespace) -> int:
    """Check a caliper capture: refuse what cannot be right, warn of what
    probably is not, and show the sizes a candidate would be built from."""

    check = check_capture(args.file)
    payload: dict[str, object] = {
        "file": str(args.file),
        "valid": check.valid,
        "errors": list(check.errors),
        "warnings": list(check.warnings),
    }

    if check.valid:
        capture = load_capture(args.file)
        payload["sha256"] = capture.sha256
        payload["device"] = capture.device
        payload["name"] = capture.name
        payload["outline"] = (
            "rectangle"
            if capture.outline_radius_mm is None
            else f"rounded rectangle, {capture.outline_radius_mm:g} mm corners"
        )
        payload["face_features"] = [
            f"{feature.identifier} ({feature.width_mm:g} x {feature.depth_mm:g} mm)"
            for feature in capture.face_features
        ]
        payload["mass_g"] = capture.mass_g
        payload["body_mm"] = {
            "length": capture.length_mm,
            "width": capture.width_mm,
            "thickness": capture.thickness_mm,
        }
        payload["edge_features"] = [
            f"{feature.identifier} on the {feature.edge} edge"
            for feature in capture.edge_features
        ]

    emit(payload)

    return 0 if check.valid else 1


def _wearable_template(args: argparse.Namespace) -> int:
    """Print an example capture to fill in, or write it."""

    template = capture_template(args.device)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the capture commands, also named ``wearable``, to the zcad-validation parser."""

    capture = subcommands.add_parser(
        "capture",
        aliases=["wearable"],
        help="check a caliper capture of a device or an object, or write one to fill in",
    )
    commands = capture.add_subparsers(dest="capture_command", required=True)
    check = commands.add_parser(
        "check", help="check a caliper capture; exits 1 if it cannot be used"
    )
    check.add_argument("file", type=Path)
    check.set_defaults(handler=_wearable_check)
    template = commands.add_parser(
        "template", help="print an example caliper capture to fill in"
    )
    template.add_argument("--device", required=True, choices=[*sorted(DEVICES), CUSTOM])
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_wearable_template)
