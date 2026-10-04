"""The examples run in the gate, so they cannot drift from the API."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import cast

from zcad_core.cli.enclosure_group_bays import _bays
from zcad_core.features.enclosure_group import Bay, BayKind

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

    result, review = example.main(tmp_path)

    assert [part.part_name for part in result.parts] == ["base", "lid"]
    for part in result.parts:
        assert part.step_path.is_file()
        assert part.stl_path.is_file()
    assert result.validation_report["evaluated_status"] == "PASS"

    metadata = json.loads(result.parts[0].metadata_path.read_text(encoding="utf-8"))
    assert metadata["design"]["name"] == "pico2-oled-enclosure"
    assert review.passed
    assert review.glb_path.is_file()


def test_pi5_group_enclosure_exports_a_validated_base_and_lid_and_a_viewer(
    tmp_path: Path,
) -> None:
    example = load_example("pi5_group_enclosure")

    result, group, viewer = example.main(tmp_path)

    assert [part.part_name for part in result.parts] == ["base", "lid"]
    for part in result.parts:
        assert part.step_path.is_file()
        assert part.stl_path.is_file()
    assert result.validation_report["evaluated_status"] == "PASS"
    assert group.passed

    metadata = json.loads(result.parts[0].metadata_path.read_text(encoding="utf-8"))
    assert metadata["design"]["name"] == "pi5-group-example"
    shown = json.loads((viewer / "enclosures.json").read_text(encoding="utf-8"))
    assert [entry["key"] for entry in shown] == ["example"]
    assert (viewer / "index.html").read_text(encoding="utf-8").startswith("<!doctype")


def test_pi5_group_example_command_line_spelling_matches_its_bays() -> None:
    example = load_example("pi5_group_enclosure")
    written = tuple(
        Bay(kind=cast(BayKind, bay)) if isinstance(bay, str) else bay
        for bay in example.BAYS
    )

    assert _bays(example.BAYS_SPEC) == written
