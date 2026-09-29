"""Slice a Validation Lab candidate's fixture with the Bambu Studio CLI.

Resolves Bambu system presets for the project's printer and material, applies
the settings declared in a project slicer profile, slices the candidate's
``fixture.stl`` base-down (arrange translates and spins about Z only; auto-
orient is off), and writes evidence to ``<candidate>/slice/``:

- ``slice-summary.json``: Bambu version, presets, applied settings, fixture
  and G-code hashes, and slice metrics
- ``plate_1.gcode`` and Bambu's ``result.json``
- the flattened ``machine.json``, ``process.json`` and ``filament.json``

Existing slice evidence is never overwritten. The slicing itself is
:func:`zcad_core.printing.slice_models`, shared with
``zcad-validation enclosure build --slice``.

Usage:
    python scripts/slice-candidate-fixture.py <candidate-directory> \\
        [--slicer-profile profiles/slicers/<id>.json]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from zcad_core.printing import SliceError, slice_models
from zcad_core.printing.bambu import sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidate_directory", type=Path)
    parser.add_argument(
        "--slicer-profile",
        type=Path,
        default=Path("profiles/slicers/bambu-studio-a1-mini-petg-validation.json"),
    )
    args = parser.parse_args()

    candidate = args.candidate_directory
    fixture = candidate / "fixture.stl"

    if not fixture.is_file():
        raise SystemExit(f"Missing fixture: {fixture}")

    try:
        result = slice_models(
            [fixture],
            candidate / "slice",
            slicer_profile_path=args.slicer_profile,
            summary_fields={
                "candidate_directory": str(candidate),
                "fixture_path": str(fixture),
                "fixture_sha256": sha256(fixture),
            },
        )
    except (SliceError, FileExistsError) as error:
        raise SystemExit(str(error)) from error

    print(json.dumps(result.summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
