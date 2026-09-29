from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention import (
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    ProductionCornerExecutionResult,
    ValidationFixturePolicy,
    build_validation_fixture,
    execute_production_corner_capture,
    export_validation_fixture,
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
) -> ProductionCornerExecutionResult:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "capture.step"

    export_clear_board(source_step)

    return execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        )
    )


def test_fixture_is_connected_to_base(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)

    fixture = build_validation_fixture(
        execution,
        policy=ValidationFixturePolicy(),
    )

    shape = workplane_shape(fixture)

    assert shape is not None

    bounds = shape.BoundingBox()

    pcb_bottom = execution.board_model.pcb.BoundingBox().zmin

    # The base's top sits at the PCB's underside, wherever the model puts it.
    assert bounds.zmin == pytest.approx(pcb_bottom - 2.0)
    assert bounds.zmax > pcb_bottom
    assert shape.Volume() > 0.0


def test_fixture_exports_stl(
    tmp_path: Path,
) -> None:
    execution = production_execution(tmp_path)
    output_path = tmp_path / "fixture.stl"

    artifact = export_validation_fixture(
        execution,
        output_path=output_path,
        policy=ValidationFixturePolicy(),
    )

    assert artifact.stl_path == output_path
    assert output_path.is_file()
    assert output_path.stat().st_size > 0


def test_fixture_policy_fails_on_invalid_dimensions() -> None:
    try:
        ValidationFixturePolicy(base_thickness_mm=0.0)
    except ValueError as error:
        assert "base_thickness_mm" in str(error)
    else:
        raise AssertionError("Invalid fixture policy passed")
