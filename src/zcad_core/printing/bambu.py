"""Slice printable parts with the Bambu Studio command-line interface.

Resolves Bambu system presets for a project slicer profile's printer and
material, applies the settings the profile declares, and slices one or more
STL files onto a single plate. Parts are sliced in the orientation their STL
files give them: Bambu may arrange them (translate, and spin about Z) but
never re-orients them. Writes to the output directory:

- ``slice-summary.json``: Bambu version, presets, applied settings, model and
  G-code hashes, and slice metrics
- ``plate_1.gcode`` and Bambu's ``result.json``
- the flattened ``machine.json``, ``process.json``, and ``filament.json``

Existing slice output is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import plistlib
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BAMBU_STUDIO = Path("/Applications/BambuStudio.app")
SLICE_SUMMARY_SCHEMA_VERSION = "1.1.0"

# Project profile ids -> Bambu system presets, keyed by nozzle diameter.
MACHINE_PRESETS = {("bambu-lab-a1-mini", 0.4): "Bambu Lab A1 mini 0.4 nozzle"}
PROCESS_PRESETS = {("bambu-lab-a1-mini", 0.4): "0.20mm Standard @BBL A1M"}
FILAMENT_PRESETS = {
    ("bambu-lab-a1-mini", "petg", 0.4): "Bambu PETG Basic @BBL A1M 0.4 nozzle"
}
# The A1 mini ships with the textured PEI plate, the usual surface for PETG.
BED_TYPE = "Textured PEI Plate"


class SliceError(RuntimeError):
    """Bambu Studio could not slice the plate."""


@dataclass(frozen=True)
class SliceResult:
    """Where the plate's G-code and summary were written."""

    gcode_path: Path
    summary_path: Path
    summary: dict[str, Any]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_presets(app: Path = BAMBU_STUDIO) -> dict[tuple[str, str], dict[str, Any]]:
    """Every Bambu system preset, by kind and name."""

    index = {}
    presets = app / "Contents/Resources/profiles/BBL"

    for kind in ("machine", "process", "filament"):
        for path in (presets / kind).glob("*.json"):
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
    """A preset with everything it inherits merged in."""

    preset = index[kind, name]
    base = flatten(index, kind, preset["inherits"]) if preset.get("inherits") else {}
    merged = {**base, **preset}
    merged.pop("inherits", None)
    merged["from"] = "system"

    return merged


def process_overrides(profile: dict[str, Any]) -> dict[str, str]:
    """The process settings a project slicer profile fixes."""

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


def preset_names(profile: dict[str, Any]) -> dict[str, str]:
    """The Bambu system presets a project slicer profile maps to."""

    printer = profile["printer_profile_id"]
    nozzle = float(profile["nozzle_diameter_mm"])
    material = profile["material_profile_id"]

    try:
        return {
            "machine": MACHINE_PRESETS[printer, nozzle],
            "process": PROCESS_PRESETS[printer, nozzle],
            "filament": FILAMENT_PRESETS[printer, material, nozzle],
        }
    except KeyError as error:
        raise SliceError(f"No Bambu preset mapping for {error}") from error


def bambu_command(app: Path, work: Path, models: Sequence[Path]) -> list[str]:
    """Slice plate 1, arranging but never re-orienting the models."""

    return [
        str(app / "Contents/MacOS/BambuStudio"),
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
        *(str(model.resolve()) for model in models),
    ]


def slice_models(
    models: Sequence[Path],
    output_directory: Path,
    *,
    slicer_profile_path: Path,
    app: Path = BAMBU_STUDIO,
    summary_fields: dict[str, Any] | None = None,
) -> SliceResult:
    """Slice the models onto one plate and write the slice evidence, with
    any ``summary_fields`` the caller adds to the summary."""

    if not models:
        raise ValueError("Nothing to slice")

    for model in models:
        if not model.is_file():
            raise FileNotFoundError(f"Missing model: {model}")

    if output_directory.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing slice output: {output_directory}"
        )

    if not app.is_dir():
        raise SliceError(f"Bambu Studio is not installed at {app}")

    profile = json.loads(slicer_profile_path.read_text(encoding="utf-8"))

    if profile.get("orientation") != "base_down":
        raise SliceError("Only base_down slicer profiles are supported")

    names = preset_names(profile)
    version = plistlib.loads((app / "Contents/Info.plist").read_bytes())[
        "CFBundleShortVersionString"
    ]
    index = load_presets(app)
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
            bambu_command(app, work, models),
            capture_output=True,
            text=True,
            check=False,
        )
        result_path = work / "result.json"

        if not result_path.is_file():
            raise SliceError(
                "Bambu Studio did not write result.json:\n"
                + completed.stdout[-4000:]
                + completed.stderr[-4000:]
            )

        result = json.loads(result_path.read_text(encoding="utf-8"))

        if result.get("return_code") != 0 or not (work / "plate_1.gcode").is_file():
            raise SliceError(f"Slice failed: {result.get('error_string')}")

        plate = result["sliced_plates"][0]
        output_directory.mkdir(parents=True)

        for name in ("plate_1.gcode", "result.json"):
            (output_directory / name).write_bytes((work / name).read_bytes())

        for kind in configs:
            (output_directory / f"{kind}.json").write_bytes(
                (work / f"{kind}.json").read_bytes()
            )

    gcode = output_directory / "plate_1.gcode"
    summary = {
        "schema_version": SLICE_SUMMARY_SCHEMA_VERSION,
        "models": [{"path": str(model), "sha256": sha256(model)} for model in models],
        "slicer_profile_id": profile["profile_id"],
        "software": {"name": "Bambu Studio", "version": version},
        "presets": names,
        "applied_settings": overrides,
        "orientation": "as modelled (auto-orient off; arrange may spin about Z)",
        "gcode_sha256": sha256(gcode),
        "estimated_print_time_seconds": plate["total_predication"],
        "filament_used_g": sum(f["total_used_g"] for f in plate["filaments"]),
        "feature_type_times_seconds": plate["feature_type_times"],
        "slicer_warning": plate.get("warning_message", ""),
        "sliced_at_utc": datetime.now(UTC).isoformat(),
        **(summary_fields or {}),
    }
    summary_path = output_directory / "slice-summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    return SliceResult(gcode_path=gcode, summary_path=summary_path, summary=summary)
