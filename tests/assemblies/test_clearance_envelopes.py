"""Tests for directional assembly clearance envelopes."""

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    ClearanceEnvelope,
    DeviceAssembly,
    Placement,
)


def _box(
    *,
    identifier: str,
    x_mm: float,
    envelope: ClearanceEnvelope | None = None,
) -> AssemblyComponent:
    return AssemblyComponent(
        identifier=identifier,
        geometry=cq.Workplane("XY").box(
            10.0,
            10.0,
            10.0,
            centered=(True, True, False),
        ),
        placement=Placement(
            x_mm=x_mm,
        ),
        clearance_envelope=(envelope if envelope is not None else ClearanceEnvelope()),
    )


def test_default_envelope_requires_no_clearance() -> None:
    envelope = ClearanceEnvelope()

    assert not envelope.has_clearance


def test_negative_directional_clearance_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="negative_x_mm",
    ):
        ClearanceEnvelope(
            negative_x_mm=-0.1,
        )


def test_positive_x_envelope_detects_violation() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=2.0,
                ),
            ),
            _box(
                identifier="second",
                x_mm=11.0,
            ),
        )
    )

    report = assembly.analyze_interference()

    assert len(report.clearance_violations) == 1

    finding = report.clearance_violations[0]

    assert finding.clearance_source == "envelope"
    assert finding.measured_clearance_mm == pytest.approx(1.0)
    assert finding.required_clearance_mm == pytest.approx(2.0)


def test_directional_envelope_is_asymmetric() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=2.0,
                ),
            ),
            _box(
                identifier="second",
                x_mm=-11.0,
            ),
        )
    )

    report = assembly.analyze_interference()

    assert not report.has_findings


def test_opposing_envelopes_are_combined() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=1.0,
                ),
            ),
            _box(
                identifier="second",
                x_mm=12.0,
                envelope=ClearanceEnvelope(
                    negative_x_mm=2.0,
                ),
            ),
        )
    )

    report = assembly.analyze_interference()

    assert len(report.clearance_violations) == 1

    finding = report.clearance_violations[0]

    assert finding.measured_clearance_mm == pytest.approx(2.0)
    assert finding.required_clearance_mm == pytest.approx(3.0)


def test_exact_envelope_boundary_passes() -> None:
    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=1.0,
                ),
            ),
            _box(
                identifier="second",
                x_mm=13.0,
                envelope=ClearanceEnvelope(
                    negative_x_mm=2.0,
                ),
            ),
        )
    )

    report = assembly.analyze_interference()

    assert not report.has_findings
