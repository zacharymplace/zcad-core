from __future__ import annotations

import cadquery as cq
import pytest

from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.retention import (
    BoardCorner,
    CornerCaptureLocation,
    CornerCaptureParameters,
    CornerCapturePolicy,
    CornerCaptureRequest,
    RetentionBackend,
    RetentionEngine,
    RetentionStrategy,
    SyntheticCornerCaptureBackend,
)


def opposite_locations() -> tuple[CornerCaptureLocation, ...]:
    return (
        CornerCaptureLocation(
            corner=(BoardCorner.NEGATIVE_X_NEGATIVE_Y),
            x_mm=-20.0,
            y_mm=-15.0,
        ),
        CornerCaptureLocation(
            corner=(BoardCorner.POSITIVE_X_POSITIVE_Y),
            x_mm=20.0,
            y_mm=15.0,
        ),
    )


def all_locations() -> tuple[CornerCaptureLocation, ...]:
    return (
        CornerCaptureLocation(
            BoardCorner.NEGATIVE_X_NEGATIVE_Y,
            -20.0,
            -15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.NEGATIVE_X_POSITIVE_Y,
            -20.0,
            15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.POSITIVE_X_NEGATIVE_Y,
            20.0,
            -15.0,
        ),
        CornerCaptureLocation(
            BoardCorner.POSITIVE_X_POSITIVE_Y,
            20.0,
            15.0,
        ),
    )


def valid_request() -> CornerCaptureRequest:
    return CornerCaptureRequest(
        board_thickness_mm=1.6,
        locations=opposite_locations(),
        policy=CornerCapturePolicy(),
    )


def test_synthetic_backend_satisfies_generic_protocol() -> None:
    backend = SyntheticCornerCaptureBackend()

    assert isinstance(
        backend,
        RetentionBackend,
    )


def test_register_and_resolve_backend() -> None:
    engine = RetentionEngine()
    backend = SyntheticCornerCaptureBackend()

    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        backend,
    )

    assert engine.resolve(RetentionStrategy.CORNER_CAPTURE) is backend


def test_duplicate_registration_is_rejected() -> None:
    engine = RetentionEngine()
    backend = SyntheticCornerCaptureBackend()

    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        backend,
    )

    with pytest.raises(
        ValueError,
        match="already registered",
    ):
        engine.register(
            RetentionStrategy.CORNER_CAPTURE,
            backend,
        )


def test_registration_can_be_replaced_explicitly() -> None:
    engine = RetentionEngine()
    first = SyntheticCornerCaptureBackend()
    second = SyntheticCornerCaptureBackend()

    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        first,
    )
    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        second,
        replace=True,
    )

    assert engine.resolve(RetentionStrategy.CORNER_CAPTURE) is second


def test_unregistered_strategy_fails_closed() -> None:
    engine = RetentionEngine()

    with pytest.raises(
        KeyError,
        match="No retention backend registered",
    ):
        engine.resolve(RetentionStrategy.CORNER_CAPTURE)


def test_invalid_backend_is_rejected() -> None:
    engine = RetentionEngine()

    with pytest.raises(
        TypeError,
        match="RetentionBackend",
    ):
        engine.register(
            RetentionStrategy.CORNER_CAPTURE,
            object(),  # type: ignore[arg-type]  # the invalid backend under test
        )


def test_engine_executes_complete_lifecycle() -> None:
    engine = RetentionEngine()
    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        SyntheticCornerCaptureBackend(),
    )

    base = (
        cq.Workplane("XY")
        .box(
            50.0,
            40.0,
            2.0,
        )
        .translate(
            (
                0.0,
                0.0,
                -1.0,
            )
        )
    )
    base_volume = workplane_shape(base).Volume()

    execution = engine.execute(
        strategy=RetentionStrategy.CORNER_CAPTURE,
        request=valid_request(),
        model=base,
    )

    assert execution.strategy is (RetentionStrategy.CORNER_CAPTURE)
    assert isinstance(
        execution.parameters,
        CornerCaptureParameters,
    )
    assert isinstance(
        execution.model,
        cq.Workplane,
    )
    assert workplane_shape(execution.model).Volume() > base_volume
    assert execution.report.passed is True
    assert execution.passed is True


def test_engine_preserves_failed_fit_report() -> None:
    engine = RetentionEngine()
    engine.register(
        RetentionStrategy.CORNER_CAPTURE,
        SyntheticCornerCaptureBackend(),
    )

    request = CornerCaptureRequest(
        board_thickness_mm=1.6,
        locations=all_locations(),
        policy=CornerCapturePolicy(),
    )

    execution = engine.execute(
        strategy=RetentionStrategy.CORNER_CAPTURE,
        request=request,
        model=cq.Workplane("XY").box(
            50.0,
            40.0,
            2.0,
        ),
    )

    assert execution.report.passed is False
    assert execution.passed is False
