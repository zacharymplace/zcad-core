"""zcad-validation target register."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    emit,
    now,
)
from zcad_core.retention import (
    ValidationTarget,
    sha256_file,
    write_immutable_manifest,
)


def _target_register(args: argparse.Namespace) -> int:
    target = ValidationTarget(
        schema_version="1.0.0",
        target_id=args.target_id,
        display_name=args.display_name,
        manufacturer=args.manufacturer,
        product_family=args.product_family,
        source_model_path=str(args.source_model_path),
        source_model_sha256=sha256_file(args.source_model_path),
        pcb_solid_index=args.pcb_solid_index,
        created_at_utc=(args.created_at_utc or now()),
    )

    write_immutable_manifest(
        target,
        output_path=args.output,
    )

    emit(
        {
            "target_id": target.target_id,
            "source_model_sha256": target.source_model_sha256,
            "manifest": str(args.output),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the target commands to the zcad-validation parser."""

    target = subcommands.add_parser("target")
    target_commands = target.add_subparsers(dest="subcommand", required=True)

    target_register = target_commands.add_parser("register")
    target_register.add_argument("--target-id", required=True)
    target_register.add_argument("--display-name", required=True)
    target_register.add_argument("--manufacturer", required=True)
    target_register.add_argument("--product-family", required=True)
    target_register.add_argument("--source-model-path", required=True, type=Path)
    target_register.add_argument("--pcb-solid-index", required=True, type=int)
    target_register.add_argument("--created-at-utc")
    target_register.add_argument("--output", required=True, type=Path)
    target_register.set_defaults(handler=_target_register)
