"""Full-segment obstruction tests independent of coupon placement."""

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.validation.stl_mesh import STLMesh, read_stl


@pytest.fixture
def mesh(tmp_path: Path) -> STLMesh:
    path = tmp_path / "box.stl"
    cq.exporters.export(
        cq.Workplane().box(2, 2, 0.02).translate((0, 0, 0.7)), str(path)
    )
    return read_stl(path.read_bytes())[0]


def test_thin_obstruction_between_old_heights(mesh: STLMesh) -> None:
    assert all(not mesh.contains((0, 0, z)) for z in (-1.6, 0, 1.6))
    result = mesh.vertical_clearance(0, 0, -2, 2)
    assert not result["clear"]
    assert result["surface_contact_count"] > 0


def test_clear_and_buried_segments(mesh: STLMesh) -> None:
    assert mesh.vertical_clearance(3, 0, -2, 2)["clear"]
    result = mesh.vertical_clearance(0, 0, 0.695, 0.705)
    assert not result["clear"]
    assert result["midpoint_occupied"]
    assert result["surface_contact_count"] == 0


@pytest.mark.parametrize("x,y", [(1, 0), (1, 1), (0, 0)])
def test_contact_at_edges_vertices_and_triangle_seams(
    mesh: STLMesh, x: float, y: float
) -> None:
    assert not mesh.vertical_clearance(x, y, -2, 2)["clear"]


def test_surface_outside_segment_does_not_block(mesh: STLMesh) -> None:
    assert mesh.vertical_clearance(0, 0, -2, 0.5)["clear"]


def test_end_contact_and_coplanar_overlap(mesh: STLMesh) -> None:
    assert not mesh.vertical_clearance(0, 0, -2, 0.69)["clear"]
    result = mesh.vertical_clearance(1, 0, 0.695, 0.705)
    assert not result["clear"]
    assert any(c["kind"] == "coplanar" for c in result["contacts"])


@pytest.mark.parametrize("interval", [(2, -2), (0, 0), (float("nan"), 2)])
def test_invalid_interval_rejected(
    mesh: STLMesh, interval: tuple[float, float]
) -> None:
    with pytest.raises(ValueError):
        mesh.vertical_clearance(0, 0, *interval)
