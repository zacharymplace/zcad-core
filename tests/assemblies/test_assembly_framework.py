"""Tests for the reusable assembly framework."""

import cadquery as cq
import pytest

from zcad_core.assemblies import (
    AssemblyComponent,
    DeviceAssembly,
    Placement,
)
from zcad_core.geometry.cadquery_support import workplane_shape


def _box(
    width_mm: float,
    depth_mm: float,
    height_mm: float,
) -> cq.Workplane:
    return cq.Workplane("XY").box(
        width_mm,
        depth_mm,
        height_mm,
        centered=(True, True, False),
    )


def test_placement_translates_geometry() -> None:
    component = AssemblyComponent(
        identifier="board",
        geometry=_box(
            20.0,
            10.0,
            2.0,
        ),
        placement=Placement(
            x_mm=15.0,
            y_mm=-4.0,
            z_mm=3.0,
        ),
    )

    bounds = workplane_shape(component.transformed_geometry()).BoundingBox()

    assert bounds.center.x == pytest.approx(15.0)
    assert bounds.center.y == pytest.approx(-4.0)
    assert bounds.zmin == pytest.approx(3.0)


def test_rotation_changes_component_bounds() -> None:
    component = AssemblyComponent(
        identifier="display",
        geometry=_box(
            20.0,
            10.0,
            2.0,
        ),
        placement=Placement(
            rotation_z_deg=90.0,
        ),
    )

    bounds = workplane_shape(component.transformed_geometry()).BoundingBox()

    assert bounds.xlen == pytest.approx(10.0)
    assert bounds.ylen == pytest.approx(20.0)


def test_assembly_preserves_component_order() -> None:
    assembly = DeviceAssembly(
        (
            AssemblyComponent(
                identifier="board",
                geometry=_box(
                    20.0,
                    10.0,
                    2.0,
                ),
            ),
            AssemblyComponent(
                identifier="display",
                geometry=_box(
                    12.0,
                    8.0,
                    1.0,
                ),
            ),
        )
    )

    assert assembly.identifiers == (
        "board",
        "display",
    )
    assert assembly.get("display").identifier == "display"


def test_duplicate_identifier_is_rejected() -> None:
    assembly = DeviceAssembly()

    component = AssemblyComponent(
        identifier="board",
        geometry=_box(
            20.0,
            10.0,
            2.0,
        ),
    )

    assembly.add(component)

    with pytest.raises(
        ValueError,
        match="already exists",
    ):
        assembly.add(component)


def test_assembly_bounds_include_all_components() -> None:
    assembly = DeviceAssembly(
        (
            AssemblyComponent(
                identifier="left",
                geometry=_box(
                    10.0,
                    10.0,
                    2.0,
                ),
                placement=Placement(
                    x_mm=-10.0,
                ),
            ),
            AssemblyComponent(
                identifier="right",
                geometry=_box(
                    10.0,
                    6.0,
                    4.0,
                ),
                placement=Placement(
                    x_mm=10.0,
                    z_mm=3.0,
                ),
            ),
        )
    )

    bounds = assembly.bounds()

    assert bounds.minimum_x_mm == pytest.approx(-15.0)
    assert bounds.maximum_x_mm == pytest.approx(15.0)
    assert bounds.width_mm == pytest.approx(30.0)
    assert bounds.depth_mm == pytest.approx(10.0)
    assert bounds.height_mm == pytest.approx(7.0)


def test_assembly_compound_contains_all_solids() -> None:
    assembly = DeviceAssembly(
        (
            AssemblyComponent(
                identifier="first",
                geometry=_box(
                    4.0,
                    4.0,
                    4.0,
                ),
                placement=Placement(
                    x_mm=-5.0,
                ),
            ),
            AssemblyComponent(
                identifier="second",
                geometry=_box(
                    4.0,
                    4.0,
                    4.0,
                ),
                placement=Placement(
                    x_mm=5.0,
                ),
            ),
        )
    )

    compound = workplane_shape(assembly.compound())

    assert compound.isValid()
    assert len(compound.Solids()) == 2


def test_empty_assembly_has_no_bounds() -> None:
    assembly = DeviceAssembly()

    with pytest.raises(
        ValueError,
        match="at least one component",
    ):
        assembly.bounds()
