"""zcad-validation compensation derive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.profiles import derive_compensation_profile, write_compensation_profile
from zcad_core.profiles.compensation import DEFAULT_MINIMUM_TRIALS


def _compensation_derive(args: argparse.Namespace) -> int:
    """Pool the recorded trials into the next version of a profile."""

    output = args.output or (
        Path("profiles/compensation")
        / f"{args.printer_profile_id}-{args.material_profile_id}.json"
    )
    previous = (
        json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    )
    profile = derive_compensation_profile(
        args.evidence_root,
        printer_profile_id=args.printer_profile_id,
        material_profile_id=args.material_profile_id,
        minimum_trials=args.minimum_trials,
        previous=previous,
    )
    write_compensation_profile(profile, output)
    emit(
        {
            "profile": str(output),
            "version": profile["version"],
            "figures": profile["figures"],
            "trials": len(profile["sources"]),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the compensation commands to the zcad-validation parser."""

    compensation = subcommands.add_parser(
        "compensation", help="pool trials into printer and material profiles"
    )
    commands = compensation.add_subparsers(dest="subcommand", required=True)
    derive = commands.add_parser(
        "derive", help="write the next version of a compensation profile"
    )
    derive.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    derive.add_argument("--printer-profile-id", default="bambu-lab-a1-mini")
    derive.add_argument("--material-profile-id", default="petg")
    derive.add_argument("--minimum-trials", type=int, default=DEFAULT_MINIMUM_TRIALS)
    derive.add_argument(
        "--output",
        type=Path,
        help="defaults to profiles/compensation/<printer>-<material>.json",
    )
    derive.set_defaults(handler=_compensation_derive)
