"""Continuous material coverage with explicit endpoint and contact behavior."""

import cadquery as cq
import pytest

from zcad_core.validation.stl_mesh import read_stl


def mesh(tmp_path, shape):
    path = tmp_path / "material.stl"
    cq.exporters.export(shape, str(path))
    return read_stl(path.read_bytes())[0]


def test_solid_end_faces_and_buried_interval(tmp_path):
    model = mesh(tmp_path, cq.Workplane().box(4, 4, 4))
    for interval in ((-2, 2), (-1, 1)):
        result = model.vertical_material(0, 0, *interval)
        assert result["covered"]
        assert result["interior_contact_count"] == 0
        assert result["midpoint_occupied"]
    assert model.vertical_material(0, 0, -2, 2)["endpoint_contact_count"] > 0


@pytest.mark.parametrize("height", [-1.9, -0.7, 0.7, 1.9])
def test_thin_internal_gap_between_old_samples(tmp_path, height):
    shape = (
        cq.Workplane()
        .box(4, 4, 4)
        .cut(cq.Workplane().box(5, 5, 0.02).translate((0, 0, height)))
    )
    model = mesh(tmp_path, shape)
    assert all(model.contains((0, 0, z)) for z in (-1.6, 0, 1.6))
    result = model.vertical_material(0, 0, -2, 2)
    assert not result["covered"]
    assert result["interior_contact_count"] > 0


@pytest.mark.parametrize("point", [(3, 0), (2, 0), (2, 2)])
def test_missing_or_boundary_material_fails(tmp_path, point):
    model = mesh(tmp_path, cq.Workplane().box(4, 4, 4))
    assert not model.vertical_material(*point, -2, 2)["covered"]


def test_recessed_end_fails(tmp_path):
    model = mesh(tmp_path, cq.Workplane().box(4, 4, 3.98))
    assert not model.vertical_material(0, 0, -2, 2)["covered"]


@pytest.mark.parametrize("interval", [(0, 0), (2, -2), (0, 1e-7), (0, float("nan"))])
def test_invalid_intervals_fail(tmp_path, interval):
    model = mesh(tmp_path, cq.Workplane().box(4, 4, 4))
    with pytest.raises(ValueError):
        model.vertical_material(0, 0, *interval)
