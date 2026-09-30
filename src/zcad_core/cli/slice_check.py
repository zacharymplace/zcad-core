"""zcad-validation slice check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.printing import slice_freshness

SUMMARY_NAME = "slice-summary.json"


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

    for path in _summaries(args.paths):
        summary = json.loads(path.read_text(encoding="utf-8"))
        slices.append({"summary": str(path), **slice_freshness(summary).as_dict()})

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
    check.set_defaults(handler=_slice_check)
