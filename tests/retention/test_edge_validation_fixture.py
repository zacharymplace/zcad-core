from __future__ import annotations

from pathlib import Path

import cadquery as cq

from zcad_core.retention.edge_capture import EdgeCapturePolicy
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionRequest,
    ProductionEdgeExecutionResult,
    execute_production_edge_capture,
)
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    build_edge_validation_fixture,
    export_edge_validation_fixture,
)


def export_clear_board(
    path: Path,
) -> None:
    pcb = (
        cq.Workplane("XY")
        .box(
            40.0,
            30.0,
            1.6,
        )
        .translate(
            (
                0.0,
                0.0,
                0.8,
            )
        )
    )

    marker = (
        cq.Workplane("XY")
        .box(
            1.0,
            1.0,
            1.0,
        )
        .translate(
            (
                100.0,
                100.0,
                100.0,
            )
        )
    )

    assembly = cq.Assembly()
    assembly.add(marker, name="marker")
    assembly.add(pcb, name="pcb")
    assembly.export(
        str(path),
        exportType="STEP",
    )


def production_execution(
    tmp_path: Path,
) -> ProductionEdgeExecutionResult:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"

    export_clear_board(source_step)

    return execute_production_edge_capture(
        ProductionEdgeExecutionRequest(
            # solid 1 is the 1x1x1 marker (added to the assembly first);
            # solid 2 is the actual 40x30x1.6 board. EdgeOutlineAnalyzer
            # validates engagement_depth_mm against the PCB argument's own
            # extents, so (unlike corner capture, which has no such
            # check) pointing pcb_solid_index at the marker fails loudly.
            source_step=source_step,
            pcb_solid_index=2,
            output_step=output_step,
            policy=EdgeCapturePolicy(),
        )
    )


def test_fixture_is_connected_to_base(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)

    fixture = build_edge_validation_fixture(
        execution,
        policy=ValidationFixturePolicy(),
    )

    shape = fixture.val()

    assert shape is not None

    bounds = shape.BoundingBox()

    assert bounds.zmin == -2.0
    assert bounds.zmax > 0.0
    assert shape.Volume() > 0.0


def test_fixture_exports_stl(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_path = tmp_path / "fixture.stl"

    artifact = export_edge_validation_fixture(
        execution,
        output_path=output_path,
        policy=ValidationFixturePolicy(),
    )

    assert artifact.stl_path == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0
