"""Core assembly data models."""

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class AssemblyPart:
    """One named part used by an assembly."""

    name: str
    quantity: int = 1

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Assembly part name cannot be empty")

        if self.quantity <= 0:
            raise ValueError("Assembly part quantity must be greater than zero")


@dataclass(frozen=True)
class Mate:
    """Relationship between two assembly parts."""

    parent: str
    child: str
    kind: str
    axis: str
    direction: str
    clearance_mm: float | None = None
    engagement_mm: float | None = None

    def validate(self) -> None:
        if not self.parent.strip():
            raise ValueError("Mate parent cannot be empty")

        if not self.child.strip():
            raise ValueError("Mate child cannot be empty")

        if self.parent == self.child:
            raise ValueError("Mate parent and child must differ")

        if self.kind not in {
            "fixed",
            "sliding_fit",
            "press_fit",
            "snap_fit",
            "fastened",
        }:
            raise ValueError(f"Unsupported mate kind: {self.kind}")

        if self.axis not in {
            "x",
            "y",
            "z",
        }:
            raise ValueError(f"Unsupported mate axis: {self.axis}")

        if self.direction not in {
            "positive",
            "negative",
            "none",
        }:
            raise ValueError(f"Unsupported mate direction: {self.direction}")

        if self.clearance_mm is not None and self.clearance_mm < 0:
            raise ValueError("Mate clearance cannot be negative")

        if self.engagement_mm is not None and self.engagement_mm <= 0:
            raise ValueError("Mate engagement must be greater than zero")


@dataclass(frozen=True)
class Assembly:
    """Declarative description of a multi-part design."""

    assembly_id: str
    reference_part: str
    parts: tuple[AssemblyPart, ...]
    relationships: tuple[Mate, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable assembly record."""
        return {
            "schema_version": "1.0",
            "assembly_id": self.assembly_id,
            "reference_part": self.reference_part,
            "parts": [asdict(part) for part in self.parts],
            "relationships": [
                asdict(relationship) for relationship in self.relationships
            ],
        }
