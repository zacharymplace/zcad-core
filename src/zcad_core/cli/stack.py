"""zcad-validation stack template, check and build: stackable items."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from zcad_core.cli._common import add_compensation_profile_argument, emit
from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.features.enclosure_trial import EnclosureTrialDisposition
from zcad_core.features.layer_trial import (
    complete_layer_trial,
    start_layer_trial,
    write_layer_record,
)
from zcad_core.features.stack import build_stack, require_fits_bed
from zcad_core.features.stack_check import check_items
from zcad_core.features.stack_file import (
    check_stack_file,
    load_stack,
    stack_template,
)
from zcad_core.features.stack_layers import (
    LAYER_KIND,
    build_layer,
    check_layer_file,
    check_layers,
    layer_template,
    load_layer,
    require_layer_fits_bed,
)
from zcad_core.features.stack_profile import (
    PROFILE_KIND,
    check_profile_data,
    profile_template,
    read_profile_file,
)
from zcad_core.features.stack_trial import (
    complete_stack_trial,
    start_stack_trial,
    write_stack_record,
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

    if kind == LAYER_KIND:
        layer = check_layer_file(args.file, load_printer_profile(args.printer_profile))
        emit(
            {
                "file": str(args.file),
                "kind": kind,
                "valid": layer.valid,
                "errors": list(layer.errors),
                "warnings": list(layer.warnings),
                "layer": layer.summary,
            }
        )

        return 0 if layer.valid else 1

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


def _trial_start(args: argparse.Namespace) -> int:
    trial = start_stack_trial(args.build_record)
    files = {
        "trial": str(trial),
        "observations": str(trial / "observations.json"),
        "measurements": str(trial / "measurements.json"),
        "stacking": str(trial / "stacking.json"),
    }

    if (trial / "latch.json").is_file():
        files["latch"] = str(trial / "latch.json")

    emit(files)

    return 0


def _trial_complete(args: argparse.Namespace) -> int:
    record = complete_stack_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
        }
    )

    return 0


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


def _layer_template(args: argparse.Namespace) -> int:
    """Print a valid example layer file to copy and edit, or write it."""

    template = layer_template(args.board_file)

    if args.output is None:
        emit(template)

        return 0

    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
    emit({"written": str(args.output)})

    return 0


def _layer_build(args: argparse.Namespace) -> int:
    """Build, validate, and export a layer's plate and spacer."""

    printer = load_printer_profile(args.printer_profile)
    report = check_layer_file(args.layer_file, printer)

    if not report.valid:
        raise ValueError("The layer cannot be built:\n- " + "\n- ".join(report.errors))

    spec = load_layer(args.layer_file)
    layer = build_layer(spec, printer)

    if not layer.passed:
        failed = sorted(name for name, ok in layer.checks.items() if not ok)
        raise ValueError(f"The layer fails its checks: {failed}")

    require_layer_fits_bed(layer, printer)
    name = spec.identifier.lower().replace("_", "-")
    result = export_parts(
        ExportRequest(
            design_name=name,
            design_type="layer",
            parts=layer.parts,
            output_directory=args.output_directory,
            repository_root=Path.cwd(),
            printer_profile=printer,
            parameters={
                "board_sha256": spec.board_sha256,
                "spacer_mm": layer.summary["spacer_mm"],
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
    record = write_layer_record(
        args.output_directory,
        layer=layer,
        design_name=name,
        printer_profile_id=str(printer.get("profile_id", "")),
        part_stls={e.part_name: e.stl_path for e in result.parts},
    )
    emit(
        {
            "design_name": name,
            "build_record": str(record),
            "warnings": list(report.warnings),
            "layer": layer.summary,
            "checks": layer.checks,
            "not_claimed": list(layer.notes),
            "validation_status": (result.validation_report or {}).get(
                "evaluated_status"
            ),
            "parts": files,
        }
    )

    return 0


def _layer_trial_start(args: argparse.Namespace) -> int:
    trial = start_layer_trial(args.build_record)
    emit(
        {
            "trial": str(trial),
            "observations": str(trial / "observations.json"),
            "measurements": str(trial / "measurements.json"),
            "fitting": str(trial / "fitting.json"),
        }
    )

    return 0


def _layer_trial_complete(args: argparse.Namespace) -> int:
    record = complete_layer_trial(
        args.trial_directory,
        disposition=EnclosureTrialDisposition(args.disposition),
        material_profile_id=args.material_profile,
        notes=args.notes,
    )
    emit(
        {
            "trial_record": str(record),
            "passed": json.loads(record.read_text(encoding="utf-8"))["passed"],
        }
    )

    return 0


def _stack_check_layers(args: argparse.Namespace) -> int:
    """Whether the upper layer's board stacks over the lower layer; exits 1 if not."""

    printer = load_printer_profile(args.printer_profile)
    report = check_layers(args.upper, args.lower, printer)
    emit(
        {
            "stacks": report.stacks,
            "errors": list(report.errors),
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
    record = write_stack_record(
        args.output_directory,
        stack=stack,
        design_name=name,
        printer_profile_id=str(profile.get("profile_id", "")),
        part_stls={e.part_name: e.stl_path for e in result.parts},
    )
    emit(
        {
            "design_name": name,
            "build_record": str(record),
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
    add_compensation_profile_argument(check)
    check.set_defaults(handler=_stack_check)
    build = commands.add_parser(
        "build", help="build, validate, and export a stack's items"
    )
    build.add_argument("--stack-file", required=True, type=Path)
    build.add_argument("--output-directory", required=True, type=Path)
    build.add_argument("--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE)
    add_compensation_profile_argument(build)
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
    check_layers_command = commands.add_parser(
        "check-layers",
        help="check whether one layer's board stacks over another layer; exits 1 if not",
    )
    check_layers_command.add_argument("--upper", required=True, type=Path)
    check_layers_command.add_argument("--lower", required=True, type=Path)
    check_layers_command.add_argument(
        "--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE
    )
    check_layers_command.set_defaults(handler=_stack_check_layers)
    layer = commands.add_parser(
        "layer", help="a plate and spacers that stack over a board"
    )
    layer_commands = layer.add_subparsers(dest="layer_command", required=True)
    layer_template_command = layer_commands.add_parser(
        "template", help="print a valid example layer file to edit"
    )
    layer_template_command.add_argument(
        "--board-file", type=Path, help="the board file to name, with its hash"
    )
    layer_template_command.add_argument(
        "--output", type=Path, help="write the example here instead of printing it"
    )
    layer_template_command.set_defaults(handler=_layer_template)
    layer_build = layer_commands.add_parser(
        "build", help="build, validate, and export a layer's plate and spacer"
    )
    layer_build.add_argument("--layer-file", required=True, type=Path)
    layer_build.add_argument("--output-directory", required=True, type=Path)
    layer_build.add_argument(
        "--printer-profile", type=Path, default=DEFAULT_PRINTER_PROFILE
    )
    layer_build.set_defaults(handler=_layer_build)
    trial = commands.add_parser(
        "trial", help="record a print and stacking of a stack's items"
    )
    trial_commands = trial.add_subparsers(dest="trial_command", required=True)
    trial_start = trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and stacking templates",
    )
    trial_start.add_argument("--build-record", required=True, type=Path)
    trial_start.set_defaults(handler=_trial_start)
    trial_complete = trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    trial_complete.add_argument("--trial-directory", required=True, type=Path)
    trial_complete.add_argument(
        "--disposition",
        required=True,
        choices=[disposition.value for disposition in EnclosureTrialDisposition],
    )
    trial_complete.add_argument("--material-profile", default="petg")
    trial_complete.add_argument("--notes", default="")
    trial_complete.set_defaults(handler=_trial_complete)
    layer_trial = layer_commands.add_parser(
        "trial", help="record a print of a layer and its fit to a board"
    )
    layer_trial_commands = layer_trial.add_subparsers(
        dest="layer_trial_command", required=True
    )
    layer_trial_start = layer_trial_commands.add_parser(
        "start",
        help="write the next trial's observation, measurement and fitting templates",
    )
    layer_trial_start.add_argument("--build-record", required=True, type=Path)
    layer_trial_start.set_defaults(handler=_layer_trial_start)
    layer_trial_complete = layer_trial_commands.add_parser(
        "complete", help="validate a filled-in trial and write its record"
    )
    layer_trial_complete.add_argument("--trial-directory", required=True, type=Path)
    layer_trial_complete.add_argument(
        "--disposition",
        required=True,
        choices=[disposition.value for disposition in EnclosureTrialDisposition],
    )
    layer_trial_complete.add_argument("--material-profile", default="petg")
    layer_trial_complete.add_argument("--notes", default="")
    layer_trial_complete.set_defaults(handler=_layer_trial_complete)
