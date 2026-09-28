"""Strict STL parsing and export report coverage."""

import json
import struct

import cadquery as cq
import pytest

from zcad_core.exporters import ExportRequest, export_parts
from zcad_core.validation.stl_mesh import read_stl


@pytest.mark.parametrize(
    "damage", ["empty", "nonfinite", "duplicate", "degenerate", "inverted"]
)
def test_invalid_mesh_rejected(tmp_path, damage):
    path = tmp_path / "box.stl"
    cq.exporters.export(cq.Workplane().box(4, 4, 4), str(path))
    data = bytearray(path.read_bytes())
    count = struct.unpack_from("<I", data, 80)[0]
    if damage == "empty":
        data = data[:84]
        struct.pack_into("<I", data, 80, 0)
    elif damage == "nonfinite":
        struct.pack_into("<f", data, 96, float("nan"))
    elif damage == "duplicate":
        data += data[84:134]
        struct.pack_into("<I", data, 80, count + 1)
    elif damage == "degenerate":
        data[108:120] = data[96:108]
    elif damage == "inverted":
        for i in range(count):
            start = 84 + i * 50
            data[start + 24 : start + 36], data[start + 36 : start + 48] = (
                data[start + 36 : start + 48],
                data[start + 24 : start + 36],
            )
    with pytest.raises(ValueError):
        read_stl(data)


def test_all_part_metadata_contains_complete_mesh_report(tmp_path):
    result = export_parts(
        ExportRequest(
            design_name="pair",
            design_type="boxes",
            parts={"a": cq.Workplane().box(2, 2, 2), "b": cq.Workplane().box(3, 3, 3)},
            output_directory=tmp_path / "out",
            repository_root=tmp_path,
        )
    )
    report = result.validation_report["stl_round_trip"]
    assert set(report["stl_sha256_by_part"]) == {"a", "b"}
    assert report["checks"][-1]["status"] == "NOT_CHECKED"
    for part in result.parts:
        assert (
            json.loads(part.metadata_path.read_text())["design_validation"]
            == result.validation_report
        )


def test_body_bounds_separates_disconnected_bodies(tmp_path):
    shape = (
        cq.Workplane()
        .box(10, 10, 2)
        .union(cq.Workplane().box(2, 2, 1).translate((0, 0, 3)))
    )
    path = tmp_path / "bodies.stl"
    cq.exporters.export(shape, str(path))
    bodies = read_stl(path.read_bytes())[0].body_bounds()
    assert len(bodies) == 2
    assert bodies[0][0][2] == pytest.approx(-1)
    assert bodies[1][0][2] == pytest.approx(2.5)


def test_body_bounds_joins_fused_solids(tmp_path):
    shape = (
        cq.Workplane()
        .box(10, 10, 2)
        .union(cq.Workplane().box(2, 2, 2).translate((0, 0, 2)))
    )
    path = tmp_path / "fused.stl"
    cq.exporters.export(shape, str(path))
    assert len(read_stl(path.read_bytes())[0].body_bounds()) == 1
