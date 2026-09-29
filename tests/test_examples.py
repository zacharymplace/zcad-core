"""The examples run in the gate, so they cannot drift from the API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from zcad_core.geometry.cadquery_support import workplane_shape

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_pico2_oled_tray_exports_a_validated_tray(tmp_path: Path) -> None:
    example = load_example("pico2_oled_tray")

    result = example.main(tmp_path)

    (part,) = result.parts
    assert part.step_path.is_file()
    assert part.stl_path.is_file()
    assert result.validation_report["evaluated_status"] == "PASS"

    metadata = json.loads(part.metadata_path.read_text(encoding="utf-8"))
    assert metadata["design"]["name"] == "pico2-oled-tray"


def test_pico2_oled_tray_opening_matches_its_specification() -> None:
    """The cable opening removes exactly its clearance-padded size (0.6 mm
    each way) through one wall."""

    example = load_example("pico2_oled_tray")
    spec = example.enclosure_specification()
    tray = example.build_tray(spec)

    shell = example.build_shell(spec)
    opening_mm3 = workplane_shape(shell).Volume() - workplane_shape(tray).Volume()

    width = spec.cable_width_mm + 0.6
    height = spec.cable_height_mm + 0.6
    assert opening_mm3 == pytest.approx(width * height * example.WALL_MM, rel=1e-3)
