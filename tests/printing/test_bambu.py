"""Slicing with the Bambu Studio CLI."""

from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.printing import BAMBU_STUDIO, SliceError, slice_models
from zcad_core.printing.bambu import (
    _run_bambu,
    bambu_command,
    preset_names,
    process_overrides,
)

SLICER_PROFILE = (
    Path(__file__).resolve().parents[2]
    / "profiles/slicers/bambu-studio-a1-mini-petg-validation.json"
)


def profile() -> dict[str, object]:
    loaded = json.loads(SLICER_PROFILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_profile_maps_to_bambu_presets() -> None:
    assert preset_names(profile()) == {
        "machine": "Bambu Lab A1 mini 0.4 nozzle",
        "process": "0.20mm Standard @BBL A1M",
        "filament": "Bambu PETG Basic @BBL A1M 0.4 nozzle",
    }
    assert process_overrides(profile())["curr_bed_type"] == "Textured PEI Plate"


def test_unmapped_material_is_refused() -> None:
    with pytest.raises(SliceError, match="No Bambu preset mapping"):
        preset_names({**profile(), "material_profile_id": "pla"})


def test_command_arranges_every_model_without_reorienting(tmp_path: Path) -> None:
    command = bambu_command(BAMBU_STUDIO, tmp_path, [Path("a.stl"), Path("b.stl")])

    assert command[command.index("--orient") + 1] == "0"
    assert command[command.index("--arrange") + 1] == "1"
    assert [Path(arg).name for arg in command[-2:]] == ["a.stl", "b.stl"]


def test_refuses_missing_models_and_existing_output(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing model"):
        slice_models(
            [tmp_path / "none.stl"],
            tmp_path / "out",
            slicer_profile_path=SLICER_PROFILE,
        )

    model = tmp_path / "part.stl"
    model.write_text("solid part\n", encoding="utf-8")
    (tmp_path / "out").mkdir()
    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        slice_models([model], tmp_path / "out", slicer_profile_path=SLICER_PROFILE)

    with pytest.raises(SliceError, match="not installed"):
        slice_models(
            [model],
            tmp_path / "fresh",
            slicer_profile_path=SLICER_PROFILE,
            app=tmp_path / "NoSuch.app",
        )


def test_a_stalled_slicer_is_stopped_and_refused(tmp_path: Path) -> None:
    app = tmp_path / "Fake.app"
    binary = app / "Contents/MacOS/BambuStudio"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\nexec sleep 60\n", encoding="utf-8")
    binary.chmod(0o755)
    model = tmp_path / "part.stl"
    model.write_text("solid part\n", encoding="utf-8")

    with pytest.raises(SliceError, match="stalled"):
        _run_bambu(app, {"machine": {}}, [model], tmp_path / "out", 0.5)

    assert not (tmp_path / "out").exists()


@pytest.mark.slow
@pytest.mark.skipif(not BAMBU_STUDIO.is_dir(), reason="Bambu Studio is not installed")
def test_slices_two_parts_onto_one_plate(tmp_path: Path) -> None:
    models = []
    for name, size in (("block", 20.0), ("slab", 15.0)):
        model = tmp_path / f"{name}.stl"
        cq.exporters.export(cq.Workplane("XY").box(size, size, 5.0), str(model))
        models.append(model)

    result = slice_models(
        models,
        tmp_path / "slice",
        slicer_profile_path=SLICER_PROFILE,
        summary_fields={"design_name": "blocks"},
    )

    assert result.gcode_path.stat().st_size > 0
    assert result.summary["design_name"] == "blocks"
    assert [entry["path"] for entry in result.summary["models"]] == [
        str(model) for model in models
    ]
    assert result.summary["filament_used_g"] > 0
    assert set(result.summary["source"]) == {"git_commit", "uncommitted_changes"}
    assert json.loads(result.summary_path.read_text("utf-8")) == result.summary
