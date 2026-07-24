"""Directional component clearance envelopes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ClearanceEnvelope:
    """Axis-aligned keep-out distance around a component."""

    negative_x_mm: float = 0.0
    positive_x_mm: float = 0.0

    negative_y_mm: float = 0.0
    positive_y_mm: float = 0.0

    negative_z_mm: float = 0.0
    positive_z_mm: float = 0.0

    def __post_init__(self) -> None:
        """Validate directional clearance distances."""
        values = {
            "negative_x_mm": self.negative_x_mm,
            "positive_x_mm": self.positive_x_mm,
            "negative_y_mm": self.negative_y_mm,
            "positive_y_mm": self.positive_y_mm,
            "negative_z_mm": self.negative_z_mm,
            "positive_z_mm": self.positive_z_mm,
        }

        for name, value in values.items():
            if value < 0:
                raise ValueError(f"{name} must not be negative")

    @property
    def has_clearance(self) -> bool:
        """Return whether any direction requires clearance."""
        return any(
            (
                self.negative_x_mm,
                self.positive_x_mm,
                self.negative_y_mm,
                self.positive_y_mm,
                self.negative_z_mm,
                self.positive_z_mm,
            )
        )

    def negative_for_axis(
        self,
        axis: str,
    ) -> float:
        """Return negative-direction clearance for one axis."""
        if axis == "x":
            return self.negative_x_mm

        if axis == "y":
            return self.negative_y_mm

        if axis == "z":
            return self.negative_z_mm

        raise ValueError(f"unsupported clearance axis: {axis}")

    def positive_for_axis(
        self,
        axis: str,
    ) -> float:
        """Return positive-direction clearance for one axis."""
        if axis == "x":
            return self.positive_x_mm

        if axis == "y":
            return self.positive_y_mm

        if axis == "z":
            return self.positive_z_mm

        raise ValueError(f"unsupported clearance axis: {axis}")
