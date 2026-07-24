"""Tests for generic rectangular board-display assemblies."""

from dataclasses import dataclass, field

import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    analyze_board_display_assembly,
    build_board_display_assembly,
)
from zcad_core.hardware import (
    RectangularConnectorSpec,
)


def _connector() -> RectangularConnectorSpec:
    return RectangularConnectorSpec(
        identifier="TEST_USB",
        width_mm=8.0,
        depth_mm=6.0,
        height_mm=3.0,
        board_edge="negative_y",
        center_offset_mm=1.0,
        bottom_offset_from_board_top_mm=0.5,
    )


@dataclass(frozen=True)
class StubBoard:
    identifier: str = "TEST_BOARD"

    board_width_mm: float = 20.0
    board_length_mm: float = 50.0
    board_thickness_mm: float = 1.0

    usb_connector: RectangularConnectorSpec = field(default_factory=_connector)


@dataclass(frozen=True)
class StubDisplay:
    identifier: str = "TEST_DISPLAY"

    module_width_mm: float = 30.0
    module_height_mm: float = 20.0
    module_depth_mm: float = 4.0

    mount_style: str = "bezel"


def _assembly(
    *,
    display_z_mm: float = 8.0,
    embedded_clearance_mm: float = 0.5,
    connector_clearance_mm: float = 2.0,
) -> DeviceAssembly:
    return build_board_display_assembly(
        board=StubBoard(),
        display=StubDisplay(),
        board_placement=Placement(
            x_mm=2.0,
            y_mm=-3.0,
            z_mm=3.0,
        ),
        display_placement=Placement(
            x_mm=-4.0,
            y_mm=5.0,
            z_mm=display_z_mm,
        ),
        board_display_clearance_mm=(embedded_clearance_mm),
        connector_access_clearance_mm=(connector_clearance_mm),
    )


def test_builds_board_connector_and_display() -> None:
    assembly = _assembly()

    assert assembly.identifiers == (
        "board",
        "board_connector",
        "display",
    )

    assert assembly.get("board").metadata["hardware_identifier"] == "TEST_BOARD"

    assert assembly.get("display").metadata["hardware_identifier"] == "TEST_DISPLAY"


def test_reuses_authoritative_board_placement() -> None:
    assembly = _assembly()

    board = assembly.get("board")
    connector = assembly.get("board_connector")

    assert board.placement == Placement(
        x_mm=2.0,
        y_mm=-3.0,
        z_mm=3.0,
    )

    assert connector.placement.x_mm == (pytest.approx(3.0))
    assert connector.placement.y_mm == (pytest.approx(-25.0))
    assert connector.placement.z_mm == (pytest.approx(4.5))


def test_preserves_display_metadata() -> None:
    display = _assembly().get("display")

    assert display.metadata == {
        "kind": "display",
        "hardware_identifier": "TEST_DISPLAY",
        "width_mm": 30.0,
        "depth_mm": 20.0,
        "height_mm": 4.0,
        "mount_style": "bezel",
    }


def test_embeds_directional_clearances() -> None:
    assembly = _assembly(
        embedded_clearance_mm=1.25,
        connector_clearance_mm=3.0,
    )

    board = assembly.get("board")
    connector = assembly.get("board_connector")

    assert board.clearance_envelope.positive_z_mm == pytest.approx(1.25)

    assert connector.clearance_envelope.negative_y_mm == pytest.approx(3.0)


def test_analyzer_allows_connector_attachment() -> None:
    report = analyze_board_display_assembly(
        _assembly(),
        minimum_board_display_clearance_mm=0.5,
    )

    assert not report.has_findings


def test_analyzer_reports_board_display_collision() -> None:
    report = analyze_board_display_assembly(
        _assembly(
            display_z_mm=3.5,
        ),
        minimum_board_display_clearance_mm=0.5,
    )

    assert len(report.collisions) == 1
    assert report.collisions[0].pair == {
        "board",
        "display",
    }


def test_analyzer_reports_clearance_violation() -> None:
    report = analyze_board_display_assembly(
        _assembly(
            display_z_mm=4.25,
        ),
        minimum_board_display_clearance_mm=0.5,
    )

    assert not report.collisions
    assert len(report.clearance_violations) == 1

    finding = report.clearance_violations[0]

    assert finding.measured_clearance_mm == (pytest.approx(0.25))
    assert finding.required_clearance_mm == (pytest.approx(0.5))


def test_custom_identifiers_are_supported() -> None:
    assembly = build_board_display_assembly(
        board=StubBoard(),
        display=StubDisplay(),
        board_placement=Placement(),
        display_placement=Placement(
            z_mm=6.0,
        ),
        board_identifier="controller",
        connector_identifier="power_port",
        display_identifier="screen",
    )

    report = analyze_board_display_assembly(
        assembly,
        board_identifier="controller",
        connector_identifier="power_port",
        display_identifier="screen",
    )

    assert assembly.identifiers == (
        "controller",
        "power_port",
        "screen",
    )
    assert not report.has_findings


@pytest.mark.parametrize(
    (
        "field",
        "value",
        "message",
    ),
    (
        (
            "board_display_clearance_mm",
            -0.1,
            "board_display_clearance_mm",
        ),
        (
            "connector_access_clearance_mm",
            -0.1,
            "connector_access_clearance_mm",
        ),
        (
            "board_identifier",
            "",
            "identifiers",
        ),
    ),
)
def test_builder_rejects_invalid_policy(
    field: str,
    value: float | str,
    message: str,
) -> None:
    arguments = {
        "board": StubBoard(),
        "display": StubDisplay(),
        "board_placement": Placement(),
        "display_placement": Placement(
            z_mm=6.0,
        ),
        "board_display_clearance_mm": 0.0,
        "connector_access_clearance_mm": 0.0,
        "board_identifier": "board",
    }

    arguments[field] = value

    with pytest.raises(
        ValueError,
        match=message,
    ):
        build_board_display_assembly(
            **arguments,
        )


def test_builder_rejects_duplicate_identifiers() -> None:
    with pytest.raises(
        ValueError,
        match="unique",
    ):
        build_board_display_assembly(
            board=StubBoard(),
            display=StubDisplay(),
            board_placement=Placement(),
            display_placement=Placement(
                z_mm=6.0,
            ),
            board_identifier="hardware",
            connector_identifier="hardware",
        )


def test_analyzer_rejects_wrong_component_set() -> None:
    with pytest.raises(
        ValueError,
        match="must contain exactly",
    ):
        analyze_board_display_assembly(
            DeviceAssembly(),
        )


def test_analyzer_rejects_negative_clearance() -> None:
    with pytest.raises(
        ValueError,
        match="minimum_board_display_clearance_mm",
    ):
        analyze_board_display_assembly(
            _assembly(),
            minimum_board_display_clearance_mm=-0.1,
        )
