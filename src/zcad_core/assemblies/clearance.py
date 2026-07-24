"""Directional component clearance envelopes."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from zcad_core.hardware.electronics.connectors import (
    BoardEdge,
)


@dataclass(frozen=True)
class ClearanceEnvelope:
    """Axis-aligned keep-out distance around a component."""

    negative_x_mm: float = 0.0
    positive_x_mm: float = 0.0

    negative_y_mm: float = 0.0
    positive_y_mm: float = 0.0

    negative_z_mm: float = 0.0
    positive_z_mm: float = 0.0

    @classmethod
    def for_edge(
        cls,
        *,
        edge: BoardEdge,
        clearance_mm: float,
    ) -> "ClearanceEnvelope":
        """Return clearance directed outward through one lateral edge."""
        if clearance_mm < 0:
            raise ValueError("clearance_mm must not be negative")

        values = {
            "negative_x": {
                "negative_x_mm": clearance_mm,
            },
            "positive_x": {
                "positive_x_mm": clearance_mm,
            },
            "negative_y": {
                "negative_y_mm": clearance_mm,
            },
            "positive_y": {
                "positive_y_mm": clearance_mm,
            },
        }

        try:
            parameters = values[edge]
        except KeyError as error:
            raise ValueError(f"unsupported clearance edge: {edge}") from error

        return cls(
            **parameters,
        )

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


@dataclass(frozen=True)
class ClearancePolicy:
    """Immutable analysis-time envelope overrides."""

    component_envelopes: Mapping[
        str,
        ClearanceEnvelope,
    ] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate and freeze component overrides."""
        resolved: dict[str, ClearanceEnvelope] = {}

        for identifier, envelope in self.component_envelopes.items():
            if not identifier.strip():
                raise ValueError("clearance policy identifier must not be empty")

            if not isinstance(
                envelope,
                ClearanceEnvelope,
            ):
                raise TypeError(
                    "clearance policy values must be ClearanceEnvelope instances"
                )

            resolved[identifier] = envelope

        object.__setattr__(
            self,
            "component_envelopes",
            MappingProxyType(resolved),
        )

    def validate_identifiers(
        self,
        identifiers: set[str],
    ) -> None:
        """Reject overrides for unknown components."""
        unknown = set(self.component_envelopes) - identifiers

        if unknown:
            rendered = ", ".join(sorted(unknown))

            raise ValueError(
                f"clearance policy contains unknown component identifiers: {rendered}"
            )

    def envelope_for(
        self,
        identifier: str,
        embedded: ClearanceEnvelope,
    ) -> ClearanceEnvelope:
        """Return the override or embedded envelope."""
        return self.component_envelopes.get(
            identifier,
            embedded,
        )
