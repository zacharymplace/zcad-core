from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    BoardCorner,
    CornerCaptureFitCheck,
    CornerCapturePolicy,
    ProductionCornerExecutionRequest,
    execute_production_corner_capture,
)


def export_board_fixture(
    path: Path,
    *,
    blocked_corners: tuple[
        BoardCorner,
        ...,
    ] = (),
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

    positions = {
        BoardCorner.NEGATIVE_X_NEGATIVE_Y: (
            -18.5,
            -13.5,
        ),
        BoardCorner.NEGATIVE_X_POSITIVE_Y: (
            -18.5,
            13.5,
        ),
        BoardCorner.POSITIVE_X_NEGATIVE_Y: (
            18.5,
            -13.5,
        ),
        BoardCorner.POSITIVE_X_POSITIVE_Y: (
            18.5,
            13.5,
        ),
    }

    assembly = cq.Assembly()
    assembly.add(
        pcb,
        name="pcb",
    )

    for index, corner in enumerate(
        blocked_corners,
        start=1,
    ):
        x_mm, y_mm = positions[corner]

        component = (
            cq.Workplane("XY")
            .box(
                3.0,
                3.0,
                2.0,
            )
            .translate(
                (
                    x_mm,
                    y_mm,
                    2.6,
                )
            )
        )

        assembly.add(
            component,
            name=f"component-{index}",
        )

    assembly.export(
        str(path),
        exportType="STEP",
    )


def test_request_requires_step_output(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="STEP extension",
    ):
        ProductionCornerExecutionRequest(
            source_step=tmp_path / "board.step",
            pcb_solid_index=1,
            output_step=tmp_path / "output.stl",
            policy=CornerCapturePolicy(),
        )


def test_execution_exports_inspectable_step(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "board-corner-capture.step"

    export_board_fixture(source_step)

    result = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        )
    )

    assert result.passed is True
    assert result.output_step == output_step
    assert output_step.is_file()
    assert output_step.stat().st_size > 0

    exported = cq.importers.importStep(str(output_step)).val()

    assert exported is not None
    assert len(exported.Solids()) >= 1
    assert exported.BoundingBox().xlen > 40.0
    assert exported.BoundingBox().ylen > 30.0


def test_execution_uses_second_clear_diagonal(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "output.step"

    export_board_fixture(
        source_step,
        blocked_corners=(BoardCorner.NEGATIVE_X_NEGATIVE_Y,),
    )

    result = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        )
    )

    assert result.derivation.selected_corners == (
        BoardCorner.NEGATIVE_X_POSITIVE_Y,
        BoardCorner.POSITIVE_X_NEGATIVE_Y,
    )
    assert result.passed is True


def test_component_clearance_report_is_evidence_backed(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "board.step"
    output_step = tmp_path / "output.step"

    export_board_fixture(source_step)

    result = execute_production_corner_capture(
        ProductionCornerExecutionRequest(
            source_step=source_step,
            pcb_solid_index=1,
            output_step=output_step,
            policy=CornerCapturePolicy(),
        )
    )

    component_result = next(
        item
        for item in result.execution.report.results
        if (item.check is CornerCaptureFitCheck.COMPONENT_CLEARANCE)
    )

    assert component_result.passed is True
    assert "Production STEP evidence confirmed" in (component_result.detail)
    assert source_step.name in (component_result.detail)
    assert "production clearance remains unverified" not in (component_result.detail)


def test_no_clear_diagonal_fails_before_export(
    tmp_path: Path,
) -> None:
    source_step = tmp_path / "blocked.step"
    output_step = tmp_path / "output.step"

    export_board_fixture(
        source_step,
        blocked_corners=(
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
        ),
    )

    with pytest.raises(
        ValueError,
        match="two component-clear diagonal corners",
    ):
        execute_production_corner_capture(
            ProductionCornerExecutionRequest(
                source_step=source_step,
                pcb_solid_index=1,
                output_step=output_step,
                policy=CornerCapturePolicy(),
            )
        )

    assert not output_step.exists()
