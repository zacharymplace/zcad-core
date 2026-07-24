"""Tests for assembly interference detection."""

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    DeviceAssembly,
    Placement,
    component_pair,
)


def _box(
    *,
    identifier: str,
    x_mm: float,
    width_mm: float = 10.0,
) -> AssemblyComponent:
    return AssemblyComponent(
        identifier=identifier,
        geometry=cq.Workplane("XY").box(
            width_mm,
            10.0,
            10.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=x_mm,
        ),
    )


def test_overlapping_components_report_collision() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=5.0,
            ),
        )
    )

    report = assembly.analyze_interference()

    assert report.has_findings
    assert len(report.collisions) == 1
    assert not report.clearance_violations

    finding = report.collisions[0]

    assert finding.pair == component_pair(
        "first",
        "second",
    )
    assert finding.intersection_volume_mm3 == pytest.approx(500.0)


def test_separated_components_do_not_collide() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=15.0,
            ),
        )
    )

    report = assembly.analyze_interference()

    assert not report.has_findings
    assert not report.collisions


def test_touching_faces_are_not_volume_collision() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=10.0,
            ),
        )
    )

    report = assembly.analyze_interference()

    assert not report.collisions


def test_allowed_contact_pair_suppresses_collision() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="board",
                x_mm=0.0,
            ),
            _box(
                identifier="connector",
                x_mm=5.0,
            ),
        )
    )

    report = assembly.analyze_interference(
        allowed_contact_pairs=(
            component_pair(
                "board",
                "connector",
            ),
        )
    )

    assert not report.has_findings


def test_minimum_clearance_violation_is_reported() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=11.0,
            ),
        )
    )

    report = assembly.analyze_interference(
        minimum_clearance_mm=2.0,
    )

    assert not report.collisions
    assert len(report.clearance_violations) == 1

    finding = report.clearance_violations[0]

    assert finding.measured_clearance_mm == pytest.approx(1.0)
    assert finding.required_clearance_mm == pytest.approx(2.0)


def test_sufficient_clearance_passes() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=13.0,
            ),
        )
    )

    report = assembly.analyze_interference(
        minimum_clearance_mm=2.0,
    )

    assert not report.has_findings


def test_diagonal_clearance_uses_euclidean_distance() -> None:
    first = AssemblyComponent(
        identifier="first",
        geometry=cq.Workplane("XY").box(
            10.0,
            10.0,
            10.0,
            centered=(True, True, False),
        ),
    )

    second = AssemblyComponent(
        identifier="second",
        geometry=cq.Workplane("XY").box(
            10.0,
            10.0,
            10.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=11.0,
            y_mm=11.0,
        ),
    )

    assembly = DeviceAssembly(
        (
            first,
            second,
        )
    )

    report = assembly.analyze_interference(
        minimum_clearance_mm=1.5,
    )

    assert len(report.clearance_violations) == 1

    assert report.clearance_violations[0].measured_clearance_mm == pytest.approx(2**0.5)


def test_negative_clearance_is_rejected() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
            ),
            _box(
                identifier="second",
                x_mm=20.0,
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="minimum_clearance_mm",
    ):
        assembly.analyze_interference(
            minimum_clearance_mm=-0.1,
        )


def test_component_pair_rejects_same_identifier() -> None:
    with pytest.raises(
        ValueError,
        match="must differ",
    ):
        component_pair(
            "board",
            "board",
        )
