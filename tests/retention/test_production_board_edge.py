from __future__ import annotations

from pathlib import Path

import cadquery as cq
import pytest

from zcad_core.geometry.types import BoardEdge
from zcad_core.retention.edge_capture import EdgeCapturePolicy
from zcad_core.retention.production_board import ProductionBoardModel
from zcad_core.retention.production_edge_board import ProductionBoardEdgeAdapter


def _box(
    *,
    x_center: float,
    y_center: float,
    z_center: float,
    x_len: float,
    y_len: float,
    z_len: float,
) -> cq.Solid:
    shape = (
        cq.Workplane("XY")
        .box(
            x_len,
            y_len,
            z_len,
        )
        .translate(
            (
                x_center,
                y_center,
                z_center,
            )
        )
        .val()
    )

    assert isinstance(shape, cq.Solid)

    return shape


def board_model(
    *,
    component_solids: tuple[cq.Solid, ...] = (),
) -> ProductionBoardModel:
    pcb = _box(
        x_center=20.0,
        y_center=15.0,
        z_center=0.8,
        x_len=40.0,
        y_len=30.0,
        z_len=1.6,
    )

    return ProductionBoardModel(
        source_step=Path("synthetic-board.step"),
        pcb_solid_index=1,
        shape=pcb,
        pcb=pcb,
        component_solids=component_solids,
    )


def test_edge_is_fully_clear_without_components() -> None:
    adapter = ProductionBoardEdgeAdapter()
    model = board_model()

    result = adapter.analyze_edge_clearance(
        model,
        BoardEdge.NEGATIVE_Y,
        minimum_span_mm=1.0,
    )

    assert len(result.clear_spans) == 1
    assert result.clear_spans[0].start_mm == pytest.approx(0.0, abs=1e-3)
    assert result.clear_spans[0].end_mm == pytest.approx(40.0, abs=1e-3)


def test_tall_component_splits_the_clear_span() -> None:
    tall_component = _box(
        x_center=20.0,
        y_center=1.0,
        z_center=3.0,
        x_len=6.0,
        y_len=2.0,
        z_len=6.0,
    )
    adapter = ProductionBoardEdgeAdapter()
    model = board_model(component_solids=(tall_component,))

    result = adapter.analyze_edge_clearance(
        model,
        BoardEdge.NEGATIVE_Y,
        minimum_span_mm=1.0,
    )

    assert len(result.clear_spans) == 2
    assert result.clear_spans[0].end_mm == pytest.approx(17.0, abs=1e-3)
    assert result.clear_spans[1].start_mm == pytest.approx(23.0, abs=1e-3)


def test_short_component_does_not_block_clearance() -> None:
    short_component = _box(
        x_center=20.0,
        y_center=1.0,
        z_center=1.6,
        x_len=6.0,
        y_len=2.0,
        z_len=0.2,
    )
    adapter = ProductionBoardEdgeAdapter(vertical_margin_mm=0.10)
    model = board_model(component_solids=(short_component,))

    result = adapter.analyze_edge_clearance(
        model,
        BoardEdge.NEGATIVE_Y,
        minimum_span_mm=1.0,
    )

    assert len(result.clear_spans) == 1
    assert result.clear_spans[0].length_mm == pytest.approx(40.0, abs=1e-3)


def test_component_outside_engagement_depth_does_not_block() -> None:
    far_component = _box(
        x_center=20.0,
        y_center=10.0,
        z_center=3.0,
        x_len=6.0,
        y_len=2.0,
        z_len=6.0,
    )
    adapter = ProductionBoardEdgeAdapter(engagement_depth_mm=2.5)
    model = board_model(component_solids=(far_component,))

    result = adapter.analyze_edge_clearance(
        model,
        BoardEdge.NEGATIVE_Y,
        minimum_span_mm=1.0,
    )

    assert len(result.clear_spans) == 1
    assert result.clear_spans[0].length_mm == pytest.approx(40.0, abs=1e-3)


def test_derive_picks_widest_qualifying_span() -> None:
    blocker_on_negative_y = _box(
        x_center=20.0,
        y_center=1.0,
        z_center=3.0,
        x_len=30.0,
        y_len=2.0,
        z_len=6.0,
    )
    adapter = ProductionBoardEdgeAdapter(minimum_anchor_separation_mm=2.0)
    model = board_model(component_solids=(blocker_on_negative_y,))

    derivation = adapter.derive(
        model=model,
        policy=EdgeCapturePolicy(arm_width_mm=3.0),
    )

    assert derivation.selected_edge is not BoardEdge.NEGATIVE_Y
    assert len(derivation.request.locations) == 2


def test_derive_raises_when_no_edge_qualifies() -> None:
    blockers = tuple(
        _box(
            x_center=x,
            y_center=y,
            z_center=3.0,
            x_len=45.0,
            y_len=45.0,
            z_len=6.0,
        )
        for x, y in ((20.0, 0.0), (20.0, 30.0), (0.0, 15.0), (40.0, 15.0))
    )
    adapter = ProductionBoardEdgeAdapter()
    model = board_model(component_solids=blockers)

    with pytest.raises(
        ValueError,
        match="does not have a component-clear edge span",
    ):
        adapter.derive(
            model=model,
            policy=EdgeCapturePolicy(),
        )


def test_component_clearance_widens_the_blocked_interval() -> None:
    tall_component = _box(
        x_center=20.0,
        y_center=1.0,
        z_center=3.0,
        x_len=6.0,
        y_len=2.0,
        z_len=6.0,
    )
    adapter = ProductionBoardEdgeAdapter()
    model = board_model(component_solids=(tall_component,))

    result = adapter.analyze_edge_clearance(
        model,
        BoardEdge.NEGATIVE_Y,
        minimum_span_mm=1.0,
        component_clearance_mm=0.25,
    )

    assert result.clear_spans[0].end_mm == pytest.approx(16.75, abs=1e-3)
    assert result.clear_spans[1].start_mm == pytest.approx(23.25, abs=1e-3)


def test_component_just_past_engagement_depth_blocks_within_clearance() -> None:
    """A component starting inside the clearance band beyond the engagement
    strip would sit within board_clearance_mm of the clip's inner face."""

    near_component = _box(
        x_center=20.0,
        y_center=3.6,
        z_center=3.0,
        x_len=6.0,
        y_len=2.0,
        z_len=6.0,
    )
    adapter = ProductionBoardEdgeAdapter(engagement_depth_mm=2.5)
    model = board_model(component_solids=(near_component,))

    without = adapter.analyze_edge_clearance(
        model, BoardEdge.NEGATIVE_Y, minimum_span_mm=1.0
    )
    with_clearance = adapter.analyze_edge_clearance(
        model, BoardEdge.NEGATIVE_Y, minimum_span_mm=1.0, component_clearance_mm=0.25
    )

    assert len(without.clear_spans) == 1
    assert len(with_clearance.clear_spans) == 2


def test_negative_component_clearance_is_rejected() -> None:
    adapter = ProductionBoardEdgeAdapter()

    with pytest.raises(ValueError, match="component_clearance_mm cannot be negative"):
        adapter.analyze_edge_clearance(
            board_model(),
            BoardEdge.NEGATIVE_Y,
            minimum_span_mm=1.0,
            component_clearance_mm=-0.1,
        )


def test_derive_keeps_board_clearance_from_components_at_span_ends() -> None:
    """Regression for UNO R4 r004, whose clip ended flush against a header."""

    blockers = (
        _box(
            x_center=10.0, y_center=1.0, z_center=3.0, x_len=2.54, y_len=2.54, z_len=6.0
        ),
        _box(
            x_center=30.0, y_center=1.0, z_center=3.0, x_len=2.54, y_len=2.54, z_len=6.0
        ),
        # Block every other edge so the negative_y span between them is chosen.
        _box(
            x_center=20.0, y_center=30.0, z_center=3.0, x_len=45.0, y_len=6.0, z_len=6.0
        ),
        _box(
            x_center=0.0, y_center=15.0, z_center=3.0, x_len=6.0, y_len=35.0, z_len=6.0
        ),
        _box(
            x_center=40.0, y_center=15.0, z_center=3.0, x_len=6.0, y_len=35.0, z_len=6.0
        ),
    )
    policy = EdgeCapturePolicy(arm_width_mm=3.0, board_clearance_mm=0.25)
    adapter = ProductionBoardEdgeAdapter(minimum_anchor_separation_mm=2.0)

    derivation = adapter.derive(
        model=board_model(component_solids=blockers), policy=policy
    )

    assert derivation.selected_edge is BoardEdge.NEGATIVE_Y
    assert derivation.selected_span.start_mm == pytest.approx(11.27 + 0.25, abs=1e-3)
    assert derivation.selected_span.end_mm == pytest.approx(28.73 - 0.25, abs=1e-3)
