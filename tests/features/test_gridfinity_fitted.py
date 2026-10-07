"""Fitted Gridfinity bins: a solid bin with a pocket cut for one measured object."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import cadquery as cq
import pytest

from zcad_core.cli import main
from zcad_core.features.gridfinity_fitted import (
    FittedSpec,
    Footprint,
    build_fitted_bin,
    capture_footprint,
    fewest_units,
    model_footprint,
)
from zcad_core.features.gridfinity_shapes import GridfinityPart
from zcad_core.features.holder_model import load_holder_model
from zcad_core.hardware.wearables.capture import load_capture
from zcad_core.profiles import load_printer_profile

PROFILE = load_printer_profile(
    Path(__file__).resolve().parents[2] / "profiles/printers/bambu-lab-a1-mini.json"
)


def capture(
    length: float, width: float, thickness: float, radius: float = 2.0
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "units": "mm",
        "device": "custom",
        "name": "Pocket tool",
        "measured_by": "Test",
        "measured_on": "2026-10-06",
        "caliper": "digital caliper, 0.01 mm",
        "orientation": "flat, its blade east",
        "source": "one tool, three passes",
        "body_readings": {
            "length_mm": [length] * 3,
            "width_mm": [width] * 3,
            "thickness_mm": [thickness] * 3,
        },
        "outline": {"type": "rounded_rectangle", "radius_mm": radius},
        "edge_features": [],
        "edge_features_checked": True,
        "face_features": [],
    }


def footprint(tmp_path: Path, data: dict[str, Any]) -> Footprint:
    path = tmp_path / "tool.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    return capture_footprint(load_capture(path))


@pytest.fixture(scope="module")
def tool_bin(tmp_path_factory: pytest.TempPathFactory) -> GridfinityPart:
    item = footprint(tmp_path_factory.mktemp("tool"), capture(30.0, 20.0, 12.0))

    return build_fitted_bin(item, FittedSpec(depth_mm=8.0), PROFILE)


def inside(part: GridfinityPart, x: float, y: float, z: float) -> bool:
    shape = part.body.val()
    assert isinstance(shape, cq.Shape)

    return any(solid.isInside(cq.Vector(x, y, z), 1e-4) for solid in shape.Solids())


def test_a_small_tool_gets_one_unit_with_its_pocket(tool_bin: GridfinityPart) -> None:
    assert tool_bin.passed, tool_bin.checks
    assert tool_bin.checks["object_fits_pocket"]
    assert tool_bin.checks["object_lifts_out"]
    assert tool_bin.checks["stacks"]
    fitted = tool_bin.settings["fitted"]

    assert tool_bin.settings["units"] == [1, 1]
    # A floor's 1.2 mm over the 4.75 mm base, and 8 mm of sink: 13.95 mm, so two 7 mm units.
    assert tool_bin.settings["height_units"] == 2
    assert fitted["pocket_floor_mm"] == pytest.approx(14.0 - 8.0)
    assert fitted["finger_notches"] == 2


def test_the_pocket_is_the_outline_grown_by_the_clearance(
    tool_bin: GridfinityPart,
) -> None:
    floor = tool_bin.settings["fitted"]["pocket_floor_mm"]

    # Empty just inside the clearance at the tool's end; solid just past it.
    assert not inside(tool_bin, 15.0 + 0.15, 0.0, floor + 1.0)
    assert inside(tool_bin, 15.0 + 0.25, 0.0, floor + 1.0)
    # The pocket's floor is solid under it.
    assert inside(tool_bin, 0.0, 0.0, floor - 0.5)


def test_an_object_standing_proud_of_the_top_warns_of_stacking(
    tool_bin: GridfinityPart,
) -> None:
    # 12 mm tall and sunk 8 mm: its top is 4 mm above the bin's.
    assert "stands 4.0 mm above the bin's top" in tool_bin.warnings[0]


def test_fewest_units_hold_the_object_with_its_wall() -> None:
    assert fewest_units(36.0, 0.2, 1.2) == 1
    assert fewest_units(40.0, 0.2, 1.2) == 2
    assert fewest_units(120.0, 0.2, 1.2) == 3


def test_a_tool_too_big_for_the_units_or_sunk_too_deep_is_refused(
    tmp_path: Path,
) -> None:
    item = footprint(tmp_path, capture(60.0, 20.0, 10.0))

    with pytest.raises(ValueError, match="needs at least 2x1 units"):
        build_fitted_bin(item, FittedSpec(units=(1, 1)), PROFILE)

    with pytest.raises(ValueError, match="sinks 0 to its 10.0 mm height"):
        build_fitted_bin(item, FittedSpec(depth_mm=11.0), PROFILE)


def test_a_given_clearance_is_used_and_said(tmp_path: Path) -> None:
    item = footprint(tmp_path, capture(30.0, 20.0, 6.0))
    part = build_fitted_bin(
        item,
        FittedSpec(clearance_mm=0.5, clearance_source="a loose fit, wanted", lip=False),
        PROFILE,
    )
    fitted = part.settings["fitted"]

    assert part.passed, part.checks
    assert fitted["clearance_per_side_mm"] == 0.5
    assert fitted["clearance_from"] == "given: a loose fit, wanted"
    assert part.warnings == ()


def test_a_modelled_object_lies_in_its_shadow(tmp_path: Path) -> None:
    # A T shape lying flat: a 30 x 8 mm bar with a 10 x 14 mm stem, 6 mm thick.
    path = tmp_path / "tee.step"
    tee = (
        cq.Workplane("XY")
        .box(30, 8, 6, centered=(True, False, False))
        .union(
            cq.Workplane("XY")
            .box(10, 14, 6, centered=(True, False, False))
            .translate((0, -14, 0))
        )
    )
    cq.exporters.export(tee, str(path), "STEP")
    model = load_holder_model(
        path, hashlib.sha256(path.read_bytes()).hexdigest(), None, "+z", "+y"
    )
    part = build_fitted_bin(model_footprint(model), FittedSpec(lip=False), PROFILE)

    assert part.passed, part.checks
    assert part.settings["fitted"]["object_kind"] == "model"
    assert part.settings["fitted"]["object_size_mm"] == pytest.approx([30.0, 22.0, 6.0])


def test_the_command_builds_a_fitted_bin(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    tool = tmp_path / "pocket-tool.json"
    tool.write_text(json.dumps(capture(30.0, 20.0, 6.0)), encoding="utf-8")
    code = main(
        [
            "gridfinity",
            "fitted",
            "--capture",
            str(tool),
            "--no-lip",
            "--output-directory",
            str(tmp_path / "out"),
        ]
    )
    report = json.loads(capsys.readouterr().out)

    assert code == 0
    assert report["validation_status"] == "PASS"
    assert report["design_name"] == "gridfinity-fitted-pocket-tool-1x1"
    record = json.loads((tmp_path / "out" / "gridfinity.json").read_text())
    assert record["settings"]["fitted"]["object"] == "Pocket tool"

    code = main(
        [
            "gridfinity",
            "fitted",
            "--capture",
            str(tool),
            "--clearance-mm",
            "0.4",
            "--output-directory",
            str(tmp_path / "again"),
        ]
    )

    assert code == 1
    assert "go together" in capsys.readouterr().err
