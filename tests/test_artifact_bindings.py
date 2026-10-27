"""Exact per-part binding of published artifacts without changing legacy fields."""

import hashlib
import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts


@pytest.mark.parametrize("multi", [False, True])
@pytest.mark.parametrize("validate_features", [False, True])
def test_bindings_match_each_published_part(
    tmp_path: Path, multi: bool, validate_features: bool
) -> None:
    parts = {"main": cq.Workplane("XY").box(10, 12, 8)}
    if multi:
        parts["cap"] = cq.Workplane("XY").box(6, 8, 3)
    result = export_parts(
        ExportRequest(
            design_name="binding-check",
            design_type="fixture",
            parts=parts,
            output_directory=tmp_path / "export",
            repository_root=tmp_path,
            feature_validator=(
                lambda **_: [
                    {"code": "fixture", "status": "PASS", "message": "Binding fixture"}
                ]
            )
            if validate_features
            else None,
        )
    )
    for part in result.parts:
        record = json.loads(part.metadata_path.read_text())
        assert record["schema_version"] == "1.0"
        assert "producer" in record
        assert record["part"]["name"] == part.part_name
        for kind, path in (("step", part.step_path), ("stl", part.stl_path)):
            binding = record["artifacts"][kind]
            assert binding == {
                "filename": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size_bytes": path.stat().st_size,
            }
            assert record["outputs"][kind] == str(path)
            hashes = (
                record["design_validation"]
                .get(f"{kind}_round_trip", {})
                .get(f"{kind}_sha256_by_part", {})
            )
            if part.part_name in hashes:
                assert binding["sha256"] == hashes[part.part_name]
    relocated = tmp_path / "moved"
    (tmp_path / "export").rename(relocated)
    for part in result.parts:
        metadata = json.loads((relocated / part.metadata_path.name).read_text())
        for binding in metadata["artifacts"].values():
            assert (
                hashlib.sha256(
                    (relocated / binding["filename"]).read_bytes()
                ).hexdigest()
                == binding["sha256"]
            )
