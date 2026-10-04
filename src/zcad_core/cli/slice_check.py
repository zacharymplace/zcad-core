"""zcad-validation slice check.

The quick check compares the commit a slice records with the current tree,
so any change to the geometry sources calls every slice stale, even one
whose part the change never touched. ``--rebuild`` settles those: for a
slice that recorded how it was built, it builds the part again with today's
code and compares the part STLs, which export byte for byte the same from
the same geometry.
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

from zcad_core.cli._common import emit
from zcad_core.printing import SliceFreshness, slice_freshness

SUMMARY_NAME = "slice-summary.json"
RECIPE_SCHEMA_VERSION = "1.0.0"
# Only these build anything; a revision's recipe would revise again.
_BUILD_COMMANDS = (("enclosure", "build"), ("enclosure-group", "build"))
# What the rebuild leaves out: where it writes, and the work it does not need.
_DROPPED_FLAGS = frozenset({"--slice", "--review"})
_DROPPED_OPTIONS = frozenset({"--output-directory", "--slicer-profile"})


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
        "parts": {
            part: hashlib.sha256(path.read_bytes()).hexdigest()
            for part, path in sorted(part_stls.items())
        },
    }


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
            parts = _rebuilt_parts(recipe, Path(scratch) / "rebuild")
        except (ValueError, OSError) as error:
            return SliceFreshness("unknown", f"the rebuild failed: {error}")

    expected = recipe["parts"]
    changed = tuple(
        sorted(part for part in expected if parts.get(part) != expected[part])
    )

    if changed:
        return SliceFreshness(
            "stale",
            "rebuilt with today's code, the parts differ; build and slice again",
            changed,
        )

    return SliceFreshness(
        "current", "rebuilt with today's code, every part is identical"
    )


def _rebuilt_parts(recipe: Mapping[str, Any], output: Path) -> dict[str, str]:
    """Run the recorded build into ``output``; each part's STL SHA-256."""

    from zcad_core.cli import main  # the parser lives there; imported late

    stdout = io.StringIO()
    stderr = io.StringIO()
    argv = [*recipe["argv"], "--output-directory", str(output)]

    with _working_directory(Path(recipe["working_directory"])):
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = main(argv)

        if exit_code != 0 and not stdout.getvalue().strip():
            message = stderr.getvalue().strip() or f"exit code {exit_code}"
            raise ValueError(message.removeprefix("error: "))

        built = json.loads(stdout.getvalue())

        return {
            part: hashlib.sha256(Path(files["stl"]).read_bytes()).hexdigest()
            for part, files in built["parts"].items()
        }


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

        if args.rebuild and freshness.status != "current":
            key = json.dumps(summary.get("rebuild"), sort_keys=True)

            if key not in rebuilt:
                rebuilt[key] = rebuild_freshness(summary)

            freshness = rebuilt[key]
            checked_by = "rebuild"

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
