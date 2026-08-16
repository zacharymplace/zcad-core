from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    CornerCapturePolicy,
    InstallationPathPlan,
    ProductionCornerExecutionRequest,
    analyze_installation_paths,
    execute_production_corner_capture,
    write_installation_path_report,
)


def production_execution(
    tmp_path: Path,
):
    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    source_step = tmp_path / "board.step"
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.export(
        str(source_step),
        exportType="STEP",
    )

    return execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=(tmp_path / "retention.step"),
            policy=CornerCapturePolicy(),
        )
    )


def test_analyzes_default_rigid_paths(
    tmp_path: Path,
) -> None:
    report = analyze_installation_paths(
        production_execution(tmp_path),
        candidate_id="candidate-r001",
    )

    assert report.schema_version == "1.0.0"
    assert report.results
    assert any(result.name == "vertical" for result in report.results)
    assert all(result.sample_count > 0 for result in report.results)
    assert "do not model" in report.limitation


def test_vertical_path_detects_capture_collision(
    tmp_path: Path,
) -> None:
    report = analyze_installation_paths(
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
    report = analyze_installation_paths(
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
