"""Whether two group enclosures bolt together: the arguments of the check, and the check."""

from __future__ import annotations

import argparse
import json

from zcad_core.cli._common import emit
from zcad_core.cli.enclosure_group_bays import _bays
from zcad_core.features.enclosure_group import GroupDesign, build_group_enclosure
from zcad_core.features.enclosure_group_join import check_join, check_join_records
from zcad_core.features.enclosure_group_model import JOINT_FACES, PASS_THROUGH_SIDES


def _size(text: str | None) -> tuple[float, float] | None:
    """A ``<width>x<height>`` in millimetres, or ``None``."""

    if text is None:
        return None

    width, _, height = text.partition("x")

    try:
        return float(width), float(height)
    except ValueError:
        raise ValueError(
            f"a pass-through is <width>x<height> in millimetres; got '{text}'"
        ) from None


def _add_joint_arguments(build: argparse.ArgumentParser) -> None:
    build.add_argument(
        "--joint",
        choices=JOINT_FACES,
        default="fractions",
        help=(
            "where the join bolts go: at fractions of the unit's depth (the "
            "default, which mates only units of the same depth), or on the "
            "standard joint face, which mates any two units"
        ),
    )
    build.add_argument(
        "--pass-through",
        help="a cable opening <width>x<height> in the join walls (standard joint)",
    )
    build.add_argument(
        "--pass-through-sides", choices=PASS_THROUGH_SIDES, default="both"
    )


def _check_join(args: argparse.Namespace) -> int:
    """Build two units and say whether the second bolts to the first's right
    wall; exits 1 if it does not."""

    if args.left_record is not None or args.right_record is not None:
        if args.left_record is None or args.right_record is None:
            raise ValueError("give both --left-record and --right-record")

        report = check_join_records(
            json.loads(args.left_record.read_text(encoding="utf-8")),
            json.loads(args.right_record.read_text(encoding="utf-8")),
        )
        emit(
            {
                "passed": report.passed,
                "checks": report.checks,
                "details": report.details,
                "notes": list(report.notes),
            }
        )

        return 0 if report.passed else 1

    if args.left_bays is None or args.right_bays is None:
        raise ValueError(
            "give both --left-bays and --right-bays, or both --left-record and "
            "--right-record"
        )

    units = []

    for side in ("left", "right"):
        design = GroupDesign(
            wall_mm=args.wall_mm,
            floor_mm=args.floor_mm,
            fastener=args.fastener,
            lid_attachment=args.lid,
            joint_face=getattr(args, f"{side}_joint"),
            pass_through_mm=_size(getattr(args, f"{side}_pass_through")),
            pass_through_sides=getattr(args, f"{side}_pass_through_sides"),
        )
        units.append(
            build_group_enclosure(_bays(getattr(args, f"{side}_bays")), design=design)
        )

    report = check_join(units[0], units[1])
    emit(
        {
            "passed": report.passed,
            "checks": report.checks,
            "details": report.details,
            "notes": list(report.notes),
        }
    )

    return 0 if report.passed else 1
