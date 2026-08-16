from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.retention import (
    BoardCorner,
    CornerCapturePolicy,
    ProductionBoardCornerAdapter,
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

    corner_positions = {
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
        x_mm, y_mm = corner_positions[corner]

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


def test_import_identifies_pcb_and_components(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "board.step"

    export_board_fixture(
        step_path,
        blocked_corners=(BoardCorner.NEGATIVE_X_NEGATIVE_Y,),
    )

    adapter = ProductionBoardCornerAdapter()
    model = adapter.import_model(
        source_step=step_path,
        pcb_solid_index=1,
    )

    assert model.source_step == step_path
    assert model.pcb_solid_index == 1
    assert model.pcb.BoundingBox().xlen == pytest.approx(40.0)
    assert model.pcb.BoundingBox().ylen == pytest.approx(30.0)
    assert len(model.component_solids) == 1


def test_clear_board_selects_first_diagonal(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "clear-board.step"

    export_board_fixture(step_path)

    adapter = ProductionBoardCornerAdapter()
    model = adapter.import_model(
        source_step=step_path,
        pcb_solid_index=1,
    )

    derivation = adapter.derive(
        model=model,
        policy=CornerCapturePolicy(),
    )

    assert derivation.selected_corners == (
        BoardCorner.NEGATIVE_X_NEGATIVE_Y,
        BoardCorner.POSITIVE_X_POSITIVE_Y,
    )
    assert derivation.request.board_thickness_mm == pytest.approx(1.6)
    assert len(derivation.request.locations) == 2


def test_blocked_first_diagonal_selects_second(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "blocked-board.step"

    export_board_fixture(
        step_path,
        blocked_corners=(BoardCorner.NEGATIVE_X_NEGATIVE_Y,),
    )

    adapter = ProductionBoardCornerAdapter()
    model = adapter.import_model(
        source_step=step_path,
        pcb_solid_index=1,
    )

    derivation = adapter.derive(
        model=model,
        policy=CornerCapturePolicy(),
    )

    assert derivation.selected_corners == (
        BoardCorner.NEGATIVE_X_POSITIVE_Y,
        BoardCorner.POSITIVE_X_NEGATIVE_Y,
    )

    blocked = next(
        result
        for result in derivation.clearances
        if result.corner is BoardCorner.NEGATIVE_X_NEGATIVE_Y
    )

    assert blocked.clear is False
    assert (blocked.interfering_solid_indices) == (1,)


def test_no_clear_diagonal_fails_closed(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "rejected-board.step"

    export_board_fixture(
        step_path,
        blocked_corners=(
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
        ),
    )

    adapter = ProductionBoardCornerAdapter()
    model = adapter.import_model(
        source_step=step_path,
        pcb_solid_index=1,
    )

    with pytest.raises(
        ValueError,
        match="two component-clear diagonal corners",
    ):
        adapter.derive(
            model=model,
            policy=CornerCapturePolicy(),
        )


def test_invalid_pcb_index_is_rejected(
    tmp_path: Path,
) -> None:
    step_path = tmp_path / "board.step"
    export_board_fixture(step_path)

    adapter = ProductionBoardCornerAdapter()

    with pytest.raises(
        ValueError,
        match="exceeds imported solid count",
    ):
        adapter.import_model(
            source_step=step_path,
            pcb_solid_index=50,
        )
