import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.validation.export_geometry import (
    GeometryValidationError,
    inspect_export_geometry,
)
from zcad_core.validation.profile_rules import validate_build_volume


def stack() -> cq.Workplane:
    a = cq.Workplane().box(10, 10, 10).val()
    b = cq.Workplane().box(20, 10, 10).translate((150, 0, 0)).val()
    return cq.Workplane().newObject([a, b])


def test_complete_stack_matches_step_and_metadata(tmp_path: Path) -> None:
    model = stack()
    result = export_parts(
        ExportRequest("two", "test", {"main": model}, tmp_path, tmp_path)
    )
    part = result.parts[0]
    imported = cq.importers.importStep(str(part.step_path))
    assert len(imported.solids().vals()) == 2
    assert part.volume_mm3 == pytest.approx(3000)
    assert part.bounds_mm == pytest.approx((165, 10, 10))
    assert imported.val().BoundingBox().xlen == pytest.approx(part.bounds_mm[0])
    metadata = json.loads(part.metadata_path.read_text())
    assert metadata["part"]["volume_mm3"] == 3000
    report = metadata["validation"]
    assert report["solid_count"] == 2
    statuses = {c["code"]: c["status"] for c in report["checks"]}
    assert statuses["brep_validity"] == "PASS"
    assert statuses["physical_fit"] == "NOT_CHECKED"
    assert statuses["artifact_integrity"] == "NOT_CHECKED"
    assert len(model.vals()) == 2


def test_printer_bounds_include_later_stack_items() -> None:
    issues = validate_build_volume(
        part_name="main",
        model=stack(),
        printer_profile={"build_volume_mm": {"x": 100, "y": 100, "z": 100}},
    )
    assert [i.code for i in issues] == ["build_volume_x_exceeded"]


@pytest.mark.parametrize("kind", ["empty", "vector", "face", "mixed", "nested"])
def test_reject_non_solid_topology_before_any_writes(tmp_path: Path, kind: str) -> None:
    solid = cq.Workplane().box(10, 10, 10).val()
    face = solid.Faces()[0]
    values = {
        "empty": [],
        "vector": [cq.Vector(0, 0, 0)],
        "face": [face],
        "mixed": [solid, face],
        "nested": [cq.Compound.makeCompound([solid, cq.Compound.makeCompound([face])])],
    }[kind]
    bad = cq.Workplane().newObject(values)
    output = tmp_path / "exports"
    with pytest.raises(GeometryValidationError) as caught:
        export_parts(
            ExportRequest(
                "test",
                "test",
                {"good": cq.Workplane().box(2, 2, 2), "bad": bad},
                output,
                tmp_path,
            )
        )
    assert not output.exists()
    checks = caught.value.report["checks"]
    assert sum(c["status"] == "FAIL" for c in checks) == 1
    assert checks[-1]["status"] == "NOT_CHECKED"


def test_nested_multisolid_compound_is_allowed() -> None:
    model = stack()
    nested = cq.Compound.makeCompound([cq.Compound.makeCompound(model.vals())])
    result = inspect_export_geometry(cq.Workplane().newObject([nested]), "nested")
    assert result.report["solid_count"] == 2
    assert result.volume_mm3 == pytest.approx(3000)


@pytest.mark.parametrize("volume", [0, -1, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_volume_rejected(
    monkeypatch: pytest.MonkeyPatch, volume: float
) -> None:
    monkeypatch.setattr(cq.Solid, "Volume", lambda self: volume)
    with pytest.raises(GeometryValidationError) as caught:
        inspect_export_geometry(cq.Workplane().box(2, 2, 2), "bad")
    assert caught.value.report["checks"][3]["status"] == "FAIL"


def test_invalid_brep_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cq.Solid, "isValid", lambda self: False)
    with pytest.raises(GeometryValidationError) as caught:
        inspect_export_geometry(cq.Workplane().box(2, 2, 2), "bad")
    assert caught.value.report["checks"][2]["status"] == "FAIL"
