"""zcad-validation stack template, check and build: stackable items."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.stack import build_stack, require_fits_bed
from zcad_core.features.stack_check import check_items
from zcad_core.features.stack_file import (
    check_stack_file,
    load_stack,
    stack_template,
)
from zcad_core.features.stack_profile import (
    PROFILE_KIND,
    check_profile_data,
    profile_template,
    read_profile_file,
)
from zcad_core.profiles import load_printer_profile

DEFAULT_PRINTER_PROFILE = Path("profiles/printers/bambu-lab-a1-mini.json")
FILE_KINDS = (PROFILE_KIND, "stack")


def _stack_template(args: argparse.Namespace) -> int:
    """Print a valid example profile or stack file to copy and edit, or write it."""

    template = (
        profile_template()
        if args.kind == PROFILE_KIND
        else stack_template(args.profile_file)
    )

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _stack_check(args: argparse.Namespace) -> int:
    """Check a profile or a stack file; exits 1 if it cannot be used."""

    data, _ = read_profile_file(args.file)
    kind = data.get("file_kind") if isinstance(data, dict) else None

    if kind == PROFILE_KIND:
        report = check_profile_data(data)
        emit(
            {
                "file": str(args.file),
                "kind": kind,
                "valid": report.valid,
                "errors": list(report.errors),
                "warnings": list(report.warnings),
                "profile": report.summary,
            }
        )

        return 0 if report.valid else 1

    profile = load_printer_profile(args.printer_profile)
    stack = check_stack_file(args.file, profile)
    emit(
        {
            "file": str(args.file),
            "kind": kind,
            "valid": stack.valid,
            "errors": list(stack.errors),
            "warnings": list(stack.warnings),
            "stack": stack.summary,
        }
    )

    return 0 if stack.valid else 1


def _stack_check_stack(args: argparse.Namespace) -> int:
    """Whether one item stacks on another; exits 1 if it does not."""

    profile = load_printer_profile(args.printer_profile)
    report = check_items(args.upper, args.lower, profile)
    emit(
        {
            "stacks": report.stacks,
            "errors": list(report.errors),
            "warnings": list(report.warnings),
            **report.summary,
        }
    )

    return 0 if report.stacks else 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stack_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a stack's items."""

    profile = load_printer_profile(args.printer_profile)
    report = check_stack_file(args.stack_file, profile)

    if not report.valid:
        raise ValueError("The stack cannot be built:\n- " + "\n- ".join(report.errors))

    spec = load_stack(args.stack_file)
    stack = build_stack(spec, profile)

    if not stack.passed:
        failed = sorted(name for name, ok in stack.checks.items() if not ok)
        raise ValueError(f"The stack fails its checks: {failed}")

    require_fits_bed(stack, profile)
    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="stack",
            parts=stack.parts,
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=profile,
            parameters={
                "profile_sha256": spec.profile_sha256,
                "items": [item.name for item in spec.items],
            },
        )
    )
    files = {
        exported.part_name: {
            "step_path": str(exported.step_path),
            "stl_path": str(exported.stl_path),
            "stl_sha256": _sha256(exported.stl_path),
            "bounds_mm": list(exported.bounds_mm),
        }
        for exported in result.parts
    }
    emit(
        {
            "design_name": name,
            "warnings": list(report.warnings),
            "stack": stack.summary,
            "checks": stack.checks,
            "not_claimed": list(stack.notes),
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "parts": files,
        }
    )

    return 0


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the stack commands to the zcad-validation parser."""

    stack = subcommands.add_parser(
        "stack",
        help="build stackable items on a stack profile: bins and baseplates",
    )
    commands = stack.add_subparsers(dest="stack_command", required=True)
    template = commands.add_parser(
        "template", help="print a valid example profile or stack file to edit"
    )
    template.add_argument("--kind", required=True, choices=FILE_KINDS)
    template.add_argument(
        "--profile-file",
        type=Path,
        help="the profile file a stack file names, with its hash",
    )
    template.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    template.set_defaults(handler=_stack_template)
    check = commands.add_parser(
        "check", help="check a profile or stack file; exits 1 if it cannot be used"
    )
    check.add_argument("file", type=Path)
    check.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    check.set_defaults(handler=_stack_check)
    build = commands.add_parser(
        "build", help="build, validate, and export a stack's items"
    )
    build.add_argument("--stack-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    build.set_defaults(handler=_stack_build)
    check_stack = commands.add_parser(
        "check-stack",
        help="check whether one item stacks on another; exits 1 if it does not",
    )
    check_stack.add_argument(
        "--upper",
        required=True,
        help="the item on top: FILE:NAME, or an enclosure's build record for its stack plate",
    )
    check_stack.add_argument(
        "--lower", required=True, help="the item below, as FILE:NAME"
    )
    check_stack.add_argument(
        "--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE
    )
    check_stack.set_defaults(handler=_stack_check_stack)
