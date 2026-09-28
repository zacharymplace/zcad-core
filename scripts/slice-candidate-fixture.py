"""Slice a Validation Lab candidate's fixture with the Bambu Studio CLI.

Resolves Bambu system presets for the project's printer and material, applies
the settings declared in a project slicer profile, slices the candidate's
``fixture.stl`` base-down (arrange translates and spins about Z only; auto-
orient is off), and writes evidence to ``<candidate>/slice/``:

- ``slice-summary.json``: Bambu version, presets, applied settings, fixture
  and G-code hashes, and slice metrics
- ``plate_1.gcode`` and Bambu's ``result.json``
- the flattened ``machine.json``, ``process.json`` and ``filament.json``

Existing slice evidence is never overwritten.

Usage:
    python scripts/slice-candidate-fixture.py <candidate-directory> \\
        [--slicer-profile profiles/slicers/<id>.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

APP = Path("/Applications/BambuStudio.app")
PRESETS = APP / "Contents/Resources/profiles/BBL"

# Project profile ids -> Bambu system presets, keyed by nozzle diameter.
MACHINE_PRESETS = {("bambu-lab-a1-mini", 0.4): "Bambu Lab A1 mini 0.4 nozzle"}
PROCESS_PRESETS = {("bambu-lab-a1-mini", 0.4): "0.20mm Standard @BBL A1M"}
FILAMENT_PRESETS = {
    ("bambu-lab-a1-mini", "petg", 0.4): "Bambu PETG Basic @BBL A1M 0.4 nozzle"
}
# The A1 mini ships with the textured PEI plate, the usual surface for PETG.
BED_TYPE = "Textured PEI Plate"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_presets() -> dict[tuple[str, str], dict[str, Any]]:
    index = {}

    for kind in ("machine", "process", "filament"):
        for path in (PRESETS / kind).glob("*.json"):
            try:
                preset = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue

            if "name" in preset:
                index[kind, preset["name"]] = preset

    return index


def flatten(
    index: dict[tuple[str, str], dict[str, Any]], kind: str, name: str
) -> dict[str, Any]:
    preset = index[kind, name]
    base = flatten(index, kind, preset["inherits"]) if preset.get("inherits") else {}
    merged = {**base, **preset}
    merged.pop("inherits", None)
    merged["from"] = "system"

    return merged


def process_overrides(profile: dict[str, Any]) -> dict[str, str]:
    return {
        "layer_height": str(profile["layer_height_mm"]),
        "wall_loops": str(profile["wall_loops"]),
        "top_shell_layers": str(profile["top_shell_layers"]),
        "bottom_shell_layers": str(profile["bottom_shell_layers"]),
        "sparse_infill_density": f"{profile['infill']['density_percent']}%",
        "sparse_infill_pattern": str(profile["infill"]["pattern"]),
        "enable_support": "1" if profile["supports"]["enabled"] else "0",
        "brim_type": "auto_brim" if profile["brim"]["enabled"] else "no_brim",
        "curr_bed_type": BED_TYPE,
    }


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
    output = candidate / "slice"

    if not fixture.is_file():
        raise SystemExit(f"Missing fixture: {fixture}")

    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing slice evidence: {output}")

    profile = json.loads(args.slicer_profile.read_text(encoding="utf-8"))

    if profile.get("orientation") != "base_down":
        raise SystemExit("Only base_down slicer profiles are supported")

    printer = profile["printer_profile_id"]
    nozzle = float(profile["nozzle_diameter_mm"])
    material = profile["material_profile_id"]

    try:
        names = {
            "machine": MACHINE_PRESETS[printer, nozzle],
            "process": PROCESS_PRESETS[printer, nozzle],
            "filament": FILAMENT_PRESETS[printer, material, nozzle],
        }
    except KeyError as error:
        raise SystemExit(f"No Bambu preset mapping for {error}") from error

    version = plistlib.loads((APP / "Contents/Info.plist").read_bytes())[
        "CFBundleShortVersionString"
    ]
    index = load_presets()
    configs = {kind: flatten(index, kind, name) for kind, name in names.items()}
    overrides = process_overrides(profile)
    configs["process"].update(overrides)

    with tempfile.TemporaryDirectory(prefix="zcad-slice-") as folder:
        work = Path(folder)

        for kind, config in configs.items():
            (work / f"{kind}.json").write_text(
                json.dumps(config, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )

        completed = subprocess.run(
            [
                str(APP / "Contents/MacOS/BambuStudio"),
                "--slice",
                "0",
                "--arrange",
                "1",
                "--orient",
                "0",
                "--ensure-on-bed",
                "--load-settings",
                f"{work / 'machine.json'};{work / 'process.json'}",
                "--load-filaments",
                str(work / "filament.json"),
                "--outputdir",
                str(work),
                str(fixture.resolve()),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        result_path = work / "result.json"

        if not result_path.is_file():
            sys.stderr.write(completed.stdout[-4000:] + completed.stderr[-4000:])
            raise SystemExit("Bambu Studio did not write result.json")

        result = json.loads(result_path.read_text(encoding="utf-8"))

        if result.get("return_code") != 0 or not (work / "plate_1.gcode").is_file():
            raise SystemExit(f"Slice failed: {result.get('error_string')}")

        plate = result["sliced_plates"][0]
        output.mkdir(parents=True)

        for name in ("plate_1.gcode", "result.json"):
            (output / name).write_bytes((work / name).read_bytes())

        for kind in configs:
            (output / f"{kind}.json").write_bytes((work / f"{kind}.json").read_bytes())

    summary = {
        "schema_version": "1.0.0",
        "candidate_directory": str(candidate),
        "fixture_path": str(fixture),
        "fixture_sha256": sha256(fixture),
        "slicer_profile_id": profile["profile_id"],
        "software": {"name": "Bambu Studio", "version": version},
        "presets": names,
        "applied_settings": overrides,
        "orientation": "base_down (auto-orient off; arrange may spin about Z)",
        "gcode_sha256": sha256(output / "plate_1.gcode"),
        "estimated_print_time_seconds": plate["total_predication"],
        "filament_used_g": sum(f["total_used_g"] for f in plate["filaments"]),
        "feature_type_times_seconds": plate["feature_type_times"],
        "slicer_warning": plate.get("warning_message", ""),
        "sliced_at_utc": datetime.now(UTC).isoformat(),
    }
    (output / "slice-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(json.dumps(summary, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
