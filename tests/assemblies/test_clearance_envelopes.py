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


def test_policy_overrides_embedded_envelope() -> None:
    from zcad_core.assemblies import ClearancePolicy

    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=0.5,
                ),
            ),
            _box(
                identifier="second",
                x_mm=12.0,
            ),
        )
    )

    assert not assembly.analyze_interference().has_findings

    report = assembly.analyze_interference(
        clearance_policy=ClearancePolicy(
            component_envelopes={
                "first": ClearanceEnvelope(
                    positive_x_mm=3.0,
                ),
            }
        )
    )

    assert len(report.clearance_violations) == 1
    assert report.clearance_violations[0].required_clearance_mm == pytest.approx(3.0)


def test_policy_preserves_unmentioned_envelopes() -> None:
    from zcad_core.assemblies import ClearancePolicy

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

    report = assembly.analyze_interference(
        clearance_policy=ClearancePolicy(
            component_envelopes={
                "first": ClearanceEnvelope(
                    positive_x_mm=1.5,
                ),
            }
        )
    )

    assert len(report.clearance_violations) == 1
    assert report.clearance_violations[0].required_clearance_mm == pytest.approx(3.5)


def test_policy_rejects_unknown_identifier() -> None:
    from zcad_core.assemblies import ClearancePolicy

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
        match="unknown component identifiers",
    ):
        assembly.analyze_interference(
            clearance_policy=ClearancePolicy(
                component_envelopes={
                    "missing": ClearanceEnvelope(
                        positive_x_mm=1.0,
                    ),
                }
            )
        )


def test_policy_does_not_mutate_component() -> None:
    from zcad_core.assemblies import ClearancePolicy

    assembly = DeviceAssembly(
        (
            _box(
                identifier="first",
                x_mm=0.0,
                envelope=ClearanceEnvelope(
                    positive_x_mm=0.5,
                ),
            ),
            _box(
                identifier="second",
                x_mm=12.0,
            ),
        )
    )

    component = assembly.get("first")
    envelope = component.clearance_envelope

    assembly.analyze_interference(
        clearance_policy=ClearancePolicy(
            component_envelopes={
                "first": ClearanceEnvelope(
                    positive_x_mm=3.0,
                ),
            }
        )
    )

    assert assembly.get("first") is component
    assert component.clearance_envelope is envelope
    assert envelope.positive_x_mm == pytest.approx(0.5)


@pytest.mark.parametrize(
    (
        "edge",
        "expected",
    ),
    (
        (
            "negative_x",
            {
                "negative_x_mm": 2.5,
            },
        ),
        (
            "positive_x",
            {
                "positive_x_mm": 2.5,
            },
        ),
        (
            "negative_y",
            {
                "negative_y_mm": 2.5,
            },
        ),
        (
            "positive_y",
            {
                "positive_y_mm": 2.5,
            },
        ),
    ),
)
def test_for_edge_sets_only_requested_direction(
    edge: str,
    expected: dict[str, float],
) -> None:
    envelope = ClearanceEnvelope.for_edge(
        edge=edge,
        clearance_mm=2.5,
    )

    actual = {
        "negative_x_mm": envelope.negative_x_mm,
        "positive_x_mm": envelope.positive_x_mm,
        "negative_y_mm": envelope.negative_y_mm,
        "positive_y_mm": envelope.positive_y_mm,
        "negative_z_mm": envelope.negative_z_mm,
        "positive_z_mm": envelope.positive_z_mm,
    }

    expected_complete = {
        "negative_x_mm": 0.0,
        "positive_x_mm": 0.0,
        "negative_y_mm": 0.0,
        "positive_y_mm": 0.0,
        "negative_z_mm": 0.0,
        "positive_z_mm": 0.0,
        **expected,
    }

    assert actual == expected_complete
    assert envelope.has_clearance


def test_for_edge_accepts_zero_clearance() -> None:
    envelope = ClearanceEnvelope.for_edge(
        edge="negative_y",
        clearance_mm=0.0,
    )

    assert not envelope.has_clearance
    assert envelope.negative_y_mm == pytest.approx(0.0)


def test_for_edge_rejects_negative_clearance() -> None:
    with pytest.raises(
        ValueError,
        match="clearance_mm",
    ):
        ClearanceEnvelope.for_edge(
            edge="positive_x",
            clearance_mm=-0.1,
        )


def test_for_edge_rejects_unsupported_edge() -> None:
    with pytest.raises(
        ValueError,
        match="unsupported clearance edge",
    ):
        ClearanceEnvelope.for_edge(
            edge="positive_z",
            clearance_mm=1.0,
        )
