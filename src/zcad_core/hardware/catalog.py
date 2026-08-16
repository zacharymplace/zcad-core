"""Typed registry for reusable hardware specifications."""

from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar


class HardwareSpec(Protocol):
    """Minimum contract for cataloged hardware."""

    @property
    def identifier(self) -> str:
        """Stable catalog identifier for this specification."""
        ...


HardwareSpecT = TypeVar(
    "HardwareSpecT",
    bound=HardwareSpec,
)


@dataclass(frozen=True)
class HardwareCatalog(Generic[HardwareSpecT]):
    """Immutable hardware specification registry."""

    category: str
    entries: dict[str, HardwareSpecT]

    def __post_init__(self) -> None:
        if not self.category.strip():
            raise ValueError("Hardware catalog category cannot be empty")

        if not self.entries:
            raise ValueError("Hardware catalog must contain at least one entry")

        normalized: set[str] = set()

        for key, specification in self.entries.items():
            normalized_key = self.normalize_identifier(key)

            if normalized_key in normalized:
                raise ValueError(f"Duplicate hardware identifier: {key}")

            if self.normalize_identifier(specification.identifier) != normalized_key:
                raise ValueError(
                    "Hardware catalog key does not match "
                    f"specification identifier: {key}"
                )

            normalized.add(normalized_key)

    @staticmethod
    def normalize_identifier(
        identifier: str,
    ) -> str:
        """Normalize an identifier for stable lookup."""
        normalized = identifier.strip().upper()

        if not normalized:
            raise ValueError("Hardware identifier cannot be empty")

        return normalized

    def get(
        self,
        identifier: str,
    ) -> HardwareSpecT:
        """Return one specification by identifier."""
        normalized = self.normalize_identifier(identifier)

        for key, specification in self.entries.items():
            if self.normalize_identifier(key) == normalized:
                return specification

        raise ValueError(f"Unsupported {self.category}: {identifier}")

    def identifiers(self) -> tuple[str, ...]:
        """Return stable sorted catalog identifiers."""
        return tuple(
            sorted(specification.identifier for specification in self.entries.values())
        )
