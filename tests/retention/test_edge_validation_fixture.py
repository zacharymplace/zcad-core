from __future__ import annotations

from pathlib import Path
from typing import cast

import cadquery as cq

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention.edge_capture import EdgeCapturePolicy
from zcad_core.retention.production_board import import_production_board_model
from zcad_core.retention.production_edge_execution import (
    ProductionEdgeExecutionRequest,
    ProductionEdgeExecutionResult,
    execute_production_edge_capture,
)
from zcad_core.retention.validation_fixture import (
    ValidationFixturePolicy,
    _build_base,
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

    shape = workplane_shape(fixture)

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


def test_base_is_relieved_beyond_an_overhanging_connector(
    tmp_path: Path,
) -> None:
    pcb = cq.Workplane("XY").box(40.0, 30.0, 1.6).translate((0.0, 0.0, 0.8))
    # A 10 mm wide connector hanging 2 mm past the positive-x edge.
    usb = cq.Workplane("XY").box(8.0, 10.0, 3.0).translate((18.0, 0.0, 3.1))
    assembly = cq.Assembly()
    assembly.add(pcb, name="pcb")
    assembly.add(usb, name="usb")
    source = tmp_path / "board.step"
    assembly.export(str(source), exportType="STEP")

    model = import_production_board_model(source_step=source, pcb_solid_index=1)
    base = cast(
        cq.Solid, workplane_shape(_build_base(model, ValidationFixturePolicy()))
    )

    def solid_at(x: float, y: float) -> bool:
        return base.isInside(cq.Vector(x, y, -1.0))

    assert solid_at(19.0, 10.0)  # margin beside the connector stays
    assert not solid_at(21.0, 0.0)  # margin under the plug is cut away
    assert solid_at(0.0, 0.0)  # base under the board is untouched
