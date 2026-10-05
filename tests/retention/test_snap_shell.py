from __future__ import annotations

import pytest

from zcad_core.retention.snap_shell import (
    SnapShellLocation,
    SnapShellParameters,
    SnapShellPolicy,
    as_snap_shell_parameters,
    derive_snap_shell_parameters,
)


def spaced_locations() -> tuple[SnapShellLocation, ...]:
    return (
        SnapShellLocation(label="north", x_mm=0.0, y_mm=12.0),
        SnapShellLocation(label="south", x_mm=0.0, y_mm=-12.0),
        SnapShellLocation(label="east", x_mm=13.0, y_mm=0.0),
    )


def test_default_policy_is_valid() -> None:
    policy = SnapShellPolicy()

    assert policy.clip_width_mm == pytest.approx(3.0)
    assert policy.wall_mm == pytest.approx(1.0)
    assert policy.clip_height_mm == pytest.approx(1.5)
    assert policy.overhang_mm == pytest.approx(0.6)
    assert policy.compliant_span_mm == pytest.approx(2.0)


@pytest.mark.parametrize(
    "field",
    (
        "clip_width_mm",
        "wall_mm",
        "clip_height_mm",
        "overhang_mm",
        "compliant_span_mm",
        "ledge_mm",
        "rim_height_mm",
    ),
)
def test_positive_policy_dimensions_are_required(
    field: str,
) -> None:
    values = {
        "clip_width_mm": 3.0,
        "wall_mm": 1.0,
        "clip_height_mm": 1.5,
        "overhang_mm": 0.6,
        "clearance_mm": 0.15,
        "compliant_span_mm": 2.0,
        "ledge_mm": 1.5,
        "rim_height_mm": 1.0,
    }
    values[field] = 0.0

    with pytest.raises(
        ValueError,
        match=field,
    ):
        SnapShellPolicy(**values)


def test_clearance_cannot_be_negative() -> None:
    with pytest.raises(
        ValueError,
        match="clearance_mm",
    ):
        SnapShellPolicy(clearance_mm=-0.01)


def test_overhang_must_be_less_than_compliant_span() -> None:
    with pytest.raises(
        ValueError,
        match="overhang_mm",
    ):
        SnapShellPolicy(
            overhang_mm=2.0,
            compliant_span_mm=2.0,
        )


def test_the_rim_must_stand_taller_than_the_lips_let_the_device_lift() -> None:
    with pytest.raises(ValueError, match="rim_height_mm must be greater"):
        SnapShellPolicy(clearance_mm=1.0, rim_height_mm=1.0)


def test_the_ledge_must_leave_the_underside_open() -> None:
    with pytest.raises(ValueError, match="no opening under the device"):
        derive_snap_shell_parameters(
            device_thickness_mm=4.7,
            device_length_mm=26.0,
            device_width_mm=24.0,
            locations=spaced_locations(),
            policy=SnapShellPolicy(ledge_mm=12.0),
        )


def test_derivation_preserves_validated_policy() -> None:
    policy = SnapShellPolicy(
        clip_width_mm=3.5,
        wall_mm=1.1,
        clip_height_mm=1.6,
        overhang_mm=0.5,
        clearance_mm=0.2,
        compliant_span_mm=2.2,
        ledge_mm=2.0,
        rim_height_mm=1.2,
    )

    result = derive_snap_shell_parameters(
        device_thickness_mm=4.7,
        device_length_mm=26.0,
        device_width_mm=24.0,
        locations=spaced_locations(),
        policy=policy,
    )

    assert result.device_thickness_mm == pytest.approx(4.7)
    assert result.locations == spaced_locations()
    assert result.clip_width_mm == pytest.approx(3.5)
    assert result.wall_mm == pytest.approx(1.1)
    assert result.clip_height_mm == pytest.approx(1.6)
    assert result.overhang_mm == pytest.approx(0.5)
    assert result.clearance_mm == pytest.approx(0.2)
    assert result.compliant_span_mm == pytest.approx(2.2)
    assert (result.device_length_mm, result.device_width_mm) == (26.0, 24.0)
    assert result.ledge_mm == pytest.approx(2.0)
    assert result.rim_height_mm == pytest.approx(1.2)


def test_two_locations_are_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="at least three",
    ):
        SnapShellParameters(
            device_thickness_mm=4.7,
            locations=spaced_locations()[:2],
            clip_width_mm=3.0,
            wall_mm=1.0,
            clip_height_mm=1.5,
            overhang_mm=0.6,
            clearance_mm=0.15,
            compliant_span_mm=2.0,
            device_length_mm=26.0,
            device_width_mm=24.0,
            ledge_mm=1.5,
            rim_height_mm=1.0,
        )


def test_duplicate_labels_are_rejected() -> None:
    locations = (
        SnapShellLocation(label="north", x_mm=0.0, y_mm=12.0),
        SnapShellLocation(label="north", x_mm=13.0, y_mm=0.0),
        SnapShellLocation(label="south", x_mm=0.0, y_mm=-12.0),
    )

    with pytest.raises(
        ValueError,
        match="unique",
    ):
        derive_snap_shell_parameters(
            device_thickness_mm=4.7,
            device_length_mm=26.0,
            device_width_mm=24.0,
            locations=locations,
            policy=SnapShellPolicy(),
        )


def test_overlapping_locations_are_rejected() -> None:
    location = spaced_locations()[0]
    other = SnapShellLocation(
        label="near-north",
        x_mm=location.x_mm + 1e-9,
        y_mm=location.y_mm,
    )

    with pytest.raises(
        ValueError,
        match="must not overlap",
    ):
        derive_snap_shell_parameters(
            device_thickness_mm=4.7,
            device_length_mm=26.0,
            device_width_mm=24.0,
            locations=(
                location,
                other,
                spaced_locations()[1],
            ),
            policy=SnapShellPolicy(),
        )


def test_empty_label_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="label",
    ):
        SnapShellLocation(label="  ", x_mm=0.0, y_mm=0.0)


def test_as_snap_shell_parameters_rejects_wrong_type() -> None:
    with pytest.raises(
        TypeError,
        match="SnapShellParameters",
    ):
        as_snap_shell_parameters(object())


def test_as_snap_shell_parameters_returns_matching_instance() -> None:
    parameters = derive_snap_shell_parameters(
        device_thickness_mm=4.7,
        device_length_mm=26.0,
        device_width_mm=24.0,
        locations=spaced_locations(),
        policy=SnapShellPolicy(),
    )

    assert as_snap_shell_parameters(parameters) is parameters
