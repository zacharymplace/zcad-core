"""zcad-validation slice check.

The quick check compares the commit a slice records with the current tree,
so any change to the geometry sources calls every slice stale, even one
whose part the change never touched. ``--rebuild`` settles those: for a
slice that recorded how it was built, it builds the part again with today's
code and compares the print-oriented STLs the slicer was given, and the part
STLs, which export byte for byte the same from the same geometry.

Some things no rebuild can clear, so they keep a slice stale whatever the
geometry says: the G-code beside the summary no longer being the one it
records, an input file named on the build's command line (a board file, say)
having changed, and the slicing code or the slicer profiles having changed,
since the same parts then slice to different G-code.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import cadquery as cq

from zcad_core.cli._common import emit
from zcad_core.printing import SliceFreshness, slice_freshness
from zcad_core.printing.provenance import changed_since

SUMMARY_NAME = "slice-summary.json"
RECIPE_SCHEMA_VERSION = "1.0.0"
# Only these build anything; a revision's recipe would revise again.
_BUILD_COMMANDS = (
    ("enclosure", "build"),
    ("enclosure-group", "build"),
    ("coupon", "build"),
)
# What the rebuild leaves out: where it writes, and the work it does not need.
_DROPPED_FLAGS = frozenset({"--slice", "--review"})
_DROPPED_OPTIONS = frozenset({"--output-directory", "--slicer-profile"})
# Changes here alter the G-code from the same parts, so a rebuild cannot clear them.
SLICER_PATHS = ("src/zcad_core/printing/bambu.py", "profiles/slicers")
GCODE_NAME = "plate_1.gcode"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_print_copies(
    directory: Path, name: str, shapes: Mapping[str, cq.Shape]
) -> dict[str, str]:
    """Write each part as the slicer is given it, named as a slice names it."""

    directory.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}

    for part, shape in shapes.items():
        model = directory / f"{name}-{part}.stl"
        cq.exporters.export(shape, str(model))
        written[part] = str(model)

    return written


def _input_files(argv: Sequence[str], working: Path) -> dict[str, str]:
    """The SHA-256 of every file the command line names, such as a board
    file or a bay's ``file=``: they shape the part from outside the sources."""

    found: dict[str, str] = {}

    for argument in argv:
        candidates = []

        if argument.startswith("--"):
            if "=" in argument:
                candidates.append(argument.split("=", 1)[1])
        else:
            candidates.append(argument)
            candidates.extend(
                piece.removeprefix("file=")
                for piece in argument.replace(",", ":").split(":")
                if piece.startswith("file=")
            )

        for candidate in candidates:
            path = Path(candidate)
            full = path if path.is_absolute() else working / path

            if candidate and full.is_file():
                found[candidate] = _sha256(full)

    return found


def rebuild_recipe(
    argv: Sequence[str] | None, part_stls: Mapping[str, Path]
) -> dict[str, Any] | None:
    """How to build a sliced design again: its command line, less where it
    wrote and the slicing, and the SHA-256 of each part STL it made. None for
    a command that cannot be rerun to build the same thing."""

    if argv is None or tuple(argv[:2]) not in _BUILD_COMMANDS:
        return None

    kept: list[str] = []
    skip_value = False

    for argument in argv:
        if skip_value:
            skip_value = False
            continue

        option = argument.split("=", 1)[0]

        if option in _DROPPED_FLAGS:
            continue

        if option in _DROPPED_OPTIONS:
            skip_value = "=" not in argument
            continue

        kept.append(argument)

    return {
        "schema_version": RECIPE_SCHEMA_VERSION,
        "argv": kept,
        "working_directory": str(Path.cwd()),
        "parts": {part: _sha256(path) for part, path in sorted(part_stls.items())},
        "inputs": _input_files(kept, Path.cwd()),
    }


def gcode_freshness(
    summary_path: Path, summary: Mapping[str, Any]
) -> SliceFreshness | None:
    """Stale when the G-code beside the summary is missing or is not the one
    it records; None when it is, or the summary records none."""

    recorded = summary.get("gcode_sha256")

    if not recorded:
        return None

    gcode = summary_path.parent / GCODE_NAME

    if not gcode.is_file() or _sha256(gcode) != recorded:
        return SliceFreshness(
            "stale",
            f"{GCODE_NAME} beside it is missing or is not the G-code this summary "
            "records; slice again",
        )

    return None


def inputs_freshness(summary: Mapping[str, Any]) -> SliceFreshness | None:
    """Stale when a file the build's command line named has changed or gone;
    None when none has, or the slice records none."""

    recipe = summary.get("rebuild")

    if not isinstance(recipe, dict) or not isinstance(recipe.get("inputs"), dict):
        return None

    working = Path(str(recipe.get("working_directory", ".")))
    changed = []

    for name, digest in sorted(recipe["inputs"].items()):
        path = Path(name) if Path(name).is_absolute() else working / name

        if not path.is_file() or _sha256(path) != digest:
            changed.append(name)

    if changed:
        return SliceFreshness(
            "stale",
            "a file the build was made from has changed since; build and slice again",
            tuple(changed),
        )

    return None


def rebuild_freshness(summary: Mapping[str, Any]) -> SliceFreshness:
    """Build the slice's design again and compare its parts with those it
    was sliced from."""

    recipe = summary.get("rebuild")

    if (
        not isinstance(recipe, dict)
        or recipe.get("schema_version") != RECIPE_SCHEMA_VERSION
    ):
        return SliceFreshness(
            "unknown",
            "the slice records no way to rebuild it; slice it again once to record one",
        )

    with tempfile.TemporaryDirectory() as scratch:
        try:
            parts, printed = _rebuilt_parts(recipe, Path(scratch) / "rebuild")
        except (ValueError, OSError) as error:
            return SliceFreshness("unknown", f"the rebuild failed: {error}")

    expected = recipe["parts"]
    changed = sorted(part for part in expected if parts.get(part) != expected[part])

    # What the slicer was given: the print-oriented copies, by file name.
    for model in summary.get("models") or ():
        name = Path(str(model.get("path", ""))).name

        if printed.get(name) != model.get("sha256"):
            changed.append(f"print/{name}")

    if changed:
        return SliceFreshness(
            "stale",
            "rebuilt with today's code, the parts differ; build and slice again",
            tuple(changed),
        )

    return SliceFreshness(
        "current", "rebuilt with today's code, every part is identical"
    )


def _rebuilt_parts(
    recipe: Mapping[str, Any], output: Path
) -> tuple[dict[str, str], dict[str, str]]:
    """Run the recorded build into ``output``: each part's STL SHA-256, and
    each print-oriented copy's, by file name."""

    from zcad_core.cli import main  # the parser lives there; imported late

    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = [*recipe["argv"], "--output-directory", str(output), "--print-copies"]

    with _working_directory(Path(recipe["working_directory"])):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(argv)

        if exit_code != 0 and not stdout.getvalue().strip():
            message = stderr.getvalue().strip() or f"exit code {exit_code}"
            raise ValueError(message.removeprefix("error: "))

        built = json.loads(stdout.getvalue())
        parts = {
            part: _sha256(Path(files["stl"])) for part, files in built["parts"].items()
        }
        printed = {
            Path(path).name: _sha256(Path(path))
            for path in (built.get("print_copies") or {}).values()
        }

        return parts, printed


@contextlib.contextmanager
def _working_directory(path: Path) -> Iterator[None]:
    """Relative paths in a recipe are from where its build ran."""

    previous = Path.cwd()
    os.chdir(path)

    try:
        yield
    finally:
        os.chdir(previous)


def _summaries(paths: list[Path]) -> list[Path]:
    """Each summary named, and every one under each directory named."""

    found: list[Path] = []

    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.rglob(SUMMARY_NAME)))
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(f"No slice summary at {path}")

    if not found:
        raise FileNotFoundError(f"No {SUMMARY_NAME} under {', '.join(map(str, paths))}")

    return found


def _slice_check(args: argparse.Namespace) -> int:
    """Report whether each slice still matches the source that would build
    it now; fails unless every one is current."""

    slices = []
    # Every plate of one build shares its recipe; rebuild it once.
    rebuilt: dict[str, SliceFreshness] = {}

    for path in _summaries(args.paths):
        summary = json.loads(path.read_text(encoding="utf-8"))
        freshness = slice_freshness(summary)
        checked_by = "commit"
        # These no rebuild can clear.
        fixed = gcode_freshness(path, summary) or inputs_freshness(summary)

        if fixed is not None:
            freshness, checked_by = fixed, "files"
        elif args.rebuild and freshness.status != "current":
            key = json.dumps(
                [summary.get("rebuild"), summary.get("models")], sort_keys=True
            )

            if key not in rebuilt:
                rebuilt[key] = rebuild_freshness(summary)

            freshness = rebuilt[key]
            checked_by = "rebuild"
            slicer = changed_since(summary, SLICER_PATHS)

            if freshness.status == "current" and slicer:
                freshness = SliceFreshness(
                    "stale",
                    "the parts are the same, but the slicing code or the slicer "
                    "profiles changed since; slice again",
                    slicer,
                )

        slices.append(
            {"summary": str(path), "checked_by": checked_by, **freshness.as_dict()}
        )

    current = all(entry["status"] == "current" for entry in slices)
    emit({"all_current": current, "slices": slices})

    return 0 if current else 1


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the slice commands to the zcad-validation parser."""

    slice_parser = subcommands.add_parser(
        "slice", help="check sliced plates against the current source"
    )
    commands = slice_parser.add_subparsers(dest="subcommand", required=True)
    check = commands.add_parser(
        "check",
        help=(
            "report whether each slice is current, stale (the geometry changed "
            "since it was sliced), or unknown; exits 1 unless all are current"
        ),
    )
    check.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help=f"{SUMMARY_NAME} files, or directories to search for them",
    )
    check.add_argument(
        "--rebuild",
        action="store_true",
        help=(
            "build again any slice the commit check calls stale, and compare "
            "its parts: slower, about a minute a design, but exact"
        ),
    )
    check.set_defaults(handler=_slice_check)
