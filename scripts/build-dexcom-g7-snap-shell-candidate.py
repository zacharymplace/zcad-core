#!/usr/bin/env python3
"""Register a Dexcom G7 snap-shell Validation Lab candidate.

There is no manufacturer STEP file for the G7, so the body is a
rectangular envelope. With no ``--capture`` it is sized from the
manufacturer-published dimensions in
:mod:`zcad_core.hardware.wearables.dexcom`, not a device scan: the
candidate is a ``provisional_synthetic_candidate`` that no trial may use.
With a caliper capture (see docs/guides/wearable-capture.md) it is sized
from the measurements and the candidate is verified when the shell's fit
checks, measured against that envelope, pass. Its clips are tabs bending
along the edge: a post on the 4.7 mm G7 would strain over the limit.

With no arguments it registers the target and r001. A later revision names
its parent and why:

    python scripts/build-dexcom-g7-snap-shell-candidate.py \\
        --revision r002 --parent r001 --reason "..." --capture g7.json

The revision logic lives in :mod:`zcad_core.retention.snap_shell_candidate`.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

from zcad_core.hardware.wearables import get_dexcom_g7
from zcad_core.retention.snap_shell_candidate import (
    WearableTarget,
    body_from,
    parse_arguments,
    register_snap_shell_candidate,
)

ROOT = Path(__file__).resolve().parents[1]

TARGET = WearableTarget(
    target_id="dexcom-g7-sensor",
    device="dexcom-g7",
    display_name="Dexcom G7 Sensor",
    manufacturer="Dexcom",
    product_family="G7",
    file_stem="dexcom-g7",
    # Three clips, as r001 was registered: the minimum that stops rocking.
    clip_edges=("north", "south", "east"),
    heading="DEXCOM G7",
    # At 4.7 mm the G7 is too thin for a post to bend up its side within the
    # strain limit, so each clip is a tab bending along the edge.
    tabs=True,
    placeholder_reason=(
        "Source geometry is a placeholder envelope, not a "
        "caliper-verified capture; not eligible for promotion "
        "or physical trials."
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
    args = parse_arguments(argv, "Register a Dexcom G7 snap-shell candidate.")
    spec = get_dexcom_g7()
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
