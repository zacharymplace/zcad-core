"""zcad-validation export verify.

Checks that the STEP and STL beside each part's export metadata are still the
bytes that metadata recorded: a handoff copied, synced or unpacked can be
checked before anyone prints from it. It only reads, and it says nothing
about whether the geometry is right or who wrote the files; see
``zcad_core.exporters.verify_artifact_bindings``.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from pathlib import Path

from zcad_core.cli._common import emit
from zcad_core.exporters import verify_artifact_bindings

METADATA_SUFFIX = ".metadata.json"


def _metadata_files(paths: list[Path]) -> list[Path]:
    """Each metadata file named, and every one under each directory named."""

    found: list[Path] = []

    for path in paths:
        if path.is_dir():
            under = sorted(path.rglob(f"*{METADATA_SUFFIX}"))

            if not under:
                raise FileNotFoundError(f"No *{METADATA_SUFFIX} under {path}")

            found.extend(under)
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(f"No export metadata at {path}")

    # A file named twice, or named and also under a directory, is checked once.
    return list(dict.fromkeys(found))


def _export_verify(args: argparse.Namespace) -> int:
    """Report each artifact's byte check; fails unless every one matched."""

    parts = []
    counts: dict[str, int] = {}

    for path in _metadata_files(args.paths):
        checks = verify_artifact_bindings(path)

        for check in checks:
            counts[check.status] = counts.get(check.status, 0) + 1

        parts.append(
            {"metadata": str(path), "artifacts": [asdict(check) for check in checks]}
        )

    matched = set(counts) == {"matched"}
    emit({"all_matched": matched, "counts": counts, "parts": parts})

    return 0 if matched else 1


def register(
    subcommands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Add the export commands to the zcad-validation parser."""

    export_parser = subcommands.add_parser(
        "export", help="check exported parts against their recorded bytes"
    )
    commands = export_parser.add_subparsers(dest="subcommand", required=True)
    verify = commands.add_parser(
        "verify",
        help=(
            "report whether the STEP and STL beside each part's metadata are "
            "the bytes it recorded; exits 1 unless every one matched. Reads "
            "only, and is no verdict on geometry or authorship"
        ),
    )
    verify.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help=f"*{METADATA_SUFFIX} files, or directories to search for them",
    )
    verify.set_defaults(handler=_export_verify)
