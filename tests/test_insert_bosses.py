"""Tests for reusable heat-set insert boss features."""

import cadquery as cq
import pytest

from zcad_core.features.insert_bosses import (
    InsertBossParameters,
    add_heat_set_insert_boss,
)
from zcad_core.geometry.cadquery_support import workplane_shape
from zcad_core.hardware import get_fastener


def test_m3_insert_boss_parameters() -> None:
    parameters = InsertBossParameters.from_fastener(
        fastener=get_fastener("M3"),
        base_height_mm=3.0,
    )

    assert parameters.boss_outer_diameter_mm == pytest.approx(8.2)
    assert parameters.pilot_hole_diameter_mm == 2.5
    assert parameters.insert_pocket_diameter_mm == 4.6
    assert parameters.insert_pocket_depth_mm == 5.0
    assert parameters.boss_height_mm == 6.5


def test_insert_boss_geometry_is_valid() -> None:
    base = cq.Workplane("XY").box(
        20.0,
        20.0,
        3.0,
    )

    model = add_heat_set_insert_boss(
        base,
        parameters=InsertBossParameters.from_fastener(
            fastener=get_fastener("M3"),
            base_height_mm=1.5,
        ),
    )

    solid = workplane_shape(model)
    bounds = solid.BoundingBox()

    assert solid.isValid()
    assert bounds.zlen == pytest.approx(9.5)
    assert solid.Volume() < (20.0 * 20.0 * 3.0 + 3.14159 * (8.2 / 2) ** 2 * 6.5)


def test_boss_height_must_exceed_insert_depth() -> None:
    with pytest.raises(
        ValueError,
        match="must exceed insert pocket depth",
    ):
        InsertBossParameters.from_fastener(
            fastener=get_fastener("M3"),
            base_height_mm=3.0,
            boss_height_mm=5.0,
        )


def test_insert_boss_supports_centered_model_coordinates() -> None:
    base = cq.Workplane("XY").box(
        20.0,
        20.0,
        4.0,
    )

    model = add_heat_set_insert_boss(
        base,
        parameters=InsertBossParameters.from_fastener(
            fastener=get_fastener("M3"),
            base_z_mm=-2.0,
            base_height_mm=4.0,
        ),
    )

    solid = workplane_shape(model)
    bounds = solid.BoundingBox()

    assert solid.isValid()
    assert bounds.zmin == pytest.approx(-2.0)
    assert bounds.zmax == pytest.approx(8.5)
