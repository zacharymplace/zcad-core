"""Reusable heat-set insert boss features."""

from dataclasses import dataclass

import cadquery as cq

from zcad_core.hardware import FastenerSpec


@dataclass(frozen=True)
class InsertBossParameters:
    """Geometry parameters for one heat-set insert boss."""

    x: float
    y: float
    base_height_mm: float
    boss_height_mm: float
    boss_outer_diameter_mm: float
    pilot_hole_diameter_mm: float
    insert_pocket_diameter_mm: float
    insert_pocket_depth_mm: float

    @classmethod
    def from_fastener(
        cls,
        *,
        fastener: FastenerSpec,
        x: float = 0.0,
        y: float = 0.0,
        base_height_mm: float,
        boss_height_mm: float | None = None,
        radial_wall_mm: float = 1.8,
    ) -> "InsertBossParameters":
        """Derive insert-boss geometry from a fastener specification."""
        insert_diameter = fastener.heat_set_insert_diameter_mm
        insert_depth = fastener.heat_set_insert_depth_mm

        if insert_diameter is None or insert_depth is None:
            raise ValueError(
                f"Fastener does not define heat-set insert dimensions: "
                f"{fastener.identifier}"
            )

        if base_height_mm <= 0:
            raise ValueError("base_height_mm must be greater than zero")

        if radial_wall_mm <= 0:
            raise ValueError("radial_wall_mm must be greater than zero")

        resolved_height = (
            boss_height_mm if boss_height_mm is not None else insert_depth + 1.5
        )

        if resolved_height <= insert_depth:
            raise ValueError("boss_height_mm must exceed insert pocket depth")

        return cls(
            x=x,
            y=y,
            base_height_mm=base_height_mm,
            boss_height_mm=resolved_height,
            boss_outer_diameter_mm=(insert_diameter + (2 * radial_wall_mm)),
            pilot_hole_diameter_mm=fastener.tap_hole_mm,
            insert_pocket_diameter_mm=insert_diameter,
            insert_pocket_depth_mm=insert_depth,
        )

    def validate(self) -> None:
        """Validate derived insert-boss geometry."""
        positive_values = {
            "base_height_mm": self.base_height_mm,
            "boss_height_mm": self.boss_height_mm,
            "boss_outer_diameter_mm": self.boss_outer_diameter_mm,
            "pilot_hole_diameter_mm": self.pilot_hole_diameter_mm,
            "insert_pocket_diameter_mm": self.insert_pocket_diameter_mm,
            "insert_pocket_depth_mm": self.insert_pocket_depth_mm,
        }

        for name, value in positive_values.items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")

        if self.boss_outer_diameter_mm <= self.insert_pocket_diameter_mm:
            raise ValueError("boss outer diameter must exceed insert pocket diameter")

        if self.insert_pocket_diameter_mm <= self.pilot_hole_diameter_mm:
            raise ValueError("insert pocket diameter must exceed pilot hole diameter")

        if self.boss_height_mm <= self.insert_pocket_depth_mm:
            raise ValueError("boss height must exceed insert pocket depth")


def add_heat_set_insert_boss(
    model: cq.Workplane,
    *,
    parameters: InsertBossParameters,
) -> cq.Workplane:
    """Add one heat-set insert boss and cut its stepped bore."""
    parameters.validate()

    boss = (
        cq.Workplane("XY")
        .center(
            parameters.x,
            parameters.y,
        )
        .workplane(
            offset=parameters.base_height_mm,
        )
        .circle(
            parameters.boss_outer_diameter_mm / 2,
        )
        .extrude(
            parameters.boss_height_mm,
        )
    )

    combined = model.union(boss)

    pilot_hole = (
        cq.Workplane("XY")
        .center(
            parameters.x,
            parameters.y,
        )
        .circle(
            parameters.pilot_hole_diameter_mm / 2,
        )
        .extrude(
            parameters.base_height_mm + parameters.boss_height_mm,
        )
    )

    insert_pocket = (
        cq.Workplane("XY")
        .center(
            parameters.x,
            parameters.y,
        )
        .workplane(
            offset=(
                parameters.base_height_mm
                + parameters.boss_height_mm
                - parameters.insert_pocket_depth_mm
            ),
        )
        .circle(
            parameters.insert_pocket_diameter_mm / 2,
        )
        .extrude(
            parameters.insert_pocket_depth_mm,
        )
    )

    return combined.cut(pilot_hole.union(insert_pocket))
