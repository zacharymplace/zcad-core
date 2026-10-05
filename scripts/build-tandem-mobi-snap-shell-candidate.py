#!/usr/bin/env python3
"""Register a Tandem Mobi snap-shell Validation Lab candidate.

There is no manufacturer STEP file for the Mobi, so the body is an
envelope, rounded if a capture gives a corner radius. With no
``--capture`` it is sized from the published dimensions in
:mod:`zcad_core.hardware.wearables.tandem`, without the fill port,
buttons, or charging contacts, whose places are unknown: the
candidate is a ``provisional_synthetic_candidate`` that no trial may use.
With a caliper capture (see docs/guides/wearable-capture.md) it is sized
from the measurements, its clips stand clear of every feature the capture
locates, and the candidate is verified when the shell's fit checks,
measured against that envelope, pass.

With no arguments it registers the target and r001. A later revision names
its parent and why:

    python scripts/build-tandem-mobi-snap-shell-candidate.py \\
        --revision r003 --parent r002 --reason "..." --capture mobi.json

The revision logic lives in :mod:`zcad_core.retention.snap_shell_candidate`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from zcad_core.hardware.wearables import get_tandem_mobi
from zcad_core.retention.snap_shell_candidate import (
    WearableTarget,
    body_from,
    parse_arguments,
    register_snap_shell_candidate,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET = WearableTarget(
    target_id="tandem-mobi-pump",
    device="tandem-mobi",
    display_name="Tandem Mobi Pump",
    manufacturer="Tandem Diabetes Care",
    product_family="Mobi",
    file_stem="tandem-mobi",
    # Four clips, one per edge; a capture moves each clear of the features.
    clip_edges=("north", "south", "east", "west"),
    heading="TANDEM MOBI",
    placeholder_reason=(
        "Source geometry is a placeholder envelope with no "
        "modeled fill port, buttons, or charging contacts, not "
        "a caliper-verified capture; not eligible for "
        "promotion or physical trials."
    ),
)


def git_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> None:
    args = parse_arguments(argv, "Register a Tandem Mobi snap-shell candidate.")
    spec = get_tandem_mobi()
    body = body_from(
        TARGET,
        published=(spec.body_length_mm, spec.body_width_mm, spec.body_thickness_mm),
        evidence_status=spec.geometry_evidence_status,
        source=spec.geometry_source,
        capture_path=args.capture,
    )
    register_snap_shell_candidate(
        TARGET, body, args, root=root, git_commit=git_commit(root)
    )


if __name__ == "__main__":
    main()
