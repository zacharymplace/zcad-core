"""Tests for reusable rectangular hardware components."""

import pytest

from zcad_core.assemblies import (
    ClearanceEnvelope,
    Placement,
    build_rectangular_hardware_component,
)


def test_rectangular_hardware_component_builds_proxy() -> None:
    component = build_rectangular_hardware_component(
        identifier="board",
        hardware_identifier="TEST_BOARD",
        kind="pcb",
        width_mm=21.0,
        depth_mm=51.0,
        height_mm=1.0,
        placement=Placement(
            x_mm=2.0,
            y_mm=-3.0,
            z_mm=4.0,
        ),
    )

    local_bounds = component.geometry.val().BoundingBox()
    transformed_bounds = component.transformed_geometry().val().BoundingBox()

    assert local_bounds.xlen == pytest.approx(21.0)
    assert local_bounds.ylen == pytest.approx(51.0)
    assert local_bounds.zlen == pytest.approx(1.0)

    assert transformed_bounds.center.x == (pytest.approx(2.0))
    assert transformed_bounds.center.y == (pytest.approx(-3.0))
    assert transformed_bounds.zmin == (pytest.approx(4.0))


def test_rectangular_hardware_component_preserves_metadata() -> None:
    component = build_rectangular_hardware_component(
        identifier="display",
        hardware_identifier="TEST_DISPLAY",
        kind="display",
        width_mm=28.0,
        depth_mm=28.0,
        height_mm=4.0,
        metadata={
            "mount_style": "bezel",
            "active_width_mm": 22.0,
        },
    )

    assert component.metadata == {
        "kind": "display",
        "hardware_identifier": "TEST_DISPLAY",
        "width_mm": 28.0,
        "depth_mm": 28.0,
        "height_mm": 4.0,
        "mount_style": "bezel",
        "active_width_mm": 22.0,
    }


def test_rectangular_hardware_component_preserves_clearance() -> None:
    envelope = ClearanceEnvelope(
        positive_z_mm=1.25,
    )

    component = build_rectangular_hardware_component(
        identifier="board",
        hardware_identifier="TEST_BOARD",
        kind="pcb",
        width_mm=21.0,
        depth_mm=51.0,
        height_mm=1.0,
        clearance_envelope=envelope,
    )

    assert component.clearance_envelope is envelope


@pytest.mark.parametrize(
    (
        "field",
        "value",
        "message",
    ),
    (
        (
            "identifier",
            "",
            "component identifier",
        ),
        (
            "hardware_identifier",
            "",
            "hardware identifier",
        ),
        (
            "kind",
            "",
            "component kind",
        ),
        (
            "width_mm",
            0.0,
            "width_mm",
        ),
        (
            "depth_mm",
            -1.0,
            "depth_mm",
        ),
        (
            "height_mm",
            0.0,
            "height_mm",
        ),
    ),
)
def test_rectangular_hardware_component_rejects_invalid_values(
    field: str,
    value: str | float,
    message: str,
) -> None:
    arguments = {
        "identifier": "component",
        "hardware_identifier": "TEST",
        "kind": "hardware",
        "width_mm": 10.0,
        "depth_mm": 8.0,
        "height_mm": 2.0,
    }
    arguments[field] = value

    with pytest.raises(
        ValueError,
        match=message,
    ):
        build_rectangular_hardware_component(
            **arguments,
        )


@pytest.mark.parametrize(
    "canonical_key",
    (
        "kind",
        "hardware_identifier",
        "width_mm",
        "depth_mm",
        "height_mm",
    ),
)
def test_additional_metadata_cannot_override_canonical_values(
    canonical_key: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="canonical keys",
    ):
        build_rectangular_hardware_component(
            identifier="component",
            hardware_identifier="TEST",
            kind="hardware",
            width_mm=10.0,
            depth_mm=8.0,
            height_mm=2.0,
            metadata={
                canonical_key: "override",
            },
        )
