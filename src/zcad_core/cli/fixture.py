"""zcad-validation fixture export."""

from __future__ import annotations

import argparse
from pathlib import Path

from zcad_core.cli._common import (
    add_capture_policy_arguments,
    build_capture_policy,
    corner_keepout,
    emit,
)
from zcad_core.cli.pcb_fixture import add_commands as add_pcb_fixture_commands
from zcad_core.retention import (
    CornerCapturePolicy,
    EdgeCapturePolicy,
    ProductionCornerExecutionRequest,
    ProductionEdgeExecutionRequest,
    ValidationFixturePolicy,
    execute_production_corner_capture,
    execute_production_edge_capture,
    export_edge_validation_fixture,
    export_validation_fixture,
)


def _fixture_export(args: argparse.Namespace) -> int:
    """Re-execute retention geometry and export a printable STL fixture.

    Retention execution results (board model, derivation, geometry) are
    not persisted artifacts on their own - only the STEP and JSON evidence
    ``candidate create`` writes are. Exporting a fixture re-runs the same
    deterministic execution from ``--source-step`` rather than reading
    those files back in, mirroring how the existing per-board generation
    scripts (e.g. scripts/generate-*-physical-validation.py) work.
    """

    policy = build_capture_policy(args)
    corner_options = corner_keepout(args)
    fixture_policy = ValidationFixturePolicy(
        base_thickness_mm=args.base_thickness_mm,
        perimeter_margin_mm=args.perimeter_margin_mm,
    )

    if args.strategy == "corner-capture":
        assert isinstance(policy, CornerCapturePolicy)
        execution = execute_production_corner_capture(
            ProductionCornerExecutionRequest(
                source_step=args.source_step,
                pcb_solid_index=args.pcb_solid_index,
                output_step=args.output_step,
                policy=policy,
                **corner_options,
            )
        )
        fixture = export_validation_fixture(
            execution,
            output_path=args.output,
            policy=fixture_policy,
        )
    else:
        assert isinstance(policy, EdgeCapturePolicy)
        edge_execution = execute_production_edge_capture(
            ProductionEdgeExecutionRequest(
                source_step=args.source_step,
                pcb_solid_index=args.pcb_solid_index,
                output_step=args.output_step,
                policy=policy,
            )
        )
        fixture = export_edge_validation_fixture(
            edge_execution,
            output_path=args.output,
            policy=fixture_policy,
        )

    emit(
        {
            "strategy": args.strategy,
            "fixture": str(fixture.stl_path),
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the fixture commands to the zcad-validation parser."""

    fixture = subcommands.add_parser("fixture")
    fixture_commands = fixture.add_subparsers(dest="subcommand", required=True)

    fixture_export = fixture_commands.add_parser("export")
    add_capture_policy_arguments(fixture_export)
    fixture_export.add_argument("--base-thickness-mm", type=float, default=2.0)
    fixture_export.add_argument("--perimeter-margin-mm", type=float, default=2.0)
    fixture_export.add_argument("--output", required=True, type=Path)
    fixture_export.set_defaults(handler=_fixture_export)
    add_pcb_fixture_commands(fixture_commands)
