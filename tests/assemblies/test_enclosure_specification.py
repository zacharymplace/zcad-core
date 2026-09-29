"""Tests for assembly-derived enclosure specifications."""

from dataclasses import dataclass, field
from typing import Any

import pytest

from zcad_core.assemblies import (
    DeviceAssembly,
    Placement,
    build_board_display_assembly,
    derive_enclosure_specification,
)
from zcad_core.hardware import RectangularConnectorSpec


def _negative_y_connector() -> RectangularConnectorSpec:
    return RectangularConnectorSpec(
        identifier="TEST_USB",
        width_mm=8.0,
        height_mm=3.0,
        depth_mm=6.0,
        board_edge="negative_y",
    )


def _positive_y_connector() -> RectangularConnectorSpec:
    return RectangularConnectorSpec(
        identifier="TEST_USB_C",
        width_mm=9.0,
        height_mm=3.2,
        depth_mm=7.0,
        board_edge="positive_y",
    )


@dataclass(frozen=True)
class FixtureBoardSpec:
    identifier: str = "TEST_BOARD"
    board_width_mm: float = 18.0
    board_length_mm: float = 24.0
    board_thickness_mm: float = 1.0
    usb_connector: RectangularConnectorSpec = field(
        default_factory=_negative_y_connector
    )


@dataclass(frozen=True)
class PositiveYBoardSpec:
    identifier: str = "POSITIVE_Y_BOARD"
    board_width_mm: float = 18.0
    board_length_mm: float = 24.0
    board_thickness_mm: float = 1.0
    usb_connector: RectangularConnectorSpec = field(
        default_factory=_positive_y_connector
    )


@dataclass(frozen=True)
class FixtureDisplaySpec:
    identifier: str = "TEST_DISPLAY"
    module_width_mm: float = 28.0
    module_height_mm: float = 15.0
    module_depth_mm: float = 4.0
    mount_style: str = "test"


def _assembly(
    *,
    board: FixtureBoardSpec | PositiveYBoardSpec | None = None,
) -> DeviceAssembly:
    return build_board_display_assembly(
        board=board if board is not None else FixtureBoardSpec(),
        display=FixtureDisplaySpec(),
        board_placement=Placement(z_mm=3.0),
        display_placement=Placement(
            y_mm=5.0,
            z_mm=8.0,
        ),
        board_display_clearance_mm=0.5,
        connector_access_clearance_mm=2.0,
        connector_identifier="usb_connector",
    )


def test_derivation_includes_component_and_clearance_bounds() -> None:
    specification = derive_enclosure_specification(
        _assembly(),
        internal_clearance_mm=2.0,
    )

    assert specification.inner_width_mm == pytest.approx(32.0)
    assert specification.inner_depth_mm > 28.0
    assert specification.inner_height_mm == pytest.approx(13.0)


def test_directional_clearances_override_the_internal_clearance() -> None:
    uniform = derive_enclosure_specification(_assembly(), internal_clearance_mm=2.0)
    directional = derive_enclosure_specification(
        _assembly(),
        internal_clearance_mm=2.0,
        side_clearance_mm=5.0,
        bottom_clearance_mm=3.0,
        top_clearance_mm=0.5,
    )

    assert directional.inner_width_mm == pytest.approx(uniform.inner_width_mm + 6)
    assert directional.inner_depth_mm == pytest.approx(uniform.inner_depth_mm + 6)
    assert directional.inner_height_mm == pytest.approx(
        uniform.inner_height_mm + 1 - 1.5
    )
    assert directional.bottom_z_mm == pytest.approx(uniform.bottom_z_mm - 1)
    assert directional.center_x_mm == pytest.approx(uniform.center_x_mm)
    assert directional.center_y_mm == pytest.approx(uniform.center_y_mm)


def test_negative_y_connector_drives_cable_edge() -> None:
    specification = derive_enclosure_specification(
        _assembly(),
        connector_cutout_clearance_mm=0.5,
    )

    assert specification.connector_identifier == "usb_connector"
    assert specification.cable_edge == "negative_y"
    assert specification.cable_width_mm == pytest.approx(9.0)
    assert specification.cable_height_mm == pytest.approx(4.0)


def test_positive_y_connector_drives_cable_edge() -> None:
    specification = derive_enclosure_specification(
        _assembly(board=PositiveYBoardSpec())
    )

    assert specification.cable_edge == "positive_y"


def test_cutout_clearance_expands_opening() -> None:
    specification = derive_enclosure_specification(
        _assembly(),
        connector_cutout_clearance_mm=1.0,
    )

    assert specification.cable_width_mm == pytest.approx(10.0)
    assert specification.cable_height_mm == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("keyword", "value", "message"),
    [
        (
            "internal_clearance_mm",
            -0.1,
            "internal_clearance_mm",
        ),
        (
            "connector_cutout_clearance_mm",
            -0.1,
            "connector_cutout_clearance_mm",
        ),
        ("side_clearance_mm", -0.1, "side_clearance_mm"),
        ("bottom_clearance_mm", -0.1, "bottom_clearance_mm"),
        ("top_clearance_mm", -0.1, "top_clearance_mm"),
    ],
)
def test_derivation_rejects_negative_clearances(
    keyword: str,
    value: float,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        overrides: dict[str, Any] = {keyword: value}
        derive_enclosure_specification(_assembly(), **overrides)


def test_derivation_rejects_missing_connector() -> None:
    with pytest.raises(KeyError, match="missing_connector"):
        derive_enclosure_specification(
            _assembly(),
            connector_identifier="missing_connector",
        )
