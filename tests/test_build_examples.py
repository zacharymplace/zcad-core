"""scripts/build-examples.py: one example of each product not yet built, for the z-cadalog."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), SCRIPTS / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_product_builds_as_an_example_the_catalogue_shows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    # The builds find the printer profiles from the repository root.
    monkeypatch.chdir(SCRIPTS.parent)
    built = load("build-examples").build_examples(evidence)
    catalog = load("build-catalog").build_catalog(evidence, tmp_path / "catalog")
    designs = {design["id"]: design for design in catalog["designs"]}

    assert set(built) == {
        "holder",
        "nest",
        "jig",
        "stack",
        "housing",
        "guide",
        "pcb-fixture",
    }
    assert {key: (d["kind"], d["status"]) for key, d in designs.items()} == {
        "examples/holder/holder-example": ("Object holder", "example"),
        "examples/nest/nest-example": ("Holding nest", "example"),
        "examples/jig/jig-example": ("Insert jig", "example"),
        "examples/stack/stack-example": ("Stackable items", "example"),
        "examples/housing/housing-example": ("Wearable housing", "example"),
        "examples/guide/guide-example": ("Drill guide", "example"),
        "examples/pcb-fixture/pcb-fixture-example": ("PCB test fixture", "example"),
    }
    assert all(design["models"] for design in designs.values())
    assert all(check["passed"] for d in designs.values() for check in d["checks"])

    # The template's readings are kept, and say they were never measured.
    capture = json.loads((evidence / "examples/holder/object-capture.json").read_text())
    assert "needs_review" not in capture
    assert capture["source"].startswith("Template example values, unchanged")


def test_the_examples_are_built_once_and_never_overwritten(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    (evidence / "examples").mkdir(parents=True)

    with pytest.raises(FileExistsError, match="never overwritten"):
        load("build-examples").build_examples(evidence)
