"""zcad-validation thermal derive."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.profiles import derive_thermal_profile, write_thermal_profile
from zcad_core.profiles.thermal import DEFAULT_MINIMUM_TRIALS


def _thermal_derive(args: argparse.Namespace) -> int:
    """Pool the recorded thermal trials into the next version of a profile."""

    output = (
        args.output or Path("profiles/thermal") / f"{args.material_profile_id}.json"
    )
    previous = (
        json.loads(output.read_text(encoding="utf-8")) if output.exists() else None
    )
    profile = derive_thermal_profile(
        args.evidence_root,
        material_profile_id=args.material_profile_id,
        minimum_trials=args.minimum_trials,
        previous=previous,
    )
    write_thermal_profile(profile, output)
    emit(
        {
            "profile": str(output),
            "version": profile["version"],
            "figures": profile["figures"],
            "ventilated": profile["ventilated"],
            "deformation": profile["deformation"],
            "trials": len(profile["sources"]),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the thermal commands to the zcad-validation parser."""

    thermal = subcommands.add_parser(
        "thermal", help="pool thermal trials into a material's measured profile"
    )
    commands = thermal.add_subparsers(dest="subcommand", required=True)
    derive = commands.add_parser(
        "derive", help="write the next version of a thermal profile"
    )
    derive.add_argument("--evidence-root", type=Path, default=Path("evidence"))
    derive.add_argument("--material-profile-id", default="petg")
    derive.add_argument("--minimum-trials", type=int, default=DEFAULT_MINIMUM_TRIALS)
    derive.add_argument(
        "--output", type=Path, help="defaults to profiles/thermal/<material>.json"
    )
    derive.set_defaults(handler=_thermal_derive)
