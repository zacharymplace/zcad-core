"""The examples run in the gate, so they cannot drift from the API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def test_pico2_oled_enclosure_exports_a_validated_base_and_lid(
    tmp_path: Path,
) -> None:
    example = load_example("pico2_oled_enclosure")

    result = example.main(tmp_path)

    assert [part.part_name for part in result.parts] == ["base", "lid"]
    for part in result.parts:
        assert part.step_path.is_file()
        assert part.stl_path.is_file()
    assert result.validation_report["evaluated_status"] == "PASS"

    metadata = json.loads(result.parts[0].metadata_path.read_text(encoding="utf-8"))
    assert metadata["design"]["name"] == "pico2-oled-enclosure"
