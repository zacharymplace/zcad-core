"""Retention mesh probes over exported STL bytes."""

from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention.export_checks import retention_stl_checks
from zcad_core.validation.stl_mesh import STLMesh, read_stl

# Board footprint x/y within +/-20 x +/-15, top at z = 1.6.
BOARD_BOUNDS = [[-20.0, -15.0, 0.0], [20.0, 15.0, 1.6]]
WALL = cq.Workplane("XY").box(2.0, 5.0, 3.0).translate((22.0, 0.0, 1.5))


def mesh(tmp_path: Path, shape: cq.Workplane) -> STLMesh:
    path = tmp_path / "part.stl"
    cq.exporters.export(shape, str(path))
    return read_stl(path.read_bytes())[0]


def checks(
    model: STLMesh,
    *,
    bounds: list[list[float]] | None = BOARD_BOUNDS,
    clearance: object = 0.25,
) -> dict[str, dict[str, object]]:
    parameters = {"board_clearance_mm": clearance}

    if bounds is not None:
        parameters["reference_board_bounds_mm"] = bounds

    return {
        check["code"]: check
        for check in retention_stl_checks(
            design_type="retention-candidate",
            parts={"main": model},
            parameters=parameters,
        )
    }


def ledge(bottom_z: float) -> cq.Workplane:
    return (
        cq.Workplane("XY")
        .box(5.0, 5.0, 3.0 - bottom_z)
        .translate((19.5, 0.0, (3.0 + bottom_z) / 2.0))
    )


def test_attached_ledge_passes_and_reports_vertical_play(tmp_path: Path) -> None:
    result = checks(mesh(tmp_path, WALL.union(ledge(2.0))))

    assert result["retention_supported_bodies"]["status"] == "PASS"
    assert result["retention_board_top_clearance"]["status"] == "PASS"
    assert result["retention_board_capture"]["status"] == "PASS"
    assert result["retention_board_capture"]["vertical_play_mm"] == pytest.approx(
        0.4, abs=1e-3
    )


def test_floating_ledge_fails(tmp_path: Path) -> None:
    floating = cq.Workplane("XY").box(3.0, 3.0, 1.0).translate((18.0, 0.0, 2.5))
    result = checks(mesh(tmp_path, WALL.union(floating)))

    supported = result["retention_supported_bodies"]
    assert supported["status"] == "FAIL"
    assert supported["body_count"] == 2
    assert supported["floating_body_count"] == 1


def test_ledge_inside_clearance_fails(tmp_path: Path) -> None:
    result = checks(mesh(tmp_path, WALL.union(ledge(1.7))))

    clearance = result["retention_board_top_clearance"]
    assert clearance["status"] == "FAIL"
    assert clearance["blocked_probe_count"] > 0


def test_nothing_over_board_fails_capture(tmp_path: Path) -> None:
    result = checks(mesh(tmp_path, WALL))

    assert result["retention_board_capture"]["status"] == "FAIL"
    assert result["retention_board_capture"]["vertical_play_mm"] is None


def test_board_checks_need_bounds(tmp_path: Path) -> None:
    result = checks(mesh(tmp_path, WALL), bounds=None)

    assert result["retention_supported_bodies"]["status"] == "PASS"
    assert result["retention_board_top_clearance"]["status"] == "NOT_CHECKED"
    assert result["retention_board_capture"]["status"] == "NOT_CHECKED"


@pytest.mark.parametrize("clearance", [None, True, 0.0, float("nan")])
def test_unusable_clearance_is_not_checked(tmp_path: Path, clearance: object) -> None:
    result = checks(mesh(tmp_path, WALL.union(ledge(2.0))), clearance=clearance)

    assert result["retention_board_top_clearance"]["status"] == "NOT_CHECKED"
    assert result["retention_board_capture"]["status"] == "PASS"
