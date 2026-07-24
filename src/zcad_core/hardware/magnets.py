"""Reusable cylindrical magnet specifications."""

from dataclasses import dataclass

from zcad_core.hardware.catalog import HardwareCatalog


@dataclass(frozen=True)
class MagnetSpec:
    """Engineering dimensions for one cylindrical magnet."""

    identifier: str
    diameter_mm: float
    thickness_mm: float
    radial_pocket_oversize_mm: float = 0.15
    depth_pocket_oversize_mm: float = 0.1

    def validate(self) -> None:
        """Validate magnet dimensions and pocket allowances."""
        if self.diameter_mm <= 0:
            raise ValueError("Magnet diameter must be greater than zero")

        if self.thickness_mm <= 0:
            raise ValueError("Magnet thickness must be greater than zero")

        if self.radial_pocket_oversize_mm < 0:
            raise ValueError("Magnet radial pocket oversize cannot be negative")

        if self.depth_pocket_oversize_mm < 0:
            raise ValueError("Magnet depth pocket oversize cannot be negative")

    @property
    def pocket_diameter_mm(self) -> float:
        """Return the recommended cylindrical pocket diameter."""
        self.validate()

        return self.diameter_mm + 2 * self.radial_pocket_oversize_mm

    @property
    def pocket_depth_mm(self) -> float:
        """Return the recommended cylindrical pocket depth."""
        self.validate()

        return self.thickness_mm + self.depth_pocket_oversize_mm


_MAGNET_ENTRIES = {
    "D6X2": MagnetSpec(
        identifier="D6X2",
        diameter_mm=6.0,
        thickness_mm=2.0,
    ),
    "D8X3": MagnetSpec(
        identifier="D8X3",
        diameter_mm=8.0,
        thickness_mm=3.0,
    ),
    "D10X3": MagnetSpec(
        identifier="D10X3",
        diameter_mm=10.0,
        thickness_mm=3.0,
    ),
    "D12X3": MagnetSpec(
        identifier="D12X3",
        diameter_mm=12.0,
        thickness_mm=3.0,
    ),
}


MAGNET_CATALOG = HardwareCatalog(
    category="magnet",
    entries=_MAGNET_ENTRIES,
)


def get_magnet(
    identifier: str,
) -> MagnetSpec:
    """Return one cylindrical magnet specification."""
    magnet = MAGNET_CATALOG.get(identifier)
    magnet.validate()

    return magnet


def list_magnets() -> tuple[str, ...]:
    """Return supported magnet identifiers."""
    return MAGNET_CATALOG.identifiers()
