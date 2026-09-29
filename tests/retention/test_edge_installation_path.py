from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    EdgeCapturePolicy,
    InstallationPathPlan,
    InstallationPathReport,
    ProductionEdgeExecutionRequest,
    ProductionEdgeExecutionResult,
    analyze_edge_installation_paths,
    execute_production_edge_capture,
    write_installation_path_report,
)


def production_execution(
    tmp_path: Path,
) -> ProductionEdgeExecutionResult:
    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    source_step = tmp_path / "board.step"
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.export(
        str(source_step),
        exportType="STEP",
    )

    return execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=(tmp_path / "retention.step"),
            policy=EdgeCapturePolicy(),
        )
    )


def test_analyzes_default_rigid_paths(
    tmp_path: Path,
) -> None:
    report = analyze_edge_installation_paths(
        production_execution(tmp_path),
        candidate_id="candidate-r001",
    )

    assert report.schema_version == "1.1.0"
    assert report.collision_geometry == "fixture"
    assert report.results
    assert any(result.name == "vertical" for result in report.results)
    assert all(result.sample_count > 0 for result in report.results)
    assert "do not model" in report.limitation


def test_vertical_path_detects_capture_collision(
    tmp_path: Path,
) -> None:
    report = analyze_edge_installation_paths(
        production_execution(tmp_path),
        candidate_id="candidate-r001",
        plans=(
            InstallationPathPlan(
                name="vertical",
                waypoints_mm=(
                    (0.0, 0.0, 10.0),
                    (0.0, 0.0, 0.0),
                ),
                samples_per_segment=20,
            ),
        ),
    )

    result = report.results[0]

    assert result.passed is False
    assert result.collisions
    assert result.maximum_intersection_mm3 > 0
    assert report.rigid_path_verified is False


def test_writes_immutable_path_report(
    tmp_path: Path,
) -> None:
    report = analyze_edge_installation_paths(
        production_execution(tmp_path),
        candidate_id="candidate-r001",
    )
    output_path = tmp_path / "path-report.json"

    write_installation_path_report(
        report,
        output_path=output_path,
    )
    write_installation_path_report(
        report,
        output_path=output_path,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["candidate_id"] == ("candidate-r001")
    assert "rigid_path_verified" in payload

    output_path.write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        FileExistsError,
        match="Refusing to overwrite",
    ):
        write_installation_path_report(
            report,
            output_path=output_path,
        )


def edge_execution_with_underside_part(
    tmp_path: Path, *, depth_mm: float | None
) -> ProductionEdgeExecutionResult:
    """A plain board, optionally with a 2 mm square part depth_mm below it."""

    source_step = tmp_path / "board.step"
    assembly = cq.Assembly()
    assembly.add(
        cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8)),
        name="pcb",
    )

    if depth_mm is not None:
        height = depth_mm + 0.5
        assembly.add(
            cq.Workplane("XY")
            .box(2.0, 2.0, height)
            .translate((0.0, 0.0, -depth_mm + height / 2)),
            name="part",
        )

    assembly.export(str(source_step), exportType="STEP")

    return execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=tmp_path / "retention.step",
            policy=EdgeCapturePolicy(),
        )
    )


def planar_results(report: InstallationPathReport) -> dict[str, tuple[bool, float]]:
    return {
        result.name: (result.passed, result.maximum_intersection_mm3)
        for result in report.results
        if result.name.startswith("planar_from_")
    }


def test_open_edges_allow_a_planar_slide_on_a_plain_board(tmp_path: Path) -> None:
    report = analyze_edge_installation_paths(
        edge_execution_with_underside_part(tmp_path, depth_mm=None),
        candidate_id="candidate-r001",
    )

    assert planar_results(report) == {
        "planar_from_negative_x": (True, 0.0),
        "planar_from_positive_x": (True, 0.0),
        "planar_from_positive_y": (True, 0.0),
    }


def test_parts_in_base_holes_block_planar_slides(tmp_path: Path) -> None:
    """Regression for UNO R4: the clip-only analysis reported collision-free
    slides that its pins, seated in base clearance holes, cannot make."""

    report = analyze_edge_installation_paths(
        edge_execution_with_underside_part(tmp_path, depth_mm=0.3),
        candidate_id="candidate-r001",
    )

    results = planar_results(report)
    assert set(results) == {
        "planar_from_negative_x",
        "planar_from_positive_x",
        "planar_from_positive_y",
    }
    assert all(passed is False for passed, _ in results.values())
    # The 2 x 2 mm part sweeps 0.3 mm deep into the hole wall.
    assert all(volume == pytest.approx(1.2, abs=1e-3) for _, volume in results.values())
